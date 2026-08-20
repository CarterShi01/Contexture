"""Field modifiers for first-class citizens.

A field's whole semantics live on its own declaration, never scattered elsewhere:

    budget: int = founder_only(0)        # tools cannot change it: the reflector
                                         # generates no parameter for it
    title:  str = truncate(30)           # truncation explicitly allowed, with maxLength
    why:    str = maxlen(500)            # over-length is an error, never a silent rewrite

`founder_only` is not "passing it gets rejected" — the parameter does not exist
in the schema at all.

stdlib only. Never import pydantic or brain-mcp: the declaration layer's gates
run under a bare `python3`, and each added dependency is one more machine where
they break.
"""

import types
import typing


MISSING = object()


def _unwrap_optional(annotation):
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        args = [item for item in typing.get_args(annotation) if item is not type(None)]
        if len(args) == 1 and len(args) != len(typing.get_args(annotation)):
            return args[0], True
    return annotation, False


def _type_label(annotation):
    annotation, _ = _unwrap_optional(annotation)
    origin = typing.get_origin(annotation)
    if origin in (list, tuple):
        return "array"
    if origin is dict:
        return "object"
    return {str: "string", int: "integer", float: "number", bool: "boolean",
            list: "array", dict: "object"}.get(annotation,
                                                getattr(annotation, "__name__", str(annotation)))


def _matches_type(value, annotation):
    annotation, _ = _unwrap_optional(annotation)
    origin = typing.get_origin(annotation)
    if origin in (list, tuple) or annotation is list:
        return isinstance(value, list)
    if origin is dict or annotation is dict:
        return isinstance(value, dict)
    if annotation is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if annotation is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if annotation is bool:
        return isinstance(value, bool)
    if annotation is str:
        return isinstance(value, str)
    return True


class Field:
    """The full declaration of a citizen field.

    Field methods judge shape only. Cross-field and cross-table judgements belong
    to `@invariant`; mixing them would force the schema generator to execute
    business logic.
    """

    __slots__ = ("name", "annotation", "default", "factory", "founder_only",
                 "transition_only", "server_managed",
                 "maxlen", "minlen", "nonempty", "pattern", "choices",
                 "minimum", "maximum", "maxitems", "uniqueitems", "item",
                 "shape", "shape_required", "source", "doc", "ref_to",
                 "truncate_at", "ref_where")

    def __init__(self, default=MISSING, *, factory=None, founder_only=False,
                 transition_only=False, server_managed=False,
                 maxlen=None, minlen=None, nonempty=False, pattern=None,
                 choices=None, minimum=None, maximum=None, maxitems=None,
                 uniqueitems=False, item=None, shape=None, required=None,
                 annotation=None, source=None, doc="", truncate_at=None,
                 ref_where=None):
        self.name = None            # filled in by Citizen.__init_subclass__
        # Top-level annotations are filled in by `_collect_fields` from
        # `__annotations__`. Sub-fields inside `shape` have no class annotation
        # (they are not class attributes), so they must be given explicitly:
        # without one they default to `str`, and a `list` sub-key would render as
        # `type: string` in the schema.
        self.annotation = annotation
        self.ref_to = None          # likewise: points at the Citizen subclass when annotated as one
        self.ref_where = dict(ref_where or {})
        self.default = default
        self.factory = factory
        self.founder_only = bool(founder_only)
        self.transition_only = bool(transition_only)
        self.server_managed = bool(server_managed)
        self.maxlen = maxlen
        self.truncate_at = truncate_at
        self.minlen = minlen
        self.nonempty = bool(nonempty)
        self.pattern = pattern
        self.choices = tuple(choices) if choices else None
        self.minimum = minimum
        self.maximum = maximum
        self.maxitems = maxitems
        self.uniqueitems = bool(uniqueitems)
        self.item = item            # the Field of an array element
        # Key contract for object values: `{key: Field}`. Isomorphic to `item`,
        # which governs array elements while this governs an object's keys; the
        # two compose (`item=item(shape={...})` is an array of objects).
        #
        # Needed because nested objects carry their own enums and patterns per
        # key. Without `shape` they could only be declared `dict`, and those
        # constraints would either move into `@invariant` — invisible to the
        # schema generator, degrading to `type: object` on the MCP tool surface —
        # or stay in a hand-written .schema.json, a second source of truth.
        self.shape = dict(shape) if shape else None
        # Required keys, given explicitly rather than inferred from sub-Field
        # annotations: nested Fields mostly carry none, and inferring would read
        # "no annotation written" as "optional".
        self.shape_required = tuple(required or ())
        # The key *in storage*, defaulting to the attribute name. They separate
        # because some storage keys cannot be field names: `from`/`to` are Python
        # keywords, `cc-plugin` has a hyphen. Same idea as `Citizen.key_param`.
        self.source = source
        if self.item is not None and self.item.name is None:
            self.item.name = "[]"
        if self.shape is not None:
            for key, spec in self.shape.items():
                if spec.name is None:
                    spec.name = key
                if spec.item is not None and spec.item.name in (None, "[]"):
                    spec.item.name = key + "[]"
            unknown = sorted(set(self.shape_required) - set(self.shape))
            if unknown:
                raise ValueError("required 里有未声明的键:%s" % unknown)
        self.doc = doc

    # ── Shape validation, one-to-one with the JSON Schema constraints ───────
    def violations(self, value):
        """This field's shape errors. Called by `Citizen.check()`: after writes, never on reads."""
        import re
        out = []
        if value is None:
            _base, optional = _unwrap_optional(self.annotation)
            return out if optional else ["%s 是必填字段" % self.name]
        if self.ref_to is not None:
            if not isinstance(value, self.ref_to):
                return ["%s 必须引用 %s,得到 %r"
                        % (self.name, self.ref_to.__name__, value)]
            for name, expected in self.ref_where.items():
                if getattr(value, name, None) != expected:
                    out.append("%s 引用的 %s.%s 必须是 %r"
                               % (self.name, self.ref_to.__name__, name, expected))
        elif self.annotation is not None and not _matches_type(value, self.annotation):
            return ["%s 必须是 %s,得到 %s"
                    % (self.name, _type_label(self.annotation), type(value).__name__)]
        if self.choices and value not in self.choices:
            out.append("%s 必须是 %s 之一,得到 %r" % (self.name, list(self.choices), value))
        if isinstance(value, str):
            if self.nonempty and not value:
                out.append("%s 不许为空字符串" % self.name)
            if self.minlen is not None and len(value) < self.minlen:
                out.append("%s 至少 %d 字,得到 %d" % (self.name, self.minlen, len(value)))
            if self.maxlen is not None and len(value) > self.maxlen:
                out.append("%s 至多 %d 字,得到 %d" % (self.name, self.maxlen, len(value)))
            if self.pattern and not re.match(self.pattern, value):
                out.append("%s 形状不合 %s:%r" % (self.name, self.pattern, value))
        if isinstance(value, bool):
            pass
        elif isinstance(value, int):
            if self.minimum is not None and value < self.minimum:
                out.append("%s 不得小于 %s,得到 %s" % (self.name, self.minimum, value))
            if self.maximum is not None and value > self.maximum:
                out.append("%s 不得大于 %s,得到 %s" % (self.name, self.maximum, value))
        if isinstance(value, list):
            if self.nonempty and not value:
                out.append("%s 不许为空数组" % self.name)
            if self.maxitems is not None and len(value) > self.maxitems:
                out.append("%s 至多 %d 项,得到 %d" % (self.name, self.maxitems, len(value)))
            if self.uniqueitems:
                seen, duplicated = [], []
                for element in value:
                    (duplicated if element in seen else seen).append(element)
                if duplicated:
                    out.append("%s 不许重复:%r" % (self.name, duplicated))
            if self.item is not None:
                for element in value:
                    # No prefix here: `item.name` is already `<field>[]`, and
                    # wrapping again prints `tags[]: tags[] …`.
                    out.extend(self.item.violations(element))
        if isinstance(value, dict) and self.shape is not None:
            unknown = sorted(set(value) - set(self.shape))
            if unknown:
                out.append("%s 有未声明的键:%s" % (self.name, unknown))
            for key in self.shape_required:
                if key not in value:
                    out.append("%s 缺必填键:%s" % (self.name, key))
            for key, spec in self.shape.items():
                if key in value:
                    out.extend("%s.%s" % (self.name, e)
                               for e in spec.violations(value[key]))
        return out

    # ── Write rights ────────────────────────────────────────────────────────
    @property
    def write_locked(self):
        """The three kinds of field `@write` generates no parameter for, as one criterion.

        All three reflect the same way (the parameter does not exist) but differ
        on the write path: `founder_only` / `transition_only` keep the existing
        value, `server_managed` is filled by the system. One criterion — never
        check the three flags separately elsewhere.
        """
        return self.founder_only or self.transition_only or self.server_managed

    # ── Defaults ────────────────────────────────────────────────────────────
    @property
    def has_default(self):
        return self.default is not MISSING or self.factory is not None

    def get_default(self):
        """Get the default. Mutable defaults (list/dict) are deep-copied each time."""
        if self.factory is not None:
            return self.factory()
        if self.default is MISSING:
            return MISSING
        if isinstance(self.default, (list, dict, set)):
            import copy
            return copy.deepcopy(self.default)
        return self.default

    # ── Shape coercion before persisting ────────────────────────────────────
    def coerce(self, value):
        """Coerce an externally supplied value into its persisted shape. Shape only,
        never judgement."""
        if value is None:
            return None
        if self.ref_to is not None:
            # Reference fields persist as a key string; the value may already be an object
            return getattr(value, value.__class__.__key__, value) \
                if hasattr(value, "__key__") else value
        if self.truncate_at and isinstance(value, str):
            value = value[:self.truncate_at]
        if isinstance(value, (list, tuple)):
            return list(value)
        return value

    def __repr__(self):                                          # pragma: no cover
        bits = [self.name or "?"]
        for flag in ("founder_only", "transition_only", "server_managed"):
            if getattr(self, flag):
                bits.append(flag)
        if self.maxlen:
            bits.append("maxlen=%s" % self.maxlen)
        return "<Field %s>" % " ".join(bits)


# ── Constructors — these are what appear in declarations ────────────────────

def field(default=MISSING, **kw):
    """An ordinary field. Not needed when a literal serves as the default —
    `standard: str = "TODO"` is enough."""
    return Field(default, **kw)


def founder_only(default=MISSING, **kw):
    """A field no tool can change; only the founder edits the declaration file.

    Criterion: it is a controller, not data.
      · the denominator of a metric (`area.budget`) — Goodhart: the party being
        measured must not change its own denominator
      · lifecycle judgements (`goal.status`, `area.status`) — done or abandoned
        is a human call
      · one-way doors (`project.exposure`) — what left cannot be recalled

    Reflection: `@write` generates no parameter for it; writes keep the existing
    value, creates take the default.
    """
    kw["founder_only"] = True
    return Field(default, **kw)


def transition_only(default=MISSING, **kw):
    """A field changeable only through `@transition` — typically a state machine's
    `status`.

        founder_only     no tool can set it; only the founder edits the file
        transition_only  a tool *can* set it, but only via a state transition

    One modifier cannot express both. Reflection matches `founder_only` (`@write`
    generates no parameter), but `@transition` may write it, and `@write`'s merge
    still keeps the existing value.
    """
    kw["transition_only"] = True
    return Field(default, **kw)


def server_managed(default=MISSING, **kw):
    """A field the system fills and nobody supplies: server clocks, CAS counters,
    markers with a fixed initial value.

    Examples: `ledger[].at` — letting a caller supply it would let it rewrite the
    order of history; `acked`, always starting False, since a judgement cannot
    declare itself already read; `revision`, a CAS counter.

    Different from `founder_only`: that means "a *person* edits it by hand", this
    means "the *system* fills it and no person should". Reflection likewise
    generates no parameter, but the write path fills it rather than keeping the
    old value.
    """
    kw["server_managed"] = True
    return Field(default, **kw)


def maxlen(n, default=MISSING, **kw):
    """String upper bound. Over-length is rejected by validation, never rewritten."""
    kw["maxlen"] = n
    return Field(default, **kw)


def truncate(n, default=MISSING, **kw):
    """A string field where truncation is explicitly allowed, so constraint and
    conversion stay distinguishable in the declaration."""
    kw["maxlen"] = n
    kw["truncate_at"] = n
    return Field(default, **kw)


def item(**kw):
    """The shape of an array element:
    `objects: list[str] = nonempty(item=item(pattern=...))`."""
    return Field(**kw)


def nonempty(default=MISSING, **kw):
    """May not be empty (empty string or array). The schema carries
    `minLength`/`minItems`."""
    kw["nonempty"] = True
    return Field(default, **kw)


# ── Derived properties and invariants ───────────────────────────────────────

def derived(fn):
    """A derived property: not stored, not on the write surface, computed from other
    facts.

    Typically a back-reference (`Area.goals`): stored it drifts, computed it
    cannot.
    """
    fn.__derived__ = True
    return property(fn)


def invariant(fn=None, *, scope="instance"):
    """An invariant. `scope="instance"` checks one row; `scope="all"` checks the
    whole table (the signature takes the full list).

    Reads never run invariants: `all()`/`get()` only load and dereference, and
    `check()` runs after writes and in `<x>-ops/`. One hand-broken field is a red
    validator today; if reads ran invariants the entire read surface would fail,
    which is worse than the problem.
    """
    def wrap(f):
        f.__invariant__ = scope
        return staticmethod(f) if scope == "all" else f
    return wrap(fn) if fn is not None else wrap
