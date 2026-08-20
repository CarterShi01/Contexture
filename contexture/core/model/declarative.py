"""Class-syntax declaration for context nodes.

A business application should state its context once, in its own vocabulary:

    class KubernetesOperator(Role):
        '''Operate and diagnose Kubernetes workloads.'''

        instructions = "Inspect before changing the cluster."

        diagnose = DiagnoseDeploymentFailure
        get_deployment = GetDeployment
        runbook = RolloutRunbook

This module turns that class body into a `Declaration`: an ordered, validated
record of what the class stated, resolved across its whole inheritance chain.

Two things this deliberately does not change:

* **Composition still models the team.** Subclassing declares what one node
  *is*; it never expresses containment. A role that coordinates other roles
  still holds them in `children`, exactly as an imperatively built one does.
* **Imperative construction stays first class.** `Role(name=..., ...)` remains
  the whole API for context assembled at runtime. Declaration is a second door
  onto the same object, not a replacement for the first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MemberDescriptorType
from typing import Any, Iterator, Mapping, TypeVar

from ..errors import DeclarationError

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

#: Attribute names a declarative body uses for scalars rather than members.
RESERVED_ATTRIBUTES = frozenset(
    {
        "name",
        "description",
        "instructions",
        "kind",
        "uri",
        "mime_type",
        "read_only",
        "uses",
    }
)

_T = TypeVar("_T")


@dataclass(slots=True, frozen=True, kw_only=True)
class DeclaredMember:
    """One member a declarative class body contributed, with its origin."""

    attribute: str
    value: Any
    declared_by: str

    #: The class this member was declared as, when it was declared as one.
    #: `None` when the class body named an object instead, because an object
    #: with constructor arguments cannot be rebuilt from nothing and the author
    #: who wrote it out meant *that* object.
    factory: type | None = None

    def build(self) -> Any:
        """Return this member for one owning instance.

        A declared class is built again here, per owner, so two instances of a
        role hold two independent members rather than the same object twice.
        That matters as soon as anything is *stamped* onto a node — an address,
        a handle on something outside the process — because a shared member
        would take the last stamp written anywhere in the process.

        Copies are cheap. A 300-role forest with distinct strings is 184 KB
        resident, and correctness at registration is worth more than the bytes.
        """

        return self.value if self.factory is None else self.factory()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<DeclaredMember {self.declared_by}.{self.attribute}>"


@dataclass(slots=True, frozen=True, kw_only=True)
class Declaration:
    """What one declarative class stated, resolved across its whole MRO.

    Members keep the order they were first declared in, base classes first, so
    a rendered surface is stable across runs and across refactors that only
    reorder unrelated attributes.
    """

    owner: str
    name: str
    description: str
    instructions: str | None
    members: tuple[DeclaredMember, ...]


    def stated(self) -> dict[str, Any]:
        """Keyword arguments for base fields this class body actually stated.

        A field left unstated must not be passed at all: the dataclass default
        is the single definition of what unstated means, and passing a second
        copy of it here would be a place for the two to disagree.
        """

        return {}

    def of_type(self, *types: type[_T]) -> tuple[_T, ...]:
        """Return declared member values matching any of `types`, in order."""

        return tuple(
            member.value
            for member in self.members
            if isinstance(member.value, types)
        )

    def attribute_of(self, value: Any) -> str | None:
        """Return the attribute name a member value was declared under."""

        for member in self.members:
            if member.value is value:
                return member.attribute
        return None


def derive_name(cls: type) -> str:
    """Turn a class name into a stable kebab-case node name.

    `KubernetesOperator` becomes `kubernetes-operator`, and an acronym run stays
    together, so `MCPGatewayRole` becomes `mcp-gateway-role`.
    """

    return _CAMEL_BOUNDARY.sub("-", cls.__name__).lower()


def derive_description(cls: type) -> str:
    """Use the first paragraph of the class docstring as the routing card text.

    Only the class's own docstring counts. Python hands an undocumented class
    its parent's `__doc__`, and silently routing on an inherited sentence is
    worse than refusing to guess.
    """

    own_doc = cls.__dict__.get("__doc__")
    if not isinstance(own_doc, str) or not own_doc.strip():
        return ""
    paragraph = own_doc.strip().split("\n\n", 1)[0]
    return " ".join(paragraph.split())


def is_declarative(cls: type, base: type) -> bool:
    """Report whether `cls` is a business declaration rather than `base` itself."""

    return cls is not base and issubclass(cls, base)


def collect(
    cls: type,
    *,
    member_types: tuple[type, ...],
    ignore: frozenset[str] = RESERVED_ATTRIBUTES,
) -> Declaration:
    """Build the `Declaration` for a declarative class.

    Resolution walks the MRO from the most basic class to the most derived, so
    a subclass overriding an inherited member replaces its value while keeping
    the position the base established.
    """

    name = scalar(cls, "name") or derive_name(cls)
    description = scalar(cls, "description") or derive_description(cls)
    instructions = scalar(cls, "instructions")

    if not description:
        raise DeclarationError(
            f"{cls.__name__} must state a description, either as a class "
            "docstring or a `description` attribute. Without one it cannot "
            "appear on a routing card."
        )

    # Anything this filter does not recognise is passed over in silence, and
    # that silence is load-bearing rather than lazy. A `Tool` subclass is
    # collected with `member_types=()`, so *every* class attribute it carries
    # falls through here — which is what lets a business layer hang its own
    # contract on a tool: one-creator's Goal domain declares `target`,
    # `patch_fields`, `writes` and `precondition` beside the `invoke` whose
    # signature they constrain. Rejecting the unrecognised would take that
    # pattern with it.
    #
    # The cost is that a `Prompt` or a `Resource` bound into a Role body is
    # dropped without a word, and catching *that* was considered and refused
    # twice. Naming those types here would mean `core.model` importing
    # `core.mcp_interface`, or a sentinel class in the shared ground standing
    # in for the import — the coupling ADR 009 exists to prevent, smuggled in
    # for the sake of a better error message. A concept that helps a developer
    # neither *define* a capability nor the framework *run* one is a spare
    # part. The mistake that actually happened in the wild was `class
    # MyThing(Resource)`, and that one now fails at import; see
    # `mcp_interface/resource.py`.
    members: dict[str, DeclaredMember] = {}
    for attribute, value, owner in _walk_declarations(cls, ignore):
        if isinstance(value, member_types) or _is_member_class(value, member_types):
            members[attribute] = DeclaredMember(
                attribute=attribute,
                value=_materialize(value, member_types, cls, attribute),
                declared_by=owner,
                factory=value if _is_member_class(value, member_types) else None,
            )

    return Declaration(
        owner=cls.__name__,
        name=name,
        description=description,
        instructions=instructions,
        members=tuple(members.values()),
    )


def _walk_declarations(
    cls: type,
    ignore: frozenset[str],
) -> Iterator[tuple[str, Any, str]]:
    for klass in reversed(cls.__mro__):
        for attribute, value in vars(klass).items():
            if attribute.startswith("_") or attribute in ignore:
                continue
            if isinstance(value, MemberDescriptorType):
                # A slot from the base dataclass, not a declared member.
                continue
            if isinstance(value, (staticmethod, classmethod, property)):
                continue
            if callable(value) and not isinstance(value, type):
                continue
            yield attribute, value, klass.__name__


def _is_member_class(value: Any, member_types: tuple[type, ...]) -> bool:
    return isinstance(value, type) and issubclass(value, member_types)


def _materialize(
    value: Any,
    member_types: tuple[type, ...],
    owner: type,
    attribute: str,
) -> Any:
    """Instantiate a declared member class; pass instances through unchanged.

    Declaring `diagnose = DiagnoseDeployment` and `diagnose =
    DiagnoseDeployment()` should mean the same thing, so a bare class is built
    here, at class-creation time, and the result is what the declaration
    reports: it is the prototype every validation reads, and it is what a
    caller inspecting `declaration` gets.

    It is **not** what an owning instance holds. `DeclaredMember.build` makes a
    fresh one per owner, because a member shared by two owners is one object at
    two addresses.
    """

    if not _is_member_class(value, member_types):
        return value
    try:
        return value()
    except TypeError as exc:
        raise DeclarationError(
            f"{owner.__name__}.{attribute} declares {value.__name__}, which "
            "cannot be built without arguments. Declare an instance instead of "
            "the class."
        ) from exc


def scalar(cls: type, attribute: str) -> str | None:
    """Read a scalar the class body stated, ignoring the dataclass's own slots.

    A plain getattr cannot be used here. `name` and `instructions` are slots on
    the base dataclass, so getattr returns the slot descriptor rather than None
    when nobody declared a value, and every undeclared attribute would look
    like a type error.
    """

    for klass in cls.__mro__:
        if attribute not in vars(klass):
            continue
        value = vars(klass)[attribute]
        if isinstance(value, MemberDescriptorType):
            return None
        if not isinstance(value, str):
            raise DeclarationError(
                f"{cls.__name__}.{attribute} must be a string, not "
                f"{type(value).__name__}."
            )
        stripped = value.strip()
        return stripped or None
    return None


def string_sequence(cls: type, attribute: str) -> tuple[str, ...] | None:
    """Read a declared sequence of strings, ignoring the dataclass's own slots.

    The sibling of `scalar` for the fields whose value is several strings
    rather than one. A lone string is accepted and wrapped, because
    ``uses = "a/b"`` and ``uses = ("a/b",)`` should not mean different things —
    the shorter one is what somebody writes first, and silently treating it as
    a sequence of one-character refs would be the worst possible reading.
    """

    for klass in cls.__mro__:
        if attribute not in vars(klass):
            continue
        value = vars(klass)[attribute]
        if isinstance(value, MemberDescriptorType):
            return None
        if isinstance(value, str):
            return (value,) if value.strip() else ()
        if not isinstance(value, (tuple, list)):
            raise DeclarationError(
                f"{cls.__name__}.{attribute} must be a string or a sequence of "
                f"strings, not {type(value).__name__}."
            )
        entries = []
        for entry in value:
            if not isinstance(entry, str):
                raise DeclarationError(
                    f"{cls.__name__}.{attribute} contains "
                    f"{type(entry).__name__}; every entry must be a string."
                )
            entries.append(entry)
        return tuple(entries)
    return None


def require_unique(
    values: Mapping[str, str],
    *,
    owner: str,
    label: str,
) -> None:
    """Fail at class creation when declared names collide.

    `values` maps attribute name to the node name it produces, so the error can
    name the two attributes a reader has to go look at.
    """

    seen: dict[str, str] = {}
    for attribute, node_name in values.items():
        previous = seen.get(node_name)
        if previous is not None:
            raise DeclarationError(
                f"{owner} declares two {label} named {node_name!r}: "
                f"`{previous}` and `{attribute}`."
            )
        seen[node_name] = attribute


__all__ = [
    "Declaration",
    "DeclaredMember",
    "RESERVED_ATTRIBUTES",
    "collect",
    "derive_description",
    "derive_name",
    "is_declarative",
    "require_unique",
    "scalar",
]
