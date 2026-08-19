"""Project a declared capability graph onto a native MCP surface.

This module is the only place in Contexture that knows what MCP looks like on
the wire, and it contains no business rules of its own. Everything it does is a
translation:

    Contexture                       MCP
    ----------------------------     -------------------------------------
    local Tool                       a native tool; schema from `invoke`
    local Resource                   a native resource; lazy `read`
    DisclosureEngine.discover        the tool `contexture_discover`
    DisclosureEngine.get_context     the tool `contexture_get_context`
    root roles                       server instructions

Two invariants are load-bearing enough to name here.

**`read_only` never becomes an argument.** It is a trusted host classification,
so it is projected onto the protocol's `readOnlyHint` annotation, where a host
can act on it. A model that could pass its own approval flag would be approving
its own writes, which is not approval at all.

**The graph never becomes the surface.** MCP tool and resource lists are flat
and, since 2026-07-28, may not vary per connection. The role tree therefore
travels inside the payload of the two framework tools, never as protocol shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.resources import FunctionResource
from mcp_types import ToolAnnotations

from ..core.errors import ContextureError, DuplicateNameError
from ..core.resources import Resource
from ..core.tools import Tool
from ..core.types import CompiledContext
from ..discovery import CapabilityGraph, DisclosureEngine

#: The two tools every Contexture server exposes regardless of what it serves.
DISCOVER_TOOL = "contexture_discover"
GET_CONTEXT_TOOL = "contexture_get_context"


@dataclass(slots=True, kw_only=True)
class Projection:
    """What one projection registered, so a caller can assert on it."""

    framework_tools: tuple[str, ...]
    business_tools: tuple[str, ...]
    resources: tuple[str, ...]


def project(
    server: MCPServer,
    *,
    graph: CapabilityGraph,
    engine: DisclosureEngine,
) -> Projection:
    """Register the graph's capabilities and the two framework tools."""

    _register_framework_tools(server, engine)
    business = _register_tools(server, graph)
    resources = _register_resources(server, graph)
    return Projection(
        framework_tools=(DISCOVER_TOOL, GET_CONTEXT_TOOL),
        business_tools=business,
        resources=resources,
    )


def _register_framework_tools(
    server: MCPServer,
    engine: DisclosureEngine,
) -> None:
    async def contexture_discover(ref: str | None = None) -> CompiledContext:
        """List what is available here as routing cards.

        Call with no ref to see every top-level role. Call with a role ref to
        see the sub-roles, skills, tools, and resources directly under it. Cards
        never contain instructions; each carries a `ref` to open it.
        """

        with _translated_errors(DISCOVER_TOOL):
            return engine.discover(ref)

    async def contexture_get_context(ref: str) -> CompiledContext:
        """Open one capability and return its full detail.

        Pass a `ref` taken from a routing card. A skill returns its complete
        instructions here and nowhere else. A resource returns its descriptor;
        read its content through the resource itself.
        """

        with _translated_errors(GET_CONTEXT_TOOL):
            return engine.get_context(ref)

    server.add_tool(
        contexture_discover,
        name=DISCOVER_TOOL,
        description=(
            "List the roles, skills, tools, and resources available here as "
            "short routing cards. Start every task with this."
        ),
        annotations=ToolAnnotations(read_only_hint=True),
    )
    server.add_tool(
        contexture_get_context,
        name=GET_CONTEXT_TOOL,
        description=(
            "Open one capability by ref and return its full detail, including "
            "a skill's complete instructions."
        ),
        annotations=ToolAnnotations(read_only_hint=True),
    )


def _register_tools(server: MCPServer, graph: CapabilityGraph) -> tuple[str, ...]:
    registered: dict[str, Tool] = {}
    for _, role, tool in graph.local_tools():
        assert isinstance(tool, Tool)
        existing = registered.get(tool.name)
        if existing is not None:
            raise DuplicateNameError(
                f"Two different tools are both named {tool.name!r}. MCP tool "
                "names are flat and global, so give one of them an explicit "
                "`name` in its class body."
            )
        registered[tool.name] = tool
        server.add_tool(
            tool.invoke,
            name=tool.name,
            description=tool.description,
            # read_only is host policy, projected as a hint and never as input.
            annotations=ToolAnnotations(read_only_hint=tool.read_only),
        )
    return tuple(registered)


def _register_resources(
    server: MCPServer,
    graph: CapabilityGraph,
) -> tuple[str, ...]:
    registered: dict[str, Resource] = {}
    for _, role, resource in graph.local_resources():
        assert isinstance(resource, Resource)
        existing = registered.get(resource.uri)
        if existing is not None:
            raise DuplicateNameError(
                f"Two different resources both claim URI {resource.uri!r}."
            )
        registered[resource.uri] = resource
        server.add_resource(
            FunctionResource.from_function(
                resource.read,
                uri=resource.uri,
                name=resource.name,
                description=resource.description,
                mime_type=resource.mime_type,
            )
        )
    return tuple(registered)


class _translated_errors:
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
        # KeyError subclasses repr their argument; strip the quotes it adds.
        message = exc.args[0] if exc.args else str(exc)
        raise ToolError(str(message)) from exc


__all__ = [
    "DISCOVER_TOOL",
    "GET_CONTEXT_TOOL",
    "Projection",
    "project",
]
