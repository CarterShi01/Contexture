"""Project the tree onto a fixed five-tool gateway.

This module is the only place in Contexture that knows what MCP looks like on
the wire, and it holds no business rules of its own.

**Business capabilities do not go on the surface.** MCP tool and resource lists
are flat and, since the 2026-07-28 revision, stateless: a server may not vary
them per connection or as a consequence of an earlier call. So a capability
that is registered is a capability every session pays for, forever, whatever
the user asked. The only way a tool becomes deferrable is for it not to be on
the surface at all — its name, description and schema travel inside a payload
instead, and arrive when the role holding it is opened.

What is on the surface is five tools, whatever the declaration contains::

    contexture_discover              the role skeleton
    contexture_open                  one node's detail, plus its members' cards
    contexture_read                  a resource's content
    contexture_invoke_read_only      run a tool that leaves the world unchanged
    contexture_invoke                run a tool that does not

**`read_only` is which door, not which argument.** A host cannot see a business
tool any more, so it cannot be told per tool whether to ask a human first. It
can see which of the two doors was used, and each door carries the matching
`readOnlyHint`. A model may pick the wrong one — and picking it gets the call
refused rather than executed, which is the same protection as never letting the
classification be an argument, relocated to where the host can still act on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool as SDKTool
from mcp_types import ToolAnnotations

from ..core.errors import ContextureError
from ..core.tools import Tool
from ..core.types import CompiledContext, JsonObject
from ..tree import ContextTree

DISCOVER_TOOL = "contexture_discover"
OPEN_TOOL = "contexture_open"
READ_TOOL = "contexture_read"
INVOKE_READ_ONLY_TOOL = "contexture_invoke_read_only"
INVOKE_TOOL = "contexture_invoke"

#: Every tool this server will ever expose, in the order they are registered.
GATEWAY_TOOLS = (
    DISCOVER_TOOL,
    OPEN_TOOL,
    READ_TOOL,
    INVOKE_READ_ONLY_TOOL,
    INVOKE_TOOL,
)


@dataclass(slots=True)
class Dispatch:
    """SDK-backed schema derivation and validated execution, off the wire.

    `SDKTool.from_function` needs no server, which is what lets a business
    tool's schema be derived from `invoke`'s type hints and its arguments be
    validated, without the tool ever appearing in `tools/list`.

    Instances are cached by identity because the tree owns its tools for the
    whole life of the server, and rebuilding a pydantic model on every `open`
    of a role would charge a real cost for nothing.
    """

    _derived: dict[int, SDKTool] = field(default_factory=dict, repr=False)

    def schema(self, tool: Tool) -> JsonObject:
        return self._sdk(tool).parameters

    async def run(
        self,
        tool: Tool,
        arguments: dict[str, Any] | None,
        context: Context,
    ) -> Any:
        return await self._sdk(tool).run(arguments or {}, context)

    def _sdk(self, tool: Tool) -> SDKTool:
        derived = self._derived.get(id(tool))
        if derived is None:
            derived = SDKTool.from_function(
                tool.invoke,
                name=tool.name,
                description=tool.description,
            )
            self._derived[id(tool)] = derived
        return derived


@dataclass(slots=True, kw_only=True)
class Projection:
    """What one projection put on the wire, so a caller can assert on it."""

    tools: tuple[str, ...]


def project(
    server: MCPServer,
    *,
    tree: ContextTree,
    dispatch: Dispatch,
) -> Projection:
    """Register the five gateway tools against `tree`.

    `dispatch` is the same object whose `schema` method the tree was built
    with, so a card's schema and the validation a call is checked against
    are derived once, from one place.
    """


    async def contexture_discover() -> CompiledContext:
        """List every role this server serves, as short routing cards.

        Each card carries the `ref` that opens it. Cards never contain
        instructions, tool schemas, or document content — opening a role is
        what delivers those. The same list is in this server's instructions.
        """

        with _translated(DISCOVER_TOOL):
            return tree.skeleton()

    async def contexture_open(ref: str) -> CompiledContext:
        """Open one capability by ref and return its detail.

        Opening a role returns its instructions and a card for every skill,
        tool, resource and sub-role it holds, each with the ref that opens it,
        and each tool with the schema needed to call it. Opening a skill
        returns its complete procedure, which is available here and nowhere
        else. Pass a `ref` taken from a card; never assemble one.
        """

        with _translated(OPEN_TOOL):
            return tree.open(ref)

    async def contexture_read(ref: str) -> str | bytes:
        """Return the content of one resource.

        Accepts either the `ref` from its card or the resource's own URI, so a
        procedure that names a document the way the document names itself can
        be followed literally.
        """

        with _translated(READ_TOOL):
            resource = tree.resource(ref)
        return await resource.read()

    async def contexture_invoke_read_only(
        ctx: Context,
        ref: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """Run a tool that leaves the world unchanged.

        `ref` and `arguments` come from the tool's card, which appears when its
        role is opened. A tool that is not read-only is refused here; use
        contexture_invoke for those.
        """

        return await _invoke(tree, dispatch, ctx, ref, arguments, read_only=True)

    async def contexture_invoke(
        ctx: Context,
        ref: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """Run a tool that changes something.

        `ref` and `arguments` come from the tool's card, which appears when its
        role is opened. A read-only tool is refused here; use
        contexture_invoke_read_only for those, so a host can tell the two apart.
        """

        return await _invoke(tree, dispatch, ctx, ref, arguments, read_only=False)

    server.add_tool(
        contexture_discover,
        name=DISCOVER_TOOL,
        description=(
            "List every role this server serves as short routing cards. Start "
            "here, then open the role that matches the task."
        ),
        annotations=ToolAnnotations(read_only_hint=True),
    )
    server.add_tool(
        contexture_open,
        name=OPEN_TOOL,
        description=(
            "Open one role, skill, tool, or resource by ref. Opening a role "
            "reveals what it holds; opening a skill delivers its procedure."
        ),
        annotations=ToolAnnotations(read_only_hint=True),
    )
    server.add_tool(
        contexture_read,
        name=READ_TOOL,
        description=(
            "Return the content of one resource, addressed by its ref or its "
            "URI."
        ),
        annotations=ToolAnnotations(read_only_hint=True),
    )
    server.add_tool(
        contexture_invoke_read_only,
        name=INVOKE_READ_ONLY_TOOL,
        description=(
            "Run a tool that only reads. Use this for every tool whose card "
            "says read_only: true."
        ),
        annotations=ToolAnnotations(read_only_hint=True),
    )
    server.add_tool(
        contexture_invoke,
        name=INVOKE_TOOL,
        description=(
            "Run a tool that changes something. Use this for every tool whose "
            "card says read_only: false."
        ),
        annotations=ToolAnnotations(read_only_hint=False),
    )

    return Projection(tools=GATEWAY_TOOLS)


async def _invoke(
    tree: ContextTree,
    dispatch: Dispatch,
    context: Context,
    ref: str,
    arguments: dict[str, Any] | None,
    *,
    read_only: bool,
) -> Any:
    """Resolve, check the door, then run."""

    entry = INVOKE_READ_ONLY_TOOL if read_only else INVOKE_TOOL
    with _translated(entry):
        tool = tree.tool(ref)

    if tool.read_only is not read_only:
        # The host decided whether to involve a human from the hint on the
        # entry point. Honouring a mismatch would run a write under a
        # read-only approval, so the mismatch is refused instead.
        correct = INVOKE_READ_ONLY_TOOL if tool.read_only else INVOKE_TOOL
        raise ToolError(
            f"{ref} is {'read-only' if tool.read_only else 'not read-only'}, "
            f"so it must be run through {correct}."
        )

    return await dispatch.run(tool, arguments, context)


class _translated:
    """Turn Contexture's own failures into a message an agent can act on.

    A wrong ref is a routine, recoverable mistake — the agent should read what
    was wrong and try a different one — so it must arrive as a legible sentence
    rather than a repr of an internal exception type.
    """

    __slots__ = ("_tool",)

    def __init__(self, tool: str) -> None:
        self._tool = tool

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        if exc is None or not isinstance(exc, ContextureError):
            return False
        message = exc.args[0] if exc.args else str(exc)
        raise ToolError(str(message)) from exc


__all__ = [
    "DISCOVER_TOOL",
    "Dispatch",
    "GATEWAY_TOOLS",
    "INVOKE_READ_ONLY_TOOL",
    "INVOKE_TOOL",
    "OPEN_TOOL",
    "Projection",
    "READ_TOOL",
    "project",
]
