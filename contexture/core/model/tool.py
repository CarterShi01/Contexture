"""Tools: capabilities this application owns and can execute."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, ClassVar

from .node import ContextNode
from ..types import CompiledContext


@dataclass(slots=True, kw_only=True)
class Tool(ContextNode):
    """A capability this application owns, stated as a typed Python method.

    ::

        class GetPodLogs(Tool):
            def __init__(self) -> None:
                super().__init__(
                    name="pod_logs",
                    description="Return recent container logs for one Pod.",
                    read_only=True,
                )

            async def invoke(self, namespace: str, pod: str) -> str:
                ...

    A constructor that hands its identity to the base, and an `invoke` that is
    the behaviour. Nothing is inferred: not from the class name, which a
    TypeScript bundler rewrites, and not from the docstring, which no Go or
    TypeScript runtime can read. What an agent reads is written down.

    **The class is not the node.** Nothing here is built when this module is
    imported — a class is a zero-argument factory, and the parent role's own
    constructor is what calls it. So a graph comes into existence when a
    `ControllerManager` registers its root, which is the only moment a node can
    be told where it hangs and handed what it may reach.

    The parameter schema is never written by hand *in this implementation*. It
    is derived from `invoke`'s type hints when the tool is projected onto an MCP
    surface, which is why nothing in this layer needs to know what JSON Schema
    looks like. A Go or TypeScript implementation cannot read a signature that
    way and states an argument object instead; what conformance pins is the
    schema that reaches the wire, never how it was derived.

    `read_only` is a trusted host classification, not an agent-supplied
    argument. It is projected onto the protocol's `readOnlyHint` annotation so a
    host can decide whether to ask a human before running the tool, and it must
    never appear in the tool's input schema.

    A Tool is the only node the framework executes on the agent's behalf, and
    that is what separates it from the other three. A Skill describes work the
    model performs; a Tool performs work the model asked for. So the question
    that places something here is whether the answer can be *computed* — if
    producing it requires judgement, the model must do it and what belongs in
    the declaration is a Skill.

    Content this application already holds is a read-only Tool that takes no
    arguments: two calls return the same bytes, and it computes nothing. A host
    may publish one at a URI of its own — see `core.mcp_interface.resource` —
    but that is a second name for it, not a second kind of node.

    **One instance serves the whole process, so `invoke` must be re-entrant.**
    A Tool is built once, when the tree is, and every call to it — from every
    session, and from calls a host issues in parallel on one session — arrives
    at that same object. The SDK dispatches each request as its own task, so
    two `invoke` bodies interleave at every `await`. Writing per-call state onto
    `self` therefore loses it: the second call overwrites what the first read
    and had not yet used. Keep what a call needs in its arguments and its
    locals. This is a constraint on the object, not on your domain — locking,
    transactions, and idempotency belong to whatever `invoke` talks to, and the
    framework will never offer its own.

    Python will not enforce this. `Tool` is slotted, but a subclass that is not
    itself a slotted dataclass carries a `__dict__`, so `self.anything = ...`
    inside `invoke` silently succeeds and silently shares.
    """

    kind: ClassVar[str] = "tool"

    #: Whether running this tool leaves the world unchanged.
    #:
    #: A field rather than a class attribute, because it is stated where the
    #: rest of this tool's identity is stated — at the construction site, in
    #: the same literal a Go or TypeScript implementation would write.
    read_only: bool = False

    async def invoke(self, **arguments: Any) -> Any:
        """Execute the capability. Business subclasses state real parameters."""

        raise NotImplementedError(
            f"Tool {self.name!r} does not implement invoke()."
        )

    def parameters(self) -> tuple[str, ...]:
        """Return the parameter names `invoke` accepts, in declaration order.

        Every one of them, including any the framework fills rather than the
        model — this reports the signature, not the call. What an agent may
        pass is the tool's input schema, which is derived a layer up by
        something that knows which parameters are the framework's; a disclosure
        payload must use that and not this, or it will name an argument the
        schema rejects.
        """

        signature = inspect.signature(type(self).invoke)
        return tuple(
            name
            for name, parameter in signature.parameters.items()
            if name != "self"
            and parameter.kind
            not in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD)
        )

    def _compile_active(self) -> CompiledContext:
        # No parameter list. `core` reads the signature and cannot tell a
        # model-filled argument from a framework-filled one; the input schema
        # can, and `ContextTree.open` attaches the same one the tool's card
        # carries, so the two ways of reaching a tool now agree.
        return {
            **self._compile_route(),
            "read_only": self.read_only,
        }
