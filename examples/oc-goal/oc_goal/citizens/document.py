"""`Document`: base class for a singleton document in the declaration layer.

`Citizen` is "many of a kind": primary key, list, `keys()` closed set,
addressable as `<scheme>://<key>`. `Document` is "the system has exactly one of
these" — asking "which focus?" is meaningless.

    Citizen    many instances · has a key · YamlList/YamlDir/BodyFile/InjectedStore
    Document   one instance   · no key    · YamlDoc

Not modelled as a one-entry `Citizen`, which would force a fake primary key and
make refs like `focus://<something>` imaginable, inventing a concept that does
not exist. Not a `singleton=True` branch on `Citizen` either, which would scatter
`if cls.__key__ is None` through the base class and make every multi-instance
citizen carry the singleton's check.

The field machinery (declaration order, modifiers, invariants, violations) is the
same implementation `Citizen` uses; only the primary-key part differs.

There is exactly one write form, `@document`: patch fields of this document. No
upsert (a document is either there or the domain is broken), no transition (no
key means no per-row state machine), no append.

`YamlDoc.patch` eats comments — see `store.YamlDoc.patch`.
"""
from .citizen import (CitizenError, InvariantError, _assign, _collect_fields,
                      _collect_invariants, _field_errors, _ordered_dict, _resolve_row,
                      _run_validators)
from .operation import current_operation

# A registry separate from `Citizen`'s: the structural gate requiring a store
# and a key does not hold for singletons. One shared registry would put
# `if hasattr(cls, "__key__")` inside the gate, moving the difference between the
# two shapes out of the type system and into an if. The ownership gate still runs
# over both registries.
_REGISTRY = {}


def registry():
    """Every declared singleton document. Used by the structural gates in `domain/ops/`."""
    return dict(_REGISTRY)


class Document:
    __store__ = None
    __fields__ = {}
    __invariants__ = ()

    def __init_subclass__(cls, *, store=None, **kw):
        super().__init_subclass__(**kw)
        cls.__store__ = store
        cls.__fields__ = _collect_fields(cls)
        cls.__invariants__ = _collect_invariants(cls)
        _REGISTRY[cls.__name__] = cls

    # ── Construction ─────────────────────────────────────────────────────
    def __init__(self, **values):
        _assign(self, self.__class__, values)

    @classmethod
    def _from_row(cls, row):
        resolved, missing = _resolve_row(cls, row)
        obj = cls(**resolved)
        obj._row = dict(row)
        obj._missing = missing
        return obj

    # ── Read ─────────────────────────────────────────────────────────────
    @classmethod
    def read(cls):
        """The raw mapping, not dereferenced — the shape existing callers expect."""
        if cls.__store__ is None:
            raise CitizenError("%s 没有 store,读不了" % cls.__name__)
        return cls.__store__.read()

    @classmethod
    def current(cls):
        """The current document, dereferenced."""
        return cls._from_row(cls.read())

    @classmethod
    def scheme(cls):
        """A singleton has no `<scheme>://<key>` but still belongs to a domain. Defaults
        to the lowercased class name; subclasses override when the domain name
        differs from the class name (`Focus` belongs to `goal`)."""
        return cls.__name__.lower()

    # ── Persistence shape ────────────────────────────────────────────────
    def to_dict(self):
        return _ordered_dict(self, self.__class__, {})

    # ── Invariants ───────────────────────────────────────────────────────
    def check(self):
        return _field_errors(self, self.__class__, self.__class__.__name__)

    @classmethod
    def check_all(cls):
        errors = list(cls.__store__.document_errors())
        errors.extend(cls.current().check())
        for name, member, scope in cls.__invariants__:
            if scope != "all":
                continue
            try:
                member(cls.current())
            except AssertionError as error:
                errors.append("%s: %s" % (cls.__name__, error or name))
        return errors

    # ── Write ────────────────────────────────────────────────────────────
    @classmethod
    def patch(cls, changes, *, after_write=None):
        """Patch fields into this document. The common steps live here; method bodies
        carry only domain rules.

        The merge rule deliberately differs from `Citizen.upsert`:

          · `upsert` treats "not given" as "keep the old value" because it also
            creates, and a create needs a fallback
          · `patch` only edits an existing document, so "not given" means "do not
            touch" — `None` is filtered out, and clearing a field requires an
            explicit empty value (`[]` / `""`)

        Write-locked fields may never appear in `changes`: the same gate as
        `@write`, caught earlier in `_validate_operations` because the signature
        never has that parameter.
        """
        operation = current_operation()
        if operation is None or operation.kind != "document" or operation.target is not cls:
            raise CitizenError("%s.patch 必须经拥有它的 Manager.invoke() 调用" % cls.__name__)
        unknown = set(changes) - set(operation.patch_fields)
        if unknown:
            raise CitizenError("%s.patch 收到 OperationSpec 之外的字段:%s"
                               % (cls.__name__, sorted(unknown)))
        store = cls.__store__
        required = ("lock", "snapshot", "restore", "read", "patch")
        if any(not hasattr(store, name) for name in required):
            raise CitizenError("%s 的 store 不支持 patch" % cls.__name__)

        coerced = {name: cls.__fields__[name].coerce(value)
                   for name, value in changes.items() if value is not None}

        with store.lock():
            original = store.snapshot()
            probe = cls._from_row({**dict(store.read()), **coerced})
            errors = probe.check()
            if errors:
                raise InvariantError("; ".join(errors))

            ordered = store.patch(coerced, order=tuple(cls.__fields__))
            try:
                _run_validators(operation.validators)
            except Exception:
                store.restore(original)                       # whole-file rollback
                raise
            if after_write:
                after_write()

        return {"ok": True, "file": store.path, "document": ordered,
                "changed": sorted(coerced)}


__all__ = ["Document", "registry"]
