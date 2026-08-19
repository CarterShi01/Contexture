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

    contexture_discover              the root roles, one level
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

from ..core.errors import ContextureError, NodeNotFoundError
from ..core.tools import Tool
from ..core.types import CompiledContext, JsonObject
from ..tree import ContextTree
from . import contract
from .contract import (
    DISCOVER_TOOL,
    INVOKE_READ_ONLY_TOOL,
    INVOKE_TOOL,
    OPEN_TOOL,
    READ_TOOL,
)


@dataclass(slots=True)
class Dispatch:
    """SDK-backed schema derivation and validated execution, off the wire.

    `SDKTool.from_function` needs no server, which is what lets a business
    tool's schema be derived from `invoke`'s type hints and its arguments be
    validated, without the tool ever appearing in `tools/list`.

    Derivations are cached by identity, because rebuilding a pydantic model on
    every `open` of a role would charge a real cost for nothing. The cache
    holds the tool alongside its derivation, and that reference is the point:
    `id()` is only unique among live objects, so a cache keyed by it while
    holding nothing would hand a later tool the schema of an earlier one that
    had been collected. Today the tree keeps every tool alive for the life of
    the server and the collision cannot happen — but that is the tree's
    property, not this cache's, and nothing here would notice it changing.

    The disclosed schema is cached beside the derivation rather than recomputed,
    because it is not the derivation: `title` is stripped from it, and doing
    that on every card of every `open` would pay for the same walk repeatedly.
    Validation still runs against the SDK's own copy, which keeps its titles.
    """

    _derived: dict[int, tuple[Tool, SDKTool, JsonObject]] = field(
        default_factory=dict, repr=False
    )

    def schema(self, tool: Tool) -> JsonObject:
        return self._entry(tool)[2]

    async def run(
        self,
        tool: Tool,
        arguments: dict[str, Any] | None,
        context: Context,
    ) -> Any:
        return await self._entry(tool)[1].run(arguments or {}, context)

    def _entry(self, tool: Tool) -> tuple[Tool, SDKTool, JsonObject]:
        cached = self._derived.get(id(tool))
        if cached is None:
            derived = SDKTool.from_function(
                tool.invoke,
                name=tool.name,
                description=tool.description,
            )
            cached = (tool, derived, _without_titles(derived.parameters))
            self._derived[id(tool)] = cached
        return cached


def project(
    server: MCPServer,
    *,
    tree: ContextTree,
    dispatch: Dispatch,
) -> None:
    """Register the five gateway tools against `tree`.

    `dispatch` is the same object whose `schema` method the tree was built
    with, so a card's schema and the validation a call is checked against
    are derived once, from one place.

    Returns nothing. It used to return a record of what had been registered,
    from back when that varied with the declaration; behind a fixed gateway it
    could only ever restate `contract.GATEWAY_TOOLS`, and a caller that wants
    to know what is on the wire should ask the server rather than be told by
    the function that wrote to it.
    """


    async def contexture_discover() -> CompiledContext:
        # What the agent is told about this entry point is in `contract`.
        with _translated(DISCOVER_TOOL):
            return tree.skeleton()

    async def contexture_open(ref: str) -> CompiledContext:
        with _translated(OPEN_TOOL):
            return tree.open(ref)

    async def contexture_read(ref: str) -> str | bytes:
        with _translated(READ_TOOL):
            resource = tree.resource(ref)
        return await resource.read()

    async def contexture_invoke_read_only(
        ctx: Context,
        ref: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        return await _invoke(tree, dispatch, ctx, ref, arguments, read_only=True)

    async def contexture_invoke(
        ctx: Context,
        ref: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        return await _invoke(tree, dispatch, ctx, ref, arguments, read_only=False)

    implementations = {
        DISCOVER_TOOL: contexture_discover,
        OPEN_TOOL: contexture_open,
        READ_TOOL: contexture_read,
        INVOKE_READ_ONLY_TOOL: contexture_invoke_read_only,
        INVOKE_TOOL: contexture_invoke,
    }

    # Registered from the contract rather than five call sites, so "the surface
    # is exactly these five, described exactly this way" is a fact about one
    # tuple instead of an agreement between ten places.
    for entry in contract.GATEWAY:
        server.add_tool(
            implementations[entry.name],
            name=entry.name,
            description=entry.description,
            annotations=ToolAnnotations(read_only_hint=entry.read_only),
        )


#: JSON Schema keywords whose value is one schema.
_SUBSCHEMA = ("items", "additionalProperties", "not", "contains", "propertyNames")

#: Keywords whose value is a list of schemas.
_SUBSCHEMA_LIST = ("anyOf", "oneOf", "allOf", "prefixItems")

#: Keywords whose value maps a *name* to a schema. The names are left alone: a
#: business tool is free to take a parameter called `title`, and stripping by
#: key name alone would delete the parameter instead of its label.
_SUBSCHEMA_MAP = ("properties", "$defs", "definitions", "patternProperties")


def _without_titles(schema: JsonObject) -> JsonObject:
    """Return the schema with every `title` keyword removed.

    Pydantic derives a title from whatever Python name it saw: the model it
    built for `invoke` becomes `"title": "invokeArguments"`, and a parameter
    called `pod` becomes `"title": "Pod"`. Both reach the agent on every tool
    card, and neither tells it anything — one is a framework internal it has no
    use for, the other is a capitalised copy of the key it sits under. Across
    the bundled reference application they came to 730 characters of nothing,
    before the payload's own indentation.

    A title stated deliberately, through `Annotated[..., Field(title=...)]`,
    goes with them. That is the accepted cost: `description` is the field a
    model actually reads, it is untouched, and it is what a parameter that
    needs explaining should carry.

    Walked by keyword rather than by key name so that a parameter named `title`
    survives — see `_SUBSCHEMA_MAP`.
    """

    cleaned: JsonObject = {}
    for key, value in schema.items():
        if key == "title":
            continue
        if key in _SUBSCHEMA_MAP and isinstance(value, dict):
            cleaned[key] = {
                name: _without_titles(sub) if isinstance(sub, dict) else sub
                for name, sub in value.items()
            }
        elif key in _SUBSCHEMA and isinstance(value, dict):
            cleaned[key] = _without_titles(value)
        elif key in _SUBSCHEMA_LIST and isinstance(value, list):
            cleaned[key] = [
                _without_titles(sub) if isinstance(sub, dict) else sub
                for sub in value
            ]
        else:
            cleaned[key] = value
    return cleaned


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
        raise ToolError(contract.wrong_door(ref, is_read_only=tool.read_only))

    return await dispatch.run(tool, arguments, context)


class _translated:
    """Turn Contexture's own failures into a message an agent can act on.

    A wrong ref is a routine, recoverable mistake — the agent should read what
    was wrong and try a different one — so it must arrive as a legible sentence
    rather than a repr of an internal exception type.

    This is the single point where a failure raised anywhere below becomes
    something an agent reads, which is why the sentence is composed here from
    the facts the failure carries rather than pre-written at the raise site.
    The tree that hits the failure cannot name the tool that recovers from it.
    """

    __slots__ = ("_tool",)

    def __init__(self, tool: str) -> None:
        self._tool = tool

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        if exc is None or not isinstance(exc, ContextureError):
            return False
        if isinstance(exc, NodeNotFoundError):
            raise ToolError(contract.unresolved(exc)) from exc
        # Everything else here is a declaration-time failure with one audience
        # — whoever wrote the declaration — so it already carries its sentence.
        raise ToolError(str(exc)) from exc


__all__ = ["Dispatch", "project"]
