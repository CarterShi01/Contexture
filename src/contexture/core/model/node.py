"""The common progressive-disclosure lifecycle."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar

from ..errors import ModelValidationError
from ..types import CompiledContext


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

    kind: ClassVar[str] = "context_node"

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ModelValidationError("Context node name must not be empty.")
        if not self.description.strip():
            raise ModelValidationError(
                f"Context node {self.name!r} must have a routing description."
            )

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

        return {
            "kind": self.kind,
            "name": self.name,
            "description": self.description,
        }

    @abstractmethod
    def _compile_active(self) -> CompiledContext:
        """Return the detailed surface for an explicitly activated node."""

        raise NotImplementedError
