"""The inbound boundary: what it takes to serve declared capabilities.

`MCPClient` is the outbound half of MCP — the host calling somebody else's
server. This module is the inbound half: the port a business application
implements so its own tools and resources can be served over MCP.

Only the port and a reference in-memory implementation live here. A deployable
server is deliberately absent until two independent callers have shown what it
must do; the port is the boundary that keeps that decision cheap to make later.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

from ..core.constants import JSON_RPC_VERSION
from ..core.errors import DuplicateNameError, NodeNotFoundError
from ..core.resources import MCPResource
from ..core.tools import MCPTool
from ..core.types import JsonObject, JsonValue

METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602


@dataclass(slots=True, frozen=True, kw_only=True)
class ToolResult:
    """What a business tool handler returns to the host."""

    content: tuple[JsonObject, ...] = ()
    structured_content: JsonValue | None = None
    is_error: bool = False

    @classmethod
    def text(cls, text: str, *, is_error: bool = False) -> ToolResult:
        """Build the common single-text-block result."""

        return cls(content=({"type": "text", "text": text},), is_error=is_error)

    def to_protocol_dict(self) -> JsonObject:
        payload: JsonObject = {
            "resultType": "complete",
            "content": [deepcopy(block) for block in self.content],
            "isError": self.is_error,
        }
        if self.structured_content is not None:
            payload["structuredContent"] = deepcopy(self.structured_content)
        return payload


@dataclass(slots=True, frozen=True, kw_only=True)
class ResourceContents:
    """What a business resource provider returns to the host."""

    uri: str
    text: str | None = None
    blob: str | None = None
    mime_type: str | None = None

    def to_protocol_dict(self) -> JsonObject:
        payload: JsonObject = {"uri": self.uri}
        if self.mime_type is not None:
            payload["mimeType"] = self.mime_type
        if self.text is not None:
            payload["text"] = self.text
        if self.blob is not None:
            payload["blob"] = self.blob
        return payload


@runtime_checkable
class ToolHandler(Protocol):
    """A business implementation behind one declared MCPTool."""

    async def __call__(self, arguments: Mapping[str, Any]) -> ToolResult:
        """Execute the tool and return its result."""


@runtime_checkable
class ResourceProvider(Protocol):
    """A business implementation behind one declared MCPResource."""

    async def __call__(self, uri: str) -> ResourceContents:
        """Load the content addressed by the resource URI."""


class MCPHostPort(Protocol):
    """The boundary a host implements to expose declared capabilities.

    Contexture's model layer depends on this shape and never on a concrete
    server, so an application can serve its capabilities from a standalone
    process, an existing web service, or an in-process test double without the
    declarations changing.
    """

    def register_tool(self, tool: MCPTool, handler: ToolHandler) -> None:
        """Bind a declared tool to the code that performs it."""

    def register_resource(
        self,
        resource: MCPResource,
        provider: ResourceProvider,
    ) -> None:
        """Bind a declared resource to the code that loads it."""


@dataclass(slots=True, kw_only=True)
class InMemoryHost:
    """A reference MCPHostPort that answers MCP requests in process.

    This is a test double and a demonstration, not a deployable server: it has
    no transport, no authentication, and no lifecycle. It exists so the model
    layer can be exercised end to end against real handlers instead of a
    hand-written fake, and so the eventual server has a worked example of what
    the port must satisfy.
    """

    tools: dict[str, tuple[MCPTool, ToolHandler]] = field(default_factory=dict)
    resources: dict[str, tuple[MCPResource, ResourceProvider]] = field(
        default_factory=dict
    )

    def register_tool(self, tool: MCPTool, handler: ToolHandler) -> None:
        if tool.name in self.tools:
            raise DuplicateNameError(
                f"Tool {tool.name!r} is already registered on this host."
            )
        self.tools[tool.name] = (tool, handler)

    def register_resource(
        self,
        resource: MCPResource,
        provider: ResourceProvider,
    ) -> None:
        if resource.uri in self.resources:
            raise DuplicateNameError(
                f"Resource {resource.uri!r} is already registered on this host."
            )
        self.resources[resource.uri] = (resource, provider)

    def get_tool(self, tool_name: str) -> MCPTool:
        try:
            return self.tools[tool_name][0]
        except KeyError as exc:
            raise NodeNotFoundError(
                f"Tool {tool_name!r} is not registered on this host."
            ) from exc

    def get_resource(self, uri: str) -> MCPResource:
        try:
            return self.resources[uri][0]
        except KeyError as exc:
            raise NodeNotFoundError(
                f"Resource {uri!r} is not registered on this host."
            ) from exc

    async def handle(
        self,
        payload: Mapping[str, Any],
        headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        """Dispatch one JSON-RPC request against the registered capabilities.

        The signature matches InMemoryTransport's handler so a host can be
        wired straight into a client for round-trip tests.
        """

        request_id = payload.get("id")
        method = payload.get("method")
        params = payload.get("params") or {}

        if method == "tools/list":
            return self._ok(
                request_id,
                {
                    "resultType": "complete",
                    "tools": [
                        tool.to_protocol_dict() for tool, _ in self.tools.values()
                    ],
                },
            )

        if method == "resources/list":
            return self._ok(
                request_id,
                {
                    "resources": [
                        resource.to_protocol_dict()
                        for resource, _ in self.resources.values()
                    ]
                },
            )

        if method == "tools/call":
            name = params.get("name")
            entry = self.tools.get(name)
            if entry is None:
                return self._error(
                    request_id, INVALID_PARAMS, f"Unknown tool {name!r}."
                )
            _, handler = entry
            result = await handler(params.get("arguments") or {})
            return self._ok(request_id, result.to_protocol_dict())

        if method == "resources/read":
            uri = params.get("uri")
            entry = self.resources.get(uri)
            if entry is None:
                return self._error(
                    request_id, INVALID_PARAMS, f"Unknown resource {uri!r}."
                )
            _, provider = entry
            contents = await provider(uri)
            return self._ok(
                request_id, {"contents": [contents.to_protocol_dict()]}
            )

        return self._error(
            request_id, METHOD_NOT_FOUND, f"Method {method!r} is not supported."
        )

    @staticmethod
    def _ok(request_id: Any, result: JsonObject) -> JsonObject:
        return {"jsonrpc": JSON_RPC_VERSION, "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> JsonObject:
        return {
            "jsonrpc": JSON_RPC_VERSION,
            "id": request_id,
            "error": {"code": code, "message": message},
        }
