"""Composite role objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Iterable, Iterator

from . import declarative
from .context import ContextNode
from .errors import (
    DeclarationError,
    DuplicateNameError,
    LookupFailure,
    ModelValidationError,
    NodeNotFoundError,
)
from .resources import Resource
from .skill import Skill
from .tools import Tool
from .types import CompiledContext


@dataclass(slots=True, kw_only=True)
class Role(ContextNode):
    """A responsibility boundary composed from roles, skills, tools, and resources.

    Build one imperatively::

        Role(name="k8s-operator", description="...", instructions="...")

    or declare one as a class, which is how a business project states a role it
    owns::

        class KubernetesOperator(Role):
            '''Operate and diagnose Kubernetes workloads.'''

            instructions = "Inspect before changing the cluster."

            diagnose = DiagnoseDeployment
            inspect_logs = GetPodLogs
            runbook = CrashLoopRunbook

    Subclassing states what one role *is*. It never states containment: a role
    that coordinates other roles holds them in `children`, whether it was
    declared or assembled at runtime.

    **Membership is fixed once a tree has been built from this role.** The four
    member lists are ordinary lists, and assembling one at runtime is supported
    — that is what the imperative door is for. Changing one *after* the role is
    serving is not: since the 2026-07-28 revision a server may not vary its
    surface as a consequence of an earlier call, and an `append` here does
    exactly that. It also skips the uniqueness, cycle, and
    separator checks, which all run at construction. Build the graph you mean to serve, then leave it alone;
    `tests/test_projection.py` holds the statelessness this depends on.
    """

    #: How this role behaves once opened, and how it uses what it holds.
    #:
    #: The second half is what a composite role runs on. Opening a role returns
    #: this text alongside a route card for each member, and a card says what a
    #: member is, never when to reach for it relative to its siblings. A role
    #: that coordinates others owns no tools at all, so every word here is
    #: orchestration — which branch a task belongs to, and what has to be
    #: established before one of them is opened.
    instructions: str
    # Which of the four a thing belongs in is the modelling decision this
    # framework asks a business to make, and the four questions are:
    #
    #   children   Is this a branch a session enters *instead of* its
    #              siblings? Since ADR 007 the role axis is lazy, so a child
    #              costs one round trip to reach and nothing at all to anyone
    #              who never goes there — its card arrives only when this role
    #              is opened. Splitting work that a single task needs both
    #              halves of buys the round trip and none of the saving.
    #   skills     Is this a method rather than a capability — something the
    #              model performs by following it, using tools that belong to
    #              the role rather than to the method?
    #   tools      Can the framework execute this deterministically? If the
    #              answer is "the model has to judge", it is a skill.
    #   resources  Is this content that exists whether or not anybody asks?
    #              A read-only tool computes an answer from arguments; a
    #              resource is already there and has its own stable URI.
    children: list[Role] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)
    tools: list[Tool] = field(default_factory=list)
    resources: list[Resource] = field(default_factory=list)

    kind: ClassVar[str] = "role"

    #: The class-body declaration, or None on an imperatively built Role.
    declaration: ClassVar[declarative.Declaration | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        # A zero-argument super() raises TypeError in this method: dataclass
        # slots=True rebuilds the class object, so the implicit __class__ cell
        # still points at the discarded original. Name the class explicitly.
        super(Role, cls).__init_subclass__(**kwargs)
        if not declarative.is_declarative(cls, Role):
            return
        declaration = declarative.collect(
            cls,
            member_types=(Role, Skill, Tool, Resource),
        )
        _validate_declaration(cls, declaration)
        cls.declaration = declaration
        cls.__init__ = _declarative_init  # type: ignore[method-assign]

    def __post_init__(self) -> None:
        ContextNode.__post_init__(self)
        if not self.instructions.strip():
            raise ModelValidationError(
                f"Role {self.name!r} must have active instructions."
            )
        self._require_unique_members()
        self._require_unique(
            (resource.uri for resource in self.resources),
            "resource URIs",
        )

    def members(self) -> Iterator[ContextNode]:
        """Yield everything this role holds, in a stable order.

        One definition of "what this role contains", used by the uniqueness
        check below, by `member()`, and by every caller that needs to walk a
        role without caring which of the four lists a thing came from. The four
        lists stay as fields because a declaration states them separately and a
        payload groups them separately; traversal is where they are one thing.
        """

        yield from self.children
        yield from self.skills
        yield from self.tools
        yield from self.resources

    def member(self, name: str) -> ContextNode:
        """Return the one member of this role called `name`.

        The lookup is cross-kind because the invariant that makes it possible
        is cross-kind: `_require_unique_members` refuses a role whose skill and
        tool share a name, precisely so that a name is a complete address
        within one role. This method is what that constraint was paid for.
        """

        for member in self.members():
            if member.name == name:
                return member
        raise NodeNotFoundError(
            reason=LookupFailure.NO_SUCH_MEMBER,
            segment=name,
            scope=self.name,
            known=sorted(held.name for held in self.members()),
        )

    def _require_unique_members(self) -> None:
        """Reject two members of this role that share a name.

        Uniqueness is checked across kinds rather than within them, because a
        member's name is the last segment of the reference that addresses it. A
        skill and a tool that share a name would share an address, and `member()`
        would have to guess which one was meant. Refusing the declaration is
        better than guessing, and a role holding two things called `diagnose`
        was going to confuse a reader anyway.
        """

        seen: dict[str, str] = {}
        for member in self.members():
            previous = seen.get(member.name)
            if previous is not None:
                raise DuplicateNameError(
                    f"Role {self.name!r} declares a {previous} and a "
                    f"{member.kind} both named {member.name!r}. A member's "
                    "name is the last segment of its reference, so members of "
                    "one role cannot share a name."
                )
            seen[member.name] = member.kind

    @staticmethod
    def _require_unique(values: Iterable[str], label: str) -> None:
        materialized = list(values)
        if len(materialized) != len(set(materialized)):
            raise DuplicateNameError(f"A role contains duplicate {label}.")

    def _compile_active(self) -> CompiledContext:
        """Describe this role, and nothing around it.

        A role does not list its members here. It cannot list them completely:
        a member is only reachable through a reference, references belong to
        `contexture.tree`, and `core` must not know they exist. A half-listed
        member is worse than an unlisted one — it can be seen and not opened.
        """

        return {**self._compile_route(), "instructions": self.instructions}


def _validate_declaration(
    cls: type,
    declaration: declarative.Declaration,
) -> None:
    """Reject a contradictory class body while the class is being created.

    These are the collisions a reader cannot see by looking at one attribute,
    so they are worth catching at import rather than at the first instantiation
    somewhere else in the program.
    """

    if declaration.instructions is None:
        raise DeclarationError(
            f"{cls.__name__} must state `instructions`; a Role without them "
            "has nothing to disclose once it becomes the active role, and a "
            "role that holds other nodes has nowhere to say how they are used."
        )

    declarative.require_unique(
        {
            member.attribute: member.value.name
            for member in declaration.members
            if isinstance(member.value, Skill)
        },
        owner=cls.__name__,
        label="skills",
    )
    declarative.require_unique(
        {
            member.attribute: member.value.name
            for member in declaration.members
            if isinstance(member.value, Role)
        },
        owner=cls.__name__,
        label="child roles",
    )
    declarative.require_unique(
        {
            member.attribute: member.value.name
            for member in declaration.members
            if isinstance(member.value, Tool)
        },
        owner=cls.__name__,
        label="tools",
    )
    declarative.require_unique(
        {
            member.attribute: member.value.uri
            for member in declaration.members
            if isinstance(member.value, Resource)
        },
        owner=cls.__name__,
        label="resources",
    )


def _declarative_init(self: Role, **overrides: Any) -> None:
    """Build a declared Role, letting the caller override any stated field."""

    declaration = type(self).declaration
    assert declaration is not None  # set by __init_subclass__ before rebinding
    Role.__init__(
        self,
        **{
            "name": declaration.name,
            "description": declaration.description,
            "instructions": declaration.instructions,
            "children": list(declaration.of_type(Role)),
            "skills": list(declaration.of_type(Skill)),
            "tools": list(declaration.of_type(Tool)),
            "resources": list(declaration.of_type(Resource)),
            **overrides,
        },
    )
