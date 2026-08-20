"""Composite role objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Iterator

from .node import ContextNode
from ..errors import (
    DuplicateNameError,
    LookupFailure,
    ModelValidationError,
    NodeNotFoundError,
)
from .skill import Skill
from .tool import Tool
from ..types import CompiledContext


@dataclass(slots=True, kw_only=True)
class Role(ContextNode):
    """A responsibility boundary composed from roles, skills, and tools.

    ::

        class KubernetesOperator(Role):
            def __init__(self) -> None:
                super().__init__(
                    name="k8s-operator",
                    description="Operate and diagnose Kubernetes workloads.",
                    instructions="Inspect before changing the cluster.",
                    children=[DeploymentOps()],
                    skills=[DiagnoseDeployment()],
                    tools=[GetPodLogs(), GetPodStatus()],
                )

        manager.register_role(KubernetesOperator)

    **Members are built here, never discovered.** Three lists rather than one,
    because which of the three a capability belongs in is the modelling
    decision this framework asks a business to make. The three also survive
    translation: they are three typed slices in Go and three typed arrays in
    TypeScript, where one mixed list is neither.

    **Building them inside this constructor is what defers everything.** The
    members of a role that nobody registers are never constructed, and two
    registrations of one class are two independent subtrees — which matters as
    soon as anything is stamped onto a node, because a shared member would take
    the last stamp written anywhere in the process.

    **Membership is fixed once a tree has been built from this role.** The four
    member lists are ordinary lists, and assembling one at runtime is supported
    — that is what the imperative door is for. Changing one *after* the role is
    serving is not: since the 2026-07-28 revision a server may not vary its
    surface as a consequence of an earlier call, and an `append` here does
    exactly that. It also skips the uniqueness, cycle, and
    separator checks, which all run at construction. Build the graph you mean to serve, then leave it alone;
    `tests/test_binding.py` holds the statelessness this depends on.
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
    children: list[Role] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)
    tools: list[Tool] = field(default_factory=list)

    kind: ClassVar[str] = "role"

    def __post_init__(self) -> None:
        ContextNode.__post_init__(self)
        if not self.instructions.strip():
            raise ModelValidationError(
                f"Role {self.name!r} must have active instructions."
            )
        self._require_built_members()
        self._require_unique_members()

    def members(self) -> Iterator[ContextNode]:
        """Yield everything this role holds, in a stable order.

        One definition of "what this role contains", used by the uniqueness
        check below, by `member()`, and by every caller that needs to walk a
        role without caring which of the three lists a thing came from. The
        three lists stay as fields because a declaration states them separately
        and a payload groups them separately; traversal is where they are one
        thing.
        """

        yield from self.children
        yield from self.skills
        yield from self.tools

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

    def _require_built_members(self) -> None:
        """Refuse a class where a node belongs.

        A member list holds nodes, and a class is not one — it is a factory for
        one. The mistake is `tools=[GetPodLogs]` where `tools=[GetPodLogs()]`
        was meant, and it is caught at the construction site because that is
        where somebody can see both halves of it.

        Left to itself the mistake is quiet and strange: a class carries the
        base dataclass's slot descriptors, so every unbuilt member reads as
        having the same `name`, and the first thing to fail is the uniqueness
        check below with a sentence about two members sharing a name that
        nobody wrote.
        """

        for held in (self.children, self.skills, self.tools):
            for member in held:
                if isinstance(member, type):
                    raise ModelValidationError(
                        f"Role {self.name!r} holds the class "
                        f"{member.__name__}, not a node. Build it: "
                        f"{member.__name__}() — a member list holds nodes, and "
                        "a class is the factory that makes one."
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
        `core.disclosure`, and `core.model` must not know they exist. A half-listed
        member is worse than an unlisted one — it can be seen and not opened.
        """

        return {**self._compile_route(), "instructions": self.instructions}
