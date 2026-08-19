"""`Citizen`: the instance type of a first-class citizen.

Subclasses declare fields, never behaviour; behaviour belongs to `Manager`.

    class Goal(Citizen, store=YamlList("goal/core/goals.yaml", "goals"), key="slug"):
        area:  Area                     # live reference, reflected as a schema enum
        title: str = maxlen(30)
        status: str = founder_only("active")

Five hard properties:

1. A missing `get()` raises `CitizenNotFound` rather than returning None.
2. `keys()` is the only source of a closed set — schema enums, foreign-key
   checks and command candidate lists all read it.
3. Field declaration order is persistence order. `upsert()` assembles by
   `__fields__` order, which is what keeps writes byte-aligned with the appliers.
4. Reads never run invariants: `all()`/`get()` only load and dereference, while
   `check()` runs after writes and in ops. Otherwise one hand-broken field takes
   down the whole read surface, which is worse than the problem itself.
5. A reference that fails to resolve becomes `BrokenRef` instead of raising: one
   bad reference must not make `all()` unusable, and `check()` reports it. Not in
   conflict with (1): `get(missing)` means "what you asked for is not there",
   while a dangling row inside `all()` means "one datum is broken".

stdlib + `domain/{field,store}.py` only. Never import pydantic or brain-mcp.
"""
import copy
from collections import Counter
import re
import typing

from .field import MISSING, Field
from .operation import ValidatorSpec, current_operation
from .store import InjectedDocumentStore, InjectedStore, StoreError  # noqa: F401  re-exported for citizens

# The *default* primary-key shape (slug): the default pattern for
# `__key_field__`, not a second hard gate. The primary-key contract has exactly
# one source, `cls.__key_field__` — a citizen whose key is not a slug (workitem's
# is `workitem://<project>/<id>`) would otherwise declare `key_field=` and still
# be rejected by a gate above it, and a contract point that is declared but has
# no effect is worse than none.
#
# The same regex also lives in `brain-mcp/kernel/boundary/ingress.py::SLUG_RE`,
# which is the bus ingress security boundary against path traversal. The two must
# stay identical; `domain/ops/selftest_domain_kernel.py` asserts it.
KEY_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")


class CitizenError(RuntimeError):
    """Generic citizen-layer failure."""


class CitizenNotFound(KeyError):
    """No row for this key. Subclasses KeyError on purpose: callers already catch that."""


class ConflictError(CitizenError):
    """CAS precondition failed: someone changed the row after you read it.

    Deliberately distinct from InvariantError, which means "what you wrote is
    illegal". The correct caller response differs: fix the content and retry
    versus re-read and retry.
    """


class InvariantError(CitizenError):
    """An invariant does not hold; the write path rolls back on it."""


class BrokenRef:
    """A reference that does not resolve. Reads still return it; `check()` reports it."""

    __slots__ = ("raw", "target")

    def __init__(self, raw, target):
        self.raw, self.target = raw, target

    def __bool__(self):
        return False

    def __eq__(self, other):
        return isinstance(other, BrokenRef) and self.raw == other.raw

    def __repr__(self):
        return "<BrokenRef %s→%s>" % (self.raw, getattr(self.target, "__name__", "?"))


_REGISTRY = {}


def registry():
    """Every declared citizen type. Used by the structural gates in `domain/ops/`."""
    return dict(_REGISTRY)


def _collect_fields(cls):
    """Collect fields in `__annotations__` declaration order. Order is persistence
    order, so never sort."""
    fields = {}
    for base in reversed(cls.__mro__[1:]):
        fields.update(getattr(base, "__fields__", {}) or {})
    for name, annotation in (cls.__dict__.get("__annotations__") or {}).items():
        if name.startswith("_"):
            continue
        raw = cls.__dict__.get(name, MISSING)
        spec = raw if isinstance(raw, Field) else Field(raw)
        spec.name = name
        spec.source = spec.source or name          # storage key defaults to the attribute name
        spec.annotation = annotation
        if isinstance(annotation, type) and issubclass(annotation, Citizen):
            spec.ref_to = annotation
        origin = typing.get_origin(annotation)
        args = typing.get_args(annotation)
        if spec.item is not None and origin in (list, tuple) and args:
            spec.item.name = name + "[]"
            spec.item.annotation = args[0]
        fields[name] = spec
        if isinstance(raw, Field):
            delattr(cls, name)          # don't leave the Field object posing as a default
    return fields


def _is_optional(spec):
    """Whether a field may be absent. The only criterion: is the annotation `X | None`."""
    from .field import _unwrap_optional
    _base, optional = _unwrap_optional(spec.annotation)
    return optional


def _collect_invariants(cls):
    out = []
    for name in dir(cls):
        if name.startswith("__"):
            continue
        member = getattr(cls, name, None)
        scope = getattr(member, "__invariant__", None)
        if scope:
            out.append((name, member, scope))
    return out


# ── Field machinery, shared by `Citizen` and `Document` ──────────────────────
#
# Functions rather than a mixin: the two base classes handle primary keys
# completely differently (one has one, the other has none at all), so mixing them
# into the inheritance chain would force `if self.__key__ is None` everywhere.
# A function takes only what it actually needs.

def _assign(obj, cls, values, key_name=None):
    """Spread values onto the instance: declared fields fall back to their default,
    undeclared ones go to `_extra`."""
    obj._extra = {}
    for name, spec in cls.__fields__.items():
        if name in values:
            setattr(obj, name, values[name])
        else:
            default = spec.get_default()
            setattr(obj, name, None if default is MISSING else default)
    for key, value in values.items():
        if key not in cls.__fields__ and key != key_name:
            obj._extra[key] = value


def _resolve_row(cls, row, key_name=None):
    """Raw row → (constructible kwargs, missing required fields). Refs resolve here."""
    data = dict(row)
    resolved = {}
    for name, spec in cls.__fields__.items():
        source = spec.source or name
        if source not in data:
            continue
        value = data.pop(source)
        if spec.ref_to is not None and isinstance(value, str):
            try:
                value = spec.ref_to.get(value)
            except CitizenNotFound:
                value = BrokenRef(value, spec.ref_to)             # property 5
        resolved[name] = value
    if key_name is not None:
        resolved[key_name] = row.get(key_name)
        data.pop(key_name, None)
    resolved.update(data)
    # "Missing" only applies to required fields. Optional means the annotation
    # carries `| None` — the same criterion `Field.violations` uses. Don't start
    # a second one here.
    missing = {name for name, spec in cls.__fields__.items()
               if (spec.source or name) not in row and not _is_optional(spec)}
    if key_name is not None and key_name not in row:
        missing.add(key_name)
    return resolved, missing


def _field_errors(obj, cls, label, *, include_invariants=True):
    """Field contract and, by default, instance invariants.

    ``include_invariants=False`` is the declaration-shape boundary: it validates
    the reflected field contract without consulting injected runtime stores.  A
    repo declaration validator can therefore stay deterministic and dependency
    free while the normal post-write ``check()`` path remains strict.

    No primary-key check: that is `Citizen`-only.
    """
    errors = []
    if obj._extra:
        errors.append("%s 有未声明字段:%s" % (label, sorted(obj._extra)))
    missing = sorted(getattr(obj, "_missing", ()))
    if missing:
        errors.append("%s 缺必填字段:%s" % (label, missing))
    for name, spec in cls.__fields__.items():
        value = getattr(obj, name, None)
        if isinstance(value, BrokenRef):
            errors.append("%s.%s 指不到:%s" % (label, name, value.raw))
            continue
        # Shape constraints (minlen/maxlen/pattern/choices/range/array), one-to-one with JSON Schema
        errors.extend("%s.%s" % (label, error) for error in spec.violations(value))
    if include_invariants:
        for name, _member, scope in cls.__invariants__:
            if scope != "instance":
                continue
            try:
                getattr(obj, name)()
            except AssertionError as error:
                errors.append("%s: %s" % (label, error or name))
    return errors


_WRITE_INTERFACE = ("lock", "snapshot", "restore", "write_entry", "read")


def _writable(cls):
    """The store a write path needs. The criterion is whether it has a write port,
    never which class it is: a type whitelist rejects "not one of the two I know
    about", which is a different thing from "has no write port".
    """
    store = cls.__store__
    if store is None:
        raise CitizenError("%s 没有 store,写不了" % cls.__name__)
    missing = [name for name in _WRITE_INTERFACE if not hasattr(store, name)]
    if missing:
        raise CitizenError("%s 的 store(%s)缺写口:%s"
                           % (cls.__name__, type(store).__name__, missing))
    return store


def spec_source(cls, name):
    """The field's key *in storage* (defaults to the attribute name)."""
    spec = cls.__fields__[name]
    return spec.source or name


def _ordered_dict(obj, cls, out):
    """Emit field values in declaration order. Refs collapse back to keys; None is
    not persisted."""
    for name in cls.__fields__:
        value = getattr(obj, name, None)
        if value is None:
            continue
        if isinstance(value, Citizen):
            value = value.key
        elif isinstance(value, BrokenRef):
            value = value.raw
        out[spec_source(cls, name)] = (copy.deepcopy(value)
                                       if isinstance(value, (list, dict)) else value)
    out.update(getattr(obj, "_extra", {}) or {})
    return out


class Citizen:
    __store__ = None
    __key__ = "slug"
    __key_param__ = "slug"
    __addressable__ = True
    __fields__ = {}
    __key_field__ = None
    __invariants__ = ()

    def __init_subclass__(cls, *, store=None, key="slug", key_field=None,
                          key_param=None, addressable=True, **kw):
        """`key` is the key in storage; `key_param` is the parameter name in the
        operation signature.

        They default to the same name. workitem's storage column is `ref`
        (`workitem://<project>/<id>`) while its tool parameter has always been
        `workitem_ref`; making `__key__` serve both would leak a storage
        implementation detail out as a breaking tool rename.

        Only workitem needs this. Do not spell it out on the others for symmetry
        — that dilutes the signal that these are two separate things.
        """
        super().__init_subclass__(**kw)
        cls.__store__ = store
        cls.__key__ = key
        cls.__key_param__ = key_param or key
        # Whether `<scheme>://<key>` can address it. True by default, the normal
        # case for a citizen. Vocabulary entries such as architecture's
        # `Axis`/`NodeKind`/`EdgeRel` cannot: nothing in the system writes
        # `axis://declaration`, and declaring them addressable would add three
        # schemes to the manifest's `refs.schemes` that nothing can resolve —
        # exactly what the `selftest_ref_schemes` all-five-or-nowhere gate blocks.
        cls.__addressable__ = addressable
        cls.__key_field__ = key_field or Field(nonempty=True, pattern=KEY_RE.pattern)
        cls.__key_field__.name = key
        cls.__key_field__.annotation = str
        cls.__fields__ = _collect_fields(cls)
        cls.__invariants__ = _collect_invariants(cls)
        _REGISTRY[cls.__name__] = cls

    # ── Construction ─────────────────────────────────────────────────────
    def __init__(self, **values):
        cls = self.__class__
        setattr(self, cls.__key__, values.get(cls.__key__))
        _assign(self, cls, values, key_name=cls.__key__)

    @classmethod
    def _from_row(cls, row):
        resolved, missing = _resolve_row(cls, row, key_name=cls.__key__)
        obj = cls(**resolved)
        obj._row = dict(row)
        obj._missing = missing
        return obj

    # ── Class-level read surface (properties 1/2/4) ──────────────────────
    @classmethod
    def rows(cls):
        """Raw rows, no dereferencing. Used by write paths and schema enums, which
        keeps dereferencing from recursing."""
        if cls.__store__ is None:
            raise CitizenError("%s 没有 store,读不了" % cls.__name__)
        return cls.__store__.read()

    @classmethod
    def all(cls):
        return [cls._from_row(r) for r in cls.rows()]

    @classmethod
    def get(cls, key):
        for row in cls.rows():
            if row.get(cls.__key__) == key:
                return cls._from_row(row)
        raise CitizenNotFound("%s://%s" % (cls.scheme(), key))

    @classmethod
    def keys(cls, **where):
        """The closed set. `where` filters raw rows by equality (e.g. `status="active"`).

        The only source of a schema enum. Goes through `rows()`, not `all()`: a
        closed set needs no dereferencing, and dereferencing calls `keys()` back.
        """
        out = []
        for row in cls.rows():
            if all(row.get(k) == v for k, v in where.items()):
                key = row.get(cls.__key__)
                if key:
                    out.append(key)
        return out

    @classmethod
    def scheme(cls):
        """The ref scheme is the lowercased class name: `Area` → `area://`."""
        return cls.__name__.lower()

    @property
    def key(self):
        return getattr(self, self.__class__.__key__, None)

    @classmethod
    def ref_of(cls, key):
        """`<scheme>://<key>`, unless the primary key is already a typed ref.

        workitem's key *is* `workitem://<project>/<id>`, its real column value, so
        prefixing again yields `workitem://workitem://…`.

        A classmethod, because a same-named instance attribute shadows the method:
        when the key field is called `ref`, `self.ref` is that string and
        `self.ref()` TypeErrors. Always go through this entry point internally.
        """
        prefix = cls.scheme() + "://"
        text = str(key)
        return text if text.startswith(prefix) else prefix + text

    def ref(self):
        return self.__class__.ref_of(self.key)

    # ── Persistence shape (property 3) ───────────────────────────────────
    def to_dict(self, with_key=False):
        """Emit in declaration order. With `with_key`, the primary key goes first, to
        match the YAML list-item shape."""
        out = {self.__class__.__key__: self.key} if with_key else {}
        return _ordered_dict(self, self.__class__, out)

    # ── Invariants (property 4) ──────────────────────────────────────────
    @classmethod
    def _check_key(cls, key):
        """Primary-key shape. The only criterion is `__key_field__`; see `KEY_RE` above."""
        errors = cls.__key_field__.violations(key)
        if errors:
            raise CitizenError("%s: %s" % (cls.__name__, "; ".join(errors)))

    def check(self):
        """Run the strict field contract, references and invariants. Returns error
        strings; empty means pass."""
        errors = []
        errors.extend("%s.%s" % (self.__class__.__name__, error)
                      for error in self.__class__.__key_field__.violations(self.key))
        errors.extend(_field_errors(self, self.__class__,
                                    self.__class__.ref_of(self.key)))
        return errors

    def check_shape(self):
        """Validate only the stored declaration shape, not runtime invariants.

        Runtime-backed citizens use this at repo/CI declaration boundaries.  The
        regular ``check()`` method is still the post-write contract and continues
        to run every instance invariant.
        """
        errors = []
        errors.extend("%s.%s" % (self.__class__.__name__, error)
                      for error in self.__class__.__key_field__.violations(self.key))
        errors.extend(_field_errors(self, self.__class__,
                                    self.__class__.ref_of(self.key),
                                    include_invariants=False))
        return errors

    @classmethod
    def check_all(cls):
        # The original guarded this with `isinstance(store, (YamlList, YamlDir))`,
        # because only a file-backed store has a document whose shape can be
        # wrong. An injected store answers `[]` — the database enforces its own
        # schema — so asking it directly says the same thing without a type
        # whitelist, which is the rule `_writable` states a few lines below.
        errors = list(cls.__store__.document_errors())
        items = cls.all()
        errors.extend(e for item in items for e in item.check())
        duplicates = sorted(key for key, count in Counter(item.key for item in items).items()
                            if count > 1)
        if duplicates:
            errors.append("%s 主键重复:%s" % (cls.__name__, duplicates))
        for name, member, scope in cls.__invariants__:
            if scope != "all":
                continue
            try:
                member(items)
            except AssertionError as error:
                errors.append("%s: %s" % (cls.__name__, error or name))
        return errors

    # ── Writes (the other half of property 3) ────────────────────────────
    @classmethod
    def upsert(cls, key, changes, expected=None, *, server=None, after_write=None):
        """Idempotent upsert into the declaration source. The five common steps live
        here, not copied into every method body.

        Merge rules:
          · write-locked fields (founder_only / transition_only / server_managed)
            keep their existing value and take the default on create. `@write`
            can never change them
          · every other field: use what was given (through `Field.coerce`), else
            keep the old value, else fall back to the default
          · unknown keys in the old row are preserved, appended after the
            declared order

        `expected` is the CAS expectation (required under
        `@write(precondition=cas(...))`); failing it raises `ConflictError`, not
        an invalidity error.

        `server` holds computed `server_managed` values (server clock, derived id,
        derived ref). Same discipline as `transition`'s `bump` and `append`'s
        `server_fields`: the base fills them, the method body supplies values but
        never the right to set them.

        After the write the current `OperationSpec.validators` run; any failure
        rolls back the whole file rather than leaving a half-written state.
        """
        operation = current_operation()
        if operation is None or operation.kind != "write" or operation.target is not cls:
            raise CitizenError("%s.upsert 必须经拥有它的 Manager.invoke() 调用" % cls.__name__)
        unknown = set(changes) - set(operation.patch_fields)
        if unknown:
            raise CitizenError("%s.upsert 收到 OperationSpec 之外的字段:%s"
                               % (cls.__name__, sorted(unknown)))
        store = _writable(cls)
        cls._check_key(key)

        with store.lock(key):
            original = store.snapshot(key)
            old = next((r for r in store.read() if r.get(cls.__key__) == key), None) or {}

            precondition = operation.precondition
            if precondition is not None:
                actual = old.get(precondition.field)
                if actual != expected:
                    raise ConflictError(
                        "%s 的 %s 是 %r,调用方以为是 %r —— 有人在你读到之后改过它"
                        % (cls.ref_of(key), precondition.field, actual, expected))

            ordered = cls._merge(old, changes, server)

            probe = cls._from_row(dict(ordered, **{cls.__key__: key}))
            errors = probe.check()
            if errors:
                raise InvariantError("; ".join(errors))

            created = store.write_entry(key, ordered, expected=expected)
            try:
                _run_validators(operation.validators)
            except Exception:
                store.restore(original, key)                  # whole-file rollback
                raise
            if after_write:
                after_write()

        return {"ok": True, "file": store.path, cls.__key__: key,
                "created": created, "entry": ordered}


    @classmethod
    def _merge(cls, old, changes, server=None):
        """Old row + this change + computed server values → an entry in declaration
        order.

        Shared by `upsert` and `create`: they differ only in whether an existing
        row is allowed. The merge rule itself is identical, and two copies drift.
        """
        server = dict(server or {})
        unknown = sorted(name for name in server
                         if not cls.__fields__.get(name)
                         or not cls.__fields__[name].server_managed)
        if unknown:
            raise CitizenError("server 只能填 server_managed 字段:%s" % unknown)
        entry = {k: v for k, v in old.items() if k != cls.__key__}
        for name, spec in cls.__fields__.items():
            if name in server:
                entry[name] = spec.coerce(server[name])
                continue
            if spec.write_locked:
                default = spec.get_default()
                entry[name] = old.get(name, None if default is MISSING else default)
                continue
            given = changes.get(name)
            if given is not None:
                entry[name] = spec.coerce(given)
            elif name in entry:
                pass
            else:
                default = spec.get_default()
                if default is not MISSING:
                    entry[name] = default
        return cls._ordered(entry)

    @classmethod
    def create(cls, key, changes, *, server=None, after_write=None):
        """Create-only (`@write(mode="create")`); an existing row is settled by the
        idempotency key.

        One difference from `upsert`, and it is the whole point of this kind: a
        collision never overwrites.

          · idempotency key (`OperationSpec.idempotent_on`) equal field by field
            → return the existing row with `deduped: True`. Replaying one
            `request_id` is a no-op, not a second piece of work.
          · different → `ConflictError`. Two different things under one key can
            only be a caller mistake.
        """
        operation = current_operation()
        if (operation is None or operation.kind != "write"
                or operation.mode != "create" or operation.target is not cls):
            raise CitizenError("%s.create 必须经声明了 mode=create 的 @write 调用"
                               % cls.__name__)
        unknown = set(changes) - set(operation.patch_fields)
        if unknown:
            raise CitizenError("%s.create 收到 OperationSpec 之外的字段:%s"
                               % (cls.__name__, sorted(unknown)))
        store = _writable(cls)
        cls._check_key(key)

        with store.lock(key):
            original = store.snapshot(key)
            old = next((r for r in store.read() if r.get(cls.__key__) == key), None)
            ordered = cls._merge({}, changes, server)
            if old is not None:
                same = all(old.get(name) == ordered.get(name)
                           for name in operation.idempotent_on)
                if not (operation.idempotent_on and same):
                    raise ConflictError("%s 已存在" % cls.ref_of(key))
                return {"ok": True, "file": store.path, cls.__key__: key,
                        "created": False, "deduped": True, "entry": dict(old)}

            probe = cls._from_row(dict(ordered, **{cls.__key__: key}))
            errors = probe.check()
            if errors:
                raise InvariantError("; ".join(errors))
            store.write_entry(key, ordered)
            try:
                _run_validators(operation.validators)
            except Exception:
                store.restore(original, key)
                raise
            if after_write:
                after_write()
        return {"ok": True, "file": store.path, cls.__key__: key,
                "created": True, "deduped": False, "entry": ordered}

    # ── The other two write kinds ────────────────────────────────────────
    @classmethod
    def _begin_write(cls, key, kinds, expected=None):
        """Opening shared by the three write kinds: contract check, key shape, CAS
        precondition.

        Returns `(operation, store, old_row)`. The caller holds the lock, in its
        own `with store.lock(key)`, because the rollback must be inside it too.
        """
        operation = current_operation()
        if operation is None or operation.kind not in kinds or operation.target is not cls:
            raise CitizenError("%s 的写必须经拥有它的 Manager.invoke() 调用" % cls.__name__)
        cls._check_key(key)
        store = _writable(cls)
        old = next((r for r in store.read() if r.get(cls.__key__) == key), None)
        if old is None:
            raise CitizenNotFound("%s://%s" % (cls.scheme(), key))
        precondition = operation.precondition
        if precondition is not None:
            actual = old.get(precondition.field)
            if actual != expected:
                raise ConflictError(
                    "%s://%s 的 %s 是 %r,调用方以为是 %r —— 有人在你读到之后改过它"
                    % (cls.scheme(), key, precondition.field, actual, expected))
        return operation, store, dict(old)

    @classmethod
    def _commit(cls, store, key, entry, original, operation, after_write, expected=None):
        """Closing shared by the three write kinds: invariants → persist → validate →
        roll back on failure.

        `expected` is passed down to the store so the implementation compares it
        in one statement. Comparing only in `_begin_write` is check-then-act, and
        two concurrent writes would both pass. File stores ignore it; they rely on
        `lock()` plus whole-file rollback.
        """
        probe = cls._from_row(dict(entry, **{cls.__key__: key}))
        errors = probe.check()
        if errors:
            raise InvariantError("; ".join(errors))
        created = store.write_entry(key, entry, expected=expected)
        try:
            _run_validators(operation.validators)
        except Exception:
            store.restore(original, key)
            raise
        if after_write:
            after_write()
        return created

    @classmethod
    def transition(cls, key, expected=None, *, sets=None, bump=None, after_write=None):
        """State transition: changes `state_field` plus the evidence fields declared in
        `operation.sets`, and nothing else.

        `sets` is this transition's evidence (accept's `artifact_index_ref`, for
        example) and lands in the same CAS replacement as the state. Splitting
        them leaves an illegal intermediate state. Which fields may appear here is
        pinned at class creation by `@transition(sets=...)`; the method body
        cannot supply others.

        `bump` is an optional `server_managed` increment (`{"revision": old+1}`).
        The base fills it rather than the method body, because who may set
        `server_managed` must have exactly one answer.
        """
        operation, store, old = cls._begin_write(key, ("transition",), expected)
        field_name = operation.state_field
        current = old.get(field_name)
        if operation.from_states and current not in operation.from_states:
            raise CitizenError(
                "%s://%s 的 %s 是 %r,只能从 %s 迁到 %r"
                % (cls.scheme(), key, field_name, current,
                   list(operation.from_states), operation.to_state))
        with store.lock(key):
            original = store.snapshot(key)
            entry = {k: v for k, v in old.items() if k != cls.__key__}
            entry[field_name] = operation.to_state
            unknown = set(sets or ()) - set(operation.sets)
            if unknown:
                raise CitizenError("%s.transition 收到 sets 之外的字段:%s"
                                   % (cls.__name__, sorted(unknown)))
            for name, value in (sets or {}).items():
                entry[name] = cls.__fields__[name].coerce(value)
            cls._apply_bump(entry, bump)
            ordered = cls._ordered(entry)
            cls._commit(store, key, ordered, original, operation, after_write,
                        expected=expected)
        return {"ok": True, "file": store.path, cls.__key__: key,
                "from": current, "to": operation.to_state, "entry": ordered}

    @classmethod
    def amend(cls, key, select, changes, expected=None, *, guard=None, bump=None,
              after_write=None):
        """Amend restricted keys in place on the `operation.into` elements picked by
        `select`.

        `select` is an array of indices; the method body may translate other
        selection forms into indices first.

        `changes` may only carry keys declared in `operation.amend_keys`. The base
        checks again here because the class-creation gate blocks declarations,
        while this one blocks a method body slipping in an extra key at runtime.

        `guard(row) -> None` comes from the method body and must raise when
        unsatisfied. Never skip silently: a person would believe they handled an
        item that is in fact still in the queue.

        If nothing actually changed, nothing is persisted and `changed: 0` comes
        back. An idempotent replay must not bump revision.
        """
        operation, store, old = cls._begin_write(key, ("amend",), expected)
        unknown = sorted(set(changes) - set(operation.amend_keys))
        if unknown:
            raise CitizenError("%s.amend 收到 sets 之外的键:%s" % (cls.__name__, unknown))
        rows = copy.deepcopy(list(old.get(operation.into) or []))
        if not isinstance(select, list) or not select:
            raise CitizenError("amend 的 select 必须是非空数组")
        touched = 0
        for index in select:
            if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(rows):
                raise CitizenError("%s 的 %s 下标越界:%r(共 %d 条)"
                                   % (cls.ref_of(key), operation.into, index, len(rows)))
            if guard is not None:
                guard(rows[index])
            if any(rows[index].get(k) != v for k, v in changes.items()):
                rows[index].update(changes)
                touched += 1
        if not touched:
            return {"ok": True, "file": store.path, cls.__key__: key,
                    "changed": 0, "entry": dict(old)}

        with store.lock(key):
            original = store.snapshot(key)
            entry = {k: v for k, v in old.items() if k != cls.__key__}
            entry[operation.into] = rows
            cls._apply_bump(entry, bump)
            ordered = cls._ordered(entry)
            cls._commit(store, key, ordered, original, operation, after_write,
                        expected=expected)
        return {"ok": True, "file": store.path, cls.__key__: key,
                "changed": touched, "entry": ordered}

    @classmethod
    def append(cls, key, entries, expected=None, *, server_fields=None, bump=None,
               after_write=None):
        """Append to an array field: add only, never modify, deduped by
        `operation.identity`.

        `server_fields` are the server values stamped onto each entry (clocks and
        so on); a caller key of the same name is overwritten, which is what
        `server_managed` means.

        `bump` means the same as in `transition`/`upsert`: a row-level
        `server_managed` increment (`{"revision": old+1, "updated_at": now}`).
        Don't confuse the two — `server_fields` stamps each appended entry,
        `bump` stamps this row. An append is still a replacement, and without
        bumping revision a CAS store rejects it outright
        (`replacement revision must increment by one`).
        """
        operation, store, old = cls._begin_write(key, ("append",), expected)
        if not isinstance(entries, list) or not entries:
            raise CitizenError("append 的条目必须是非空数组")
        existing = list(old.get(operation.into) or [])

        def identity_of(item):
            return tuple(item.get(name) for name in operation.identity)

        seen = {identity_of(item) for item in existing} if operation.identity else set()
        fresh = []
        for item in entries:
            if not isinstance(item, dict):
                raise CitizenError("append 的每条必须是 object")
            row = dict(item)
            row.update(server_fields or {})
            if operation.identity:
                mark = identity_of(row)
                if mark in seen:
                    continue                       # idempotent: re-appending the same entry is a no-op
                seen.add(mark)
            fresh.append(row)

        if not fresh:
            # Nothing new means genuinely nothing happens: no write, no revision
            # bump. Replays are normal, and persisting anyway would bump revision
            # on every replay (breaking every concurrent CAS) and fill the audit
            # log with writes that changed nothing. Idempotent means there is no
            # second effect, not that the effect is the same.
            return {"ok": True, "file": store.path, cls.__key__: key,
                    "appended": 0, "skipped": len(entries),
                    "entry": cls._ordered({k: v for k, v in old.items()
                                           if k != cls.__key__})}
        with store.lock(key):
            original = store.snapshot(key)
            entry = {k: v for k, v in old.items() if k != cls.__key__}
            entry[operation.into] = existing + fresh
            cls._apply_bump(entry, bump)
            ordered = cls._ordered(entry)
            cls._commit(store, key, ordered, original, operation, after_write,
                        expected=expected)
        return {"ok": True, "file": store.path, cls.__key__: key,
                "appended": len(fresh), "skipped": len(entries) - len(fresh),
                "entry": ordered}

    @classmethod
    def _apply_bump(cls, entry, bump):
        """Stamp the row-level server_managed increment. Shared by all three write
        kinds: without it the written row keeps its revision and any CAS store
        rejects it."""
        for name, value in (bump or {}).items():
            if not cls.__fields__[name].server_managed:
                raise CitizenError("bump 只能填 server_managed 字段:%s" % name)
            entry[name] = value

    @classmethod
    def _ordered(cls, entry):
        """Order by declaration, unknown keys appended after — the same rule as
        `upsert`, which is what keeps the persisted bytes stable."""
        ordered = {n: entry[n] for n in cls.__fields__ if n in entry}
        ordered.update({k: v for k, v in entry.items() if k not in ordered})
        return ordered


# ── Post-write validation ───────────────────────────────────────────────────

def run_script(rel_path, *args, timeout=60, check=False):
    """Run an in-repo script, for fire-and-forget actions such as refreshing a
    derived view after a write.

    With `check=False` a failure only means "not refreshed" and does not break the
    write path: a derived view is disposable, and its failure must not roll back a
    legal declaration change.
    """
    import os
    import subprocess
    import sys
    from .store import REPO
    script = rel_path if os.path.isabs(rel_path) else os.path.join(REPO, rel_path)
    if not os.path.isfile(script):
        return None
    result = subprocess.run([sys.executable, script, *args],
                            capture_output=True, text=True, timeout=timeout)
    if check and result.returncode != 0:
        raise CitizenError("%s 失败:%s" % (os.path.basename(script),
                                          (result.stdout + result.stderr)[-300:]))
    return result


def _run_validators(validators):
    import os
    import subprocess
    import sys
    from .store import REPO
    for validator in validators:
        if not isinstance(validator, ValidatorSpec):
            raise CitizenError("写后校验不是 ValidatorSpec:%r" % (validator,))
        argv = validator.argv
        script = argv[0] if os.path.isabs(argv[0]) else os.path.join(REPO, argv[0])
        if not os.path.isfile(script):
            raise CitizenError("写后校验不存在,已回滚:%s" % argv[0])
        try:
            result = subprocess.run([sys.executable, script, *argv[1:]],
                                    capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CitizenError("%s 没跑起来,已回滚:%s"
                               % (os.path.basename(script), type(error).__name__))
        if result.returncode != 0:
            tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-4:])[:400]
            raise CitizenError("改动过不了 %s,已回滚 —— %s"
                               % (os.path.basename(script), tail))
