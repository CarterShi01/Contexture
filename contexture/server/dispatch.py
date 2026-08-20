"""Deriving a tool's schema, and running it with its arguments checked.

`core` opens two seams and fills neither: `ContextTree.schema_source`, which a
card's `input_schema` comes from, and `SystemAPI.execute`, which is where a
business tool actually runs. Both default to doing nothing useful, so that the
object model stays exercisable with no wire in the room.

**`Dispatch` is the one object that fills both**, and that it is one object is
the point rather than a saving. A schema written on a card by one thing and a
check applied to a call by another is the worst kind of drift: an agent calls
exactly what it was told to call and is refused. Here they are two views of a
single derivation, which is why `main` names it once and hands it to both::

    dispatch = Dispatch()
    tree     = manager.sealed(schema_of=dispatch.schema)
    assembly = Assembly.of(tree, execute=dispatch.execute, published=PUBLISHED)

`SDKTool.from_function` needs no server, which is what lets a business tool's
schema be derived from `invoke`'s type hints and its arguments validated
without the tool ever appearing in `tools/list`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.tools import Tool as SDKTool

from ..core.model.tool import Tool
from ..core.principal import bound
from ..core.types import JsonObject
from .identity import principal_of

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

    async def execute(
        self,
        tool: Tool,
        arguments: dict[str, Any] | None,
        context: Any,
    ) -> Any:
        """Run one business tool, with its caller in reach of its own code.

        This is the seam `SystemAPI.execute` names, and the one place in the
        package where a caller's identity is put where a capability can read
        it. Here, and not around the whole call, because this is the one point
        at which business code runs — discovering and opening reach no
        declaration's own code, so binding around them would widen the scope of
        a global for nobody's benefit.

        The translation goes through `AccessToken` rather than a side table
        kept by the verifier, so a deployment that installs an SDK-native
        verifier instead of `Auth` still gets a working `current_principal()`.
        Unsecured transports bind `None`, which is the honest answer and the
        one every capability that cares must already handle.
        """

        with bound(principal_of(get_access_token())):
            return await self.run(tool, arguments, context)


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


__all__ = ["Dispatch"]
