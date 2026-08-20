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
    contexture_invoke_read_only      run a tool that leaves the world unchanged
    contexture_invoke                run a tool that does not

The other two primitives carry what a model does not drive: prompts a person
triggers by name, and resources a host may take up on its own. Both are
declared in `core.mcp_interface` and hung here, and both name a node the tree
still holds — so nothing on them is a second copy of anything.

**`read_only` is which door, not which argument.** A host cannot see a business
tool any more, so it cannot be told per tool whether to ask a human first. It
can see which of the two doors was used, and each door carries the matching
`readOnlyHint`. A model may pick the wrong one — and picking it gets the call
refused rather than executed, which is the same protection as never letting the
classification be an argument, relocated to where the host can still act on it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Sequence

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.prompts import Prompt as SDKPrompt
from mcp.server.mcpserver.resources import FunctionResource
from mcp.server.mcpserver.tools import Tool as SDKTool
from mcp_types import Completion, ToolAnnotations

from ..core.errors import ContextureError, ModelValidationError, NodeNotFoundError
from ..core.mcp_interface.prompt import Prompt
from ..core.mcp_interface.resource import Resource
from ..core.model.tool import Tool
from ..core.principal import bound
from .identity import principal_of
from ..core.types import CompiledContext, JsonObject
from ..core.disclosure.tree import SEPARATOR, ContextTree
from ..core.mcp_interface.tool import (
    DISCOVER_TOOL,
    GATEWAY,
    INVOKE_READ_ONLY_TOOL,
    INVOKE_TOOL,
    OPEN_TOOL,
)
from . import messages


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
    surface: Sequence[Prompt | Resource] = (),
) -> None:
    """Register the five gateway tools against `tree`.

    `dispatch` is the same object whose `schema` method the tree was built
    with, so a card's schema and the validation a call is checked against
    are derived once, from one place.

    `surface` is what this server puts on the prompt and resource primitives.
    Empty is the ordinary case: a declaration reaches an agent through the
    gateway whether or not anybody named a way in for a person.

    Returns nothing. It used to return a record of what had been registered,
    from back when that varied with the declaration; behind a fixed gateway it
    could only ever restate `GATEWAY_TOOLS`, and a caller that wants
    to know what is on the wire should ask the server rather than be told by
    the function that wrote to it.
    """


    # Computed before the entry points are defined, because `contexture_open`
    # closes over it. A prompt that reserves its node for a person is the only
    # thing that puts a ref in here.
    reserved = frozenset(
        entry.opens
        for entry in surface
        if isinstance(entry, Prompt) and not entry.model_may_open
    )

    async def contexture_discover() -> CompiledContext:
        # What the agent is told about this entry point is in `contract`.
        with _translated(DISCOVER_TOOL):
            return tree.skeleton()

    async def contexture_open(ref: str) -> CompiledContext:
        with _translated(OPEN_TOOL):
            if ref in reserved:
                # Refused here rather than in the tree, because the tree holds
                # no opinion about who is asking and only this layer knows
                # which door a call came through. The same division
                # `wrong_door` rests on.
                raise ToolError(messages.command_taken_by_a_person(ref))
            return tree.open(ref)

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
        INVOKE_READ_ONLY_TOOL: contexture_invoke_read_only,
        INVOKE_TOOL: contexture_invoke,
    }

    # Registered from the contract rather than five call sites, so "the surface
    # is exactly these five, described exactly this way" is a fact about one
    # tuple instead of an agreement between ten places.
    for entry in GATEWAY:
        server.add_tool(
            implementations[entry.name],
            name=entry.name,
            description=entry.description,
            annotations=ToolAnnotations(read_only_hint=entry.read_only),
        )

    _project_surface(server, tree=tree, dispatch=dispatch, surface=surface)


def _project_surface(
    server: MCPServer,
    *,
    tree: ContextTree,
    dispatch: Dispatch,
    surface: Sequence[Prompt | Resource],
) -> None:
    """Hang the declared surface on the two primitives the model does not drive.

    Each entry names a node and the tree keeps holding it, so a capability
    reached this way and reached by navigating is one capability with two
    addresses rather than two declarations that can disagree.

    One entry per declaration and no more: the count is what somebody wrote
    down, never what the forest holds, which is what keeps a menu a menu and
    keeps the surface legal — a server may not vary these lists once it is
    serving.

    Every `opens` is resolved here, at startup. A surface naming a node that
    does not exist must fail on the way up rather than in front of whoever
    reached for it.
    """

    _reject_ambiguous_names(surface)

    for entry in surface:
        name = _surface_name(entry)
        if isinstance(entry, Prompt):
            node = _resolve(tree, entry.opens, "prompt")
            # No arguments: the node is fixed at registration, so there is
            # nothing for a person to fill in and nothing to complete. The
            # prompt *is* the argument.
            server.add_prompt(
                SDKPrompt.from_function(
                    _command(tree, entry.opens),
                    name=name,
                    description=messages.command_description(
                        entry.opens, entry.description or node.description
                    ),
                )
            )
        else:
            _require_content_tool(tree, dispatch, entry)
            server.add_resource(
                FunctionResource.from_function(
                    _reader(tree, entry.opens),
                    uri=entry.uri,
                    name=name,
                    description=entry.description,
                    mime_type=entry.mime_type,
                )
            )

    async def goto(ref: str) -> str:
        return await _open_by_name(tree, ref)

    server.add_prompt(
        SDKPrompt.from_function(
            goto,
            name=messages.GOTO_PROMPT,
            description=messages.GOTO_DESCRIPTION,
        )
    )

    @server.completion()
    async def complete(
        ref: Any,
        argument: Any,
        context: Any,
    ) -> Completion | None:
        """Offer the tree's addresses while a person types one.

        Answers for `goto` and nothing else. A declared command takes no
        argument — the node it opens was fixed when it was registered — so
        there is nothing there to complete, and answering anyway would put
        this server's refs under somebody else's prompt.
        """

        if getattr(ref, "name", None) != messages.GOTO_PROMPT:
            return None
        if argument.name != messages.GOTO_ARGUMENT:
            return None

        matches, total = tree.matching_refs(
            argument.value, limit=messages.COMPLETION_LIMIT
        )
        values = list(matches)
        if total > len(values):
            # The protocol carries `total` and `has_more`, and a host may show
            # neither. One value spent saying so is cheaper than a person
            # believing they have seen everything.
            values[-1] = messages.truncated_completion(len(values), total)
        return Completion(values=values, total=total, has_more=total > len(matches))


def _surface_name(entry: Prompt | Resource) -> str:
    """The name a host shows, defaulting to the last segment of the ref.

    A second name, independent of position — the same thing a URI has always
    been for a document, now the only kind of second name in the package.
    """

    return entry.name or entry.opens.rsplit(SEPARATOR, 1)[-1]


def _reject_ambiguous_names(surface: Iterable[Prompt | Resource]) -> None:
    """Refuse two entries somebody would reach the same way.

    A node's name only has to be unique among its siblings, because a ref
    supplies the rest of the address. Here there is no such context: these are
    flat names in a menu, so two `deploy` prompts from two branches produce one
    name nobody can aim.

    Refused rather than disambiguated. Generating `deploy-2`, or spelling a
    whole ref into a menu, both answer "which one did you mean" with something
    nobody would have chosen — and the declaration is right there to be edited.
    """

    names: dict[tuple[str, str], str] = {}
    uris: dict[str, str] = {}
    for entry in surface:
        key = (entry.kind, _surface_name(entry))
        if key in names:
            raise ModelValidationError(
                f"{names[key]!r} and {entry.opens!r} are both exposed as the "
                f"{entry.kind} {_surface_name(entry)!r}. A ref tells them "
                "apart and a name in a menu cannot; rename one."
            )
        names[key] = entry.opens
        if isinstance(entry, Resource):
            if entry.uri in uris:
                raise ModelValidationError(
                    f"{uris[entry.uri]!r} and {entry.opens!r} are both "
                    f"published at {entry.uri!r}. One address names one thing."
                )
            uris[entry.uri] = entry.opens


def _resolve(tree: ContextTree, ref: str, kind: str) -> Any:
    """Resolve one `opens`, turning a miss into a declaration error.

    A failed lookup here has a different audience from one at request time:
    nobody is waiting on an answer, and the person who can fix it is whoever
    wrote the declaration. So it does not become `messages.unresolved`.
    """

    try:
        return tree.find(ref)
    except NodeNotFoundError as failure:
        raise ModelValidationError(
            f"The {kind} for {ref!r} names a node that does not exist "
            f"({failure.reason.value}). A surface entry is resolved when the "
            "server is built so that it fails on the way up rather than in "
            "front of whoever reached for it."
        ) from None


def _require_content_tool(
    tree: ContextTree,
    dispatch: Dispatch,
    entry: Resource,
) -> None:
    """Refuse a resource that does not name content already sitting there.

    A resource is *fetched*, not computed: two reads return the same bytes
    until the document itself changes. That shape is exactly a read-only tool
    with no arguments, and both halves are checked — a tool with parameters has
    no answer to give when a host reads it with none, and a writing tool run by
    a host that thinks it is fetching a document is the wrong door with nobody
    at it.
    """

    _resolve(tree, entry.opens, "resource")
    tool = tree.tool(entry.opens)
    if not tool.read_only:
        raise ModelValidationError(
            f"Resource {entry.uri!r} names {entry.opens!r}, which is not "
            "read-only. Reading a resource must leave the world unchanged."
        )
    if dispatch.schema(tool).get("properties"):
        raise ModelValidationError(
            f"Resource {entry.uri!r} names {entry.opens!r}, which takes "
            "arguments. A host reads a resource with none, so what it names "
            "has to answer with none."
        )


def _reader(tree: ContextTree, ref: str) -> Callable[[], Awaitable[Any]]:
    """Build the function a host calls when it reads this resource.

    Resolved per call rather than captured, for the same reason a command's
    text is assembled per call: one node reached two ways must not be able to
    answer two different things.
    """

    async def read() -> Any:
        return await tree.tool(ref).invoke()

    return read


def _command(tree: ContextTree, ref: str) -> Callable[[], Awaitable[str]]:
    """Build the one prompt that opens `ref`.

    The text is assembled per call rather than at registration, so a command
    and `contexture_open` cannot answer differently about the same node — a
    snapshot taken at startup is a second copy waiting to disagree.

    The message is **the payload `contexture_open` would have returned**, plus
    signposts. Reaching a capability two ways and being told two different
    things about how to call it is worse than either answer alone, so the two
    doors differ in who may knock and in nothing else.
    """

    async def command() -> str:
        return await _open_by_name(tree, ref)

    return command


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


async def _open_by_name(tree: ContextTree, ref: str) -> str:
    """Render one node for a person who named it rather than navigated to it.

    Shared by `goto` and by every declared command, which is what makes them
    the same door with two ways of addressing it: a command carries the ref in
    its registration, `goto` carries it in an argument, and a person gets the
    same answer either way.

    No `opened_by` check. That field says which *plane* may reach a node, and
    both callers here are the person's plane; a node marked for a model alone
    is still a node a person may look at, and refusing would mean the tree held
    capabilities its owner could not read.
    """

    with _translated(messages.GOTO_PROMPT):
        payload = tree.open(ref)
        levels = tree.signpost(ref)
    sections = [
        messages.COMMAND_PREAMBLE.format(ref=ref),
        messages.signpost(levels),
        json.dumps(payload, ensure_ascii=False, indent=2),
        messages.COMMAND_CLOSING,
    ]
    return "\n\n".join(section for section in sections if section)


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
        raise ToolError(messages.wrong_door(ref, is_read_only=tool.read_only))

    # The one place in the package where a caller's identity is put where a
    # capability can read it, and it is here because this is the one place
    # business code runs. Discovering and opening do not reach a declaration's
    # own code, so binding around them would widen the scope of a global for
    # nobody's benefit.
    #
    # The translation goes through `AccessToken` rather than a side table kept
    # by the verifier, so a deployment that installs an SDK-native verifier
    # instead of `Auth` still gets a working `current_principal()`. Unsecured
    # transports bind `None`, which is the honest answer and the one every
    # capability that cares must already handle.
    with bound(principal_of(get_access_token())):
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
            raise ToolError(messages.unresolved(exc)) from exc
        # Everything else here is a declaration-time failure with one audience
        # — whoever wrote the declaration — so it already carries its sentence.
        raise ToolError(str(exc)) from exc


__all__ = ["Dispatch", "project"]
