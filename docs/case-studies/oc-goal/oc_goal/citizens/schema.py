"""Type annotations → JSON Schema.

Hand-written rather than pydantic: the declaration layer's dependency surface is
a hard constraint (stdlib + PyYAML), and its gates run under a bare `python3`.
The cost is these ~120 lines; the return is every offline gate running on any
machine.

Reflection rules — a closed set, do not add an eighth:

    str / int / bool        → {"type": ...}
    list[str]               → {"type":"array","items":{"type":"string"}}
    X | None = None         → same as X, not in required
    <Citizen subclass>      → {"type":"string","enum": Cls.keys(**Field.ref_where)}
    maxlen(n)               → + {"maxLength": n}
    nonempty()              → + {"minLength": 1} / {"minItems": 1}
    founder_only / transition_only / server_managed → nothing (Field.write_locked)
    docstring               → description

The citizen-subclass rule is where the value is: `area: Area` puts the closed set
of active areas into the schema, so a model cannot even syntactically name one
that does not exist. The alternative path is write → validate → roll back →
error → retry.
"""
import inspect
import types
import typing

from .citizen import Citizen
from .field import MISSING


def _unwrap_optional(annotation):
    """`X | None` / `Optional[X]` → `(X, True)`; anything else → `(annotation, False)`."""
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0], True
        return args[0] if args else str, True
    return annotation, False


def of_annotation(annotation):
    """One type annotation → one piece of JSON Schema."""
    annotation, _ = _unwrap_optional(annotation)

    if isinstance(annotation, type) and issubclass(annotation, Citizen):
        try:
            choices = annotation.keys()
        except Exception:                                    # noqa: BLE001
            choices = []
        out = {"type": "string"}
        if choices:
            out["enum"] = sorted(choices)
        return out

    origin = typing.get_origin(annotation)
    if origin in (list, tuple):
        args = typing.get_args(annotation)
        return {"type": "array", "items": of_annotation(args[0]) if args else {"type": "string"}}
    if origin is dict:
        return {"type": "object"}

    return {str: {"type": "string"}, int: {"type": "integer"},
            float: {"type": "number"}, bool: {"type": "boolean"},
            dict: {"type": "object"}, list: {"type": "array"}}.get(
                annotation, {"type": "string"})


def of_field(spec):
    """One `Field` → one piece of JSON Schema: the same constraints
    `Field.violations()` enforces, projected differently."""
    out = (of_field(spec.ref_to.__key_field__)
           if spec.ref_to is not None
           # No annotation but element shape / array constraints declared → it is
           # an array. Sub-fields inside `shape` may omit annotations; this covers them.
           else of_annotation(spec.annotation
                              or (list if (spec.item is not None
                                           or spec.maxitems is not None
                                           or spec.uniqueitems) else str)))
    if spec.ref_to is not None:
        try:
            choices = spec.ref_to.keys(**spec.ref_where)
        except Exception:                                    # noqa: BLE001
            choices = []
        if choices:
            out["enum"] = sorted(choices)
    is_array = out.get("type") == "array"
    if spec.maxlen is not None:
        out["maxLength"] = spec.maxlen
    if spec.minlen is not None:
        out["minLength"] = spec.minlen
    if spec.nonempty:
        out.setdefault("minItems" if is_array else "minLength", 1)
    if spec.pattern:
        out["pattern"] = spec.pattern
    if spec.choices:
        out["enum"] = list(spec.choices)
    if spec.minimum is not None:
        out["minimum"] = spec.minimum
    if spec.maximum is not None:
        out["maximum"] = spec.maximum
    if spec.maxitems is not None:
        out["maxItems"] = spec.maxitems
    if spec.uniqueitems:
        out["uniqueItems"] = True
    if spec.item is not None and is_array:
        out["items"] = of_field(spec.item)
    if spec.shape is not None:
        # Key contract for objects. `additionalProperties: false` is the default,
        # not an option: a declaration-layer object either states all its keys or
        # it is not a declared shape.
        out["type"] = "object"
        out["additionalProperties"] = False
        out["properties"] = {key: of_field(sub) for key, sub in spec.shape.items()}
        if spec.shape_required:
            out["required"] = list(spec.shape_required)
    if spec.doc:
        out["description"] = spec.doc
    return out


def of_fields(citizen_cls, *, include_write_locked=False):
    """A `Citizen`'s field surface. Excludes write-locked fields by default, which is
    their entire point."""
    return {name: of_field(spec)
            for name, spec in citizen_cls.__fields__.items()
            if include_write_locked or not spec.write_locked}


def _hints(fn):
    try:
        return typing.get_type_hints(fn)
    except Exception:                                        # noqa: BLE001
        return {}


def of(fn):
    """One manager method → the JSON Schema of its domain parameters.

    Write methods read their `OperationSpec.target/patch_fields` first, so the
    method signature and the entity's field constraints actually converge.
    approval belongs to the runtime protocol and is appended by brain-mcp's
    adapter layer.
    """
    hints = _hints(fn)
    signature = inspect.signature(fn)
    properties, required = {}, []

    _operation = getattr(fn, "__operation__", None)
    _injected = set(getattr(_operation, "injected", ()) or ())
    for name, parameter in signature.parameters.items():
        if name in ("self", "cls", "ctx"):
            continue
        if name in _injected:
            # Host-injected parameters stay off the tool surface. Caller identity
            # is the archetype: a caller-chosen `created_by_ref` means creating
            # work on someone else's behalf.
            continue
        annotation = hints.get(name, parameter.annotation)
        if annotation is inspect.Parameter.empty:
            annotation = str
        operation = getattr(fn, "__operation__", None)
        target = operation.target if operation and operation.kind == "write" else None
        if target is not None and name == target.__key_param__:
            properties[name] = of_field(target.__key_field__)
        elif target is not None and name in operation.patch_fields:
            properties[name] = of_field(target.__fields__[name])
        else:
            properties[name] = of_annotation(annotation)
        _, optional = _unwrap_optional(annotation)
        if parameter.default is inspect.Parameter.empty and not optional:
            required.append(name)

    out = {"type": "object", "properties": properties}
    if required:
        out["required"] = required
    return out


def of_citizen_document(citizen_cls):
    """A Citizen's persisted-document schema, used to prove it covers the strict
    hand-written JSON Schema."""
    properties = {citizen_cls.__key__: of_field(citizen_cls.__key_field__)}
    properties.update(of_fields(citizen_cls, include_write_locked=True))
    from .citizen import _is_optional                            # noqa: PLC0415
    item_schema = {
        "type": "object",
        "additionalProperties": False,
        # Only genuinely required fields go into required, on the same criterion
        # `Field.violations` uses: an annotation with `| None` is optional.
        "required": [citizen_cls.__key__,
                     *(n for n, spec in citizen_cls.__fields__.items()
                       if not _is_optional(spec))],
        "properties": properties,
    }
    # Container shape follows the store: `YamlList` is one list per file, while
    # for `YamlDir` the document *is* the item, with no outer wrapper.
    list_key = getattr(citizen_cls.__store__, "list_key", None)
    if list_key is None:
        return item_schema
    version_key = getattr(citizen_cls.__store__, "version_key", "version")
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [version_key, list_key],
        "properties": {
            version_key: {"type": "integer", "const": 1},
            list_key: {"type": "array", "minItems": 1, "items": item_schema},
        },
    }


def description(fn):
    """The MCP tool description: the method's full docstring, cleandoc'd."""
    return inspect.cleandoc(fn.__doc__ or "")


def summary(fn):
    """The L1 stage-sheet line: the docstring's first line."""
    text = description(fn)
    return text.splitlines()[0] if text else ""


def body_is_ellipsis(fn):
    """Whether the method body is `...`. The structural gate in `domain/ops/` forbids it."""
    try:
        source = inspect.getsource(fn)
    except (OSError, TypeError):
        return False
    lines = [ln.strip() for ln in source.splitlines()]
    body = [ln for ln in lines
            if ln and not ln.startswith(("#", "@", "def ", "async def "))
            and not ln.startswith(('"""', "'''"))]
    return body == ["..."]


def write_locked_leaks(manager_cls):
    """A write-locked field appearing among `@write`'s parameters is a structural
    error: a controller treated as data.

    Returns `[(method, citizen, field)]`; empty means pass.
    """
    leaks = []
    for name, fn in manager_cls.methods(kind="write"):
        params = set(of(fn).get("properties", {}))
        for citizen in manager_cls.__owns__:
            for field_name, spec in getattr(citizen, "__fields__", {}).items():
                if spec.write_locked and field_name in params:
                    leaks.append((name, citizen.__name__, field_name))
    return leaks


__all__ = ["of", "of_annotation", "of_citizen_document", "of_field", "of_fields",
           "description", "summary", "body_is_ellipsis", "write_locked_leaks", "MISSING"]
