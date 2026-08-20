"""The common progressive-disclosure lifecycle."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Iterable

from .errors import ModelValidationError
from .types import CompiledContext


class Opener(str, Enum):
    """Who may cause a node to be disclosed.

    The disclosure *lifecycle* is unchanged by this — `CompileLevel` still has
    two levels and still means the same thing. This says who is allowed to
    trigger the move between them, which is a different question and the one
    MCP splits its three primitives along: tools are chosen by a model,
    prompts are chosen by a person. The 2026-07-28 revision states it exactly:
    "This refers to who decides when the prompt is used, not who authors its
    content."

    Until this existed every node in a Contexture server was MODEL and nothing
    was PERSON, which is one row of a table with three.
    """

    #: An agent may reach this node by navigating to it.
    MODEL = "model"

    #: A person may reach this node by name, without an agent choosing to.
    PERSON = "person"


class CompileLevel(str, Enum):
    """The two disclosure levels shared by all context nodes.

    Two, and there is no third, because an agent is only ever in one of two
    states with respect to a node: it has not chosen it yet, or it has. ROUTE
    serves the first and must stay cheap enough that a whole sibling set can be
    shown at once — a choice made among a subset of the alternatives is a
    guess. ACTIVE serves the second and can be as expensive as the work
    requires, because by then the agent has committed and nothing is being paid
    for speculatively.

    A middle level would have to answer "what does a node say to an agent that
    is halfway through choosing it", and there is no such moment.
    """

    ROUTE = "route"
    ACTIVE = "active"


@dataclass(slots=True, kw_only=True)
class ContextNode(ABC):
    """A node that can be progressively disclosed to an LLM context.

    The base class deliberately owns only the stable common contract:
    a machine-facing name, a routing description, and a compile lifecycle.
    Concrete node types decide what their active representation contains.
    """

    #: The machine-facing address. It is the last segment of the reference
    #: that opens this node, so it is chosen for uniqueness within its parent,
    #: not for readability.
    name: str

    #: The one sentence a model reads while deciding whether to open this node.
    #: It answers "should I go here", never "what will I find inside" — the
    #: inside is what opening delivers, and describing it twice is how the two
    #: copies start disagreeing.
    description: str

    #: Who may open this node. See `Opener`.
    #:
    #: **The default is MODEL alone, which is the opposite of the convention
    #: elsewhere, and the inversion is forced by scale.** A host that keeps a
    #: handful of skills in a flat directory can afford to offer every one of
    #: them on both planes. A Contexture server holds a forest, and a default
    #: of both planes would make the command surface grow with it — which the
    #: protocol makes worse rather than better, since a server may not vary
    #: that surface once it is serving.
    #:
    #: Marking a node PERSON is worth it only where **going wrong is
    #: expensive**. A command buys consistent execution, guardrails, and saved
    #: typing; saved typing is the weakest of the three, and everything a
    #: command could do can also be had by simply asking the agent. Marked
    #: everywhere, the command menu becomes a second copy of the tool list.
    opened_by: tuple[Opener, ...] = (Opener.MODEL,)

    kind: ClassVar[str] = "context_node"

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ModelValidationError("Context node name must not be empty.")
        if not self.description.strip():
            raise ModelValidationError(
                f"Context node {self.name!r} must have a routing description."
            )
        # Normalised here so that a declaration may write the plain strings a
        # person would write, and everything above this line reads one type.
        self.opened_by = _normalize_openers(self.name, self.opened_by)

    def compile(
        self,
        level: CompileLevel | str = CompileLevel.ROUTE,
    ) -> CompiledContext:
        """Compile the node into the requested disclosure surface."""

        normalized = CompileLevel(level)
        if normalized is CompileLevel.ROUTE:
            return self._compile_route()
        return self._compile_active()

    def _compile_route(self) -> CompiledContext:
        """Return the minimal surface that is safe for broad routing."""

        card: CompiledContext = {
            "kind": self.kind,
            "name": self.name,
            "description": self.description,
        }
        if self.opened_by != (Opener.MODEL,):
            # Stated only when it is not the default, so the common node pays
            # nothing for a field that would say the same thing every time.
            #
            # A card for a node a model may not open is still worth rendering.
            # The model cannot go there, but it can see that the capability
            # exists and tell the person which command reaches it, and a
            # guardrail that lets the model point is cooperative where one that
            # merely hides is not.
            card["opened_by"] = [opener.value for opener in self.opened_by]
        return card

    @abstractmethod
    def _compile_active(self) -> CompiledContext:
        """Return the detailed surface for an explicitly activated node."""

        raise NotImplementedError


def _normalize_openers(
    name: str,
    stated: Iterable[Opener | str],
) -> tuple[Opener, ...]:
    """Accept what a declaration writes; return what the framework reads."""

    openers: list[Opener] = []
    for entry in stated:
        try:
            opener = Opener(entry)
        except ValueError:
            raise ModelValidationError(
                f"Context node {name!r} says it is opened by {entry!r}. The "
                f"openers are: {', '.join(member.value for member in Opener)}."
            ) from None
        if opener not in openers:
            openers.append(opener)
    if not openers:
        raise ModelValidationError(
            f"Context node {name!r} states no opener. A node nobody may open "
            "is not disclosed to anybody, which is the same as not declaring "
            "it."
        )
    return tuple(openers)
