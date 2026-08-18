"""A focused MCP 2026-07-28 client for tool discovery and invocation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from itertools import count
from typing import Any, Mapping

from ..errors import MCPProtocolError, MCPRemoteError, ModelValidationError
from ..types import JsonObject, JsonValue
from .models import MCPTool
from .protocol import (
    ClientInfo,
    JSONRPCResponse,
    MCPRequestFactory,
    build_request_headers,
    validate_x_mcp_headers,
)
from .transport import MCPTransport


@dataclass(slots=True, frozen=True, kw_only=True)
class ToolCatalog:
    """A complete, paginated tools/list result assembled by the client."""

    tools: tuple[MCPTool, ...]
    warnings: tuple[str, ...] = ()
    ttl_ms: int | None = None
    cache_scope: str | None = None


@dataclass(slots=True, frozen=True, kw_only=True)
class ToolCallOutcome:
    """A tools/call result, including opaque non-complete result types."""

    result_type: str
    content: tuple[JsonObject, ...]
    structured_content: JsonValue | None
    is_error: bool
    raw: JsonObject

    @property
    def is_complete(self) -> bool:
        return self.result_type == "complete"

    @classmethod
    def from_result(cls, result: Mapping[str, Any]) -> ToolCallOutcome:
        result_type = result.get("resultType", "complete")
        if not isinstance(result_type, str) or not result_type:
            raise MCPProtocolError("Tool resultType must be a non-empty string.")

        raw_content = result.get("content", [])
        if not isinstance(raw_content, list) or not all(
            isinstance(item, dict) for item in raw_content
        ):
            raise MCPProtocolError("Tool result content must be an array of objects.")

        is_error = result.get("isError", False)
        if not isinstance(is_error, bool):
            raise MCPProtocolError("Tool result isError must be a boolean.")

        return cls(
            result_type=result_type,
            content=tuple(deepcopy(raw_content)),
            structured_content=deepcopy(result.get("structuredContent")),
            is_error=is_error,
            raw=deepcopy(dict(result)),
        )


@dataclass(slots=True, kw_only=True)
class MCPClient:
    """A stateless MCP client that adds request metadata on every call."""

    transport: MCPTransport
    client_info: ClientInfo = field(
        default_factory=lambda: ClientInfo(
            name="role-runtime-starter",
            version="0.1.0",
        )
    )
    client_capabilities: JsonObject = field(default_factory=dict)

    notifications: list[JsonObject] = field(default_factory=list, init=False)
    _request_ids: Any = field(default_factory=lambda: count(1), init=False, repr=False)
    _factory: MCPRequestFactory = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._factory = MCPRequestFactory(
            client_info=self.client_info,
            client_capabilities=self.client_capabilities,
        )

    async def list_tools(self) -> ToolCatalog:
        """Fetch all pages from tools/list and exclude malformed tool entries."""

        tools: list[MCPTool] = []
        warnings: list[str] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        ttl_ms: int | None = None
        cache_scope: str | None = None

        while True:
            params: JsonObject = {}
            if cursor is not None:
                params["cursor"] = cursor

            result = await self._request("tools/list", params=params)
            if not isinstance(result, Mapping):
                raise MCPProtocolError("tools/list result must be an object.")

            raw_tools = result.get("tools")
            if not isinstance(raw_tools, list):
                raise MCPProtocolError("tools/list result.tools must be an array.")

            for index, raw_tool in enumerate(raw_tools):
                if not isinstance(raw_tool, Mapping):
                    warnings.append(f"Ignored tool at index {index}: not an object.")
                    continue
                try:
                    tool = MCPTool.from_protocol_dict(raw_tool)
                    validate_x_mcp_headers(tool)
                except ModelValidationError as exc:
                    tool_name = raw_tool.get("name", f"index {index}")
                    warnings.append(f"Ignored tool {tool_name!r}: {exc}")
                    continue
                tools.append(tool)

            raw_ttl = result.get("ttlMs")
            if raw_ttl is not None:
                if isinstance(raw_ttl, bool) or not isinstance(raw_ttl, int):
                    raise MCPProtocolError("tools/list ttlMs must be an integer.")
                ttl_ms = raw_ttl

            raw_scope = result.get("cacheScope")
            if raw_scope is not None:
                if raw_scope not in {"public", "private"}:
                    raise MCPProtocolError(
                        "tools/list cacheScope must be 'public' or 'private'."
                    )
                cache_scope = raw_scope

            next_cursor = result.get("nextCursor")
            if next_cursor is None:
                break
            if not isinstance(next_cursor, str) or not next_cursor:
                raise MCPProtocolError(
                    "tools/list nextCursor must be a non-empty string."
                )
            if next_cursor in seen_cursors:
                raise MCPProtocolError("tools/list returned a repeated cursor.")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        return ToolCatalog(
            tools=tuple(tools),
            warnings=tuple(warnings),
            ttl_ms=ttl_ms,
            cache_scope=cache_scope,
        )

    async def call_tool(
        self,
        tool: MCPTool,
        arguments: Mapping[str, Any] | None = None,
        *,
        request_state: str | None = None,
        input_responses: Mapping[str, Any] | None = None,
    ) -> ToolCallOutcome:
        """Invoke one MCP tool using its protocol name, not the host tool_ref."""

        params: dict[str, Any] = {
            "name": tool.name,
            "arguments": deepcopy(dict(arguments or {})),
        }
        if request_state is not None:
            params["requestState"] = request_state
        if input_responses is not None:
            params["inputResponses"] = deepcopy(dict(input_responses))

        result = await self._request(
            "tools/call",
            params=params,
            tool=tool,
        )
        if not isinstance(result, Mapping):
            raise MCPProtocolError("tools/call result must be an object.")
        return ToolCallOutcome.from_result(result)

    async def _request(
        self,
        method: str,
        *,
        params: Mapping[str, Any] | None = None,
        tool: MCPTool | None = None,
    ) -> JsonValue:
        request = self._factory.build(
            request_id=next(self._request_ids),
            method=method,
            params=params,
        )
        headers = build_request_headers(request, tool=tool)
        transport_result = await self.transport.send(request.to_dict(), headers)

        matching_response: JSONRPCResponse | None = None
        for message in transport_result.messages:
            if "id" not in message:
                self.notifications.append(deepcopy(message))
                continue
            response = JSONRPCResponse.from_dict(message)
            if response.request_id == request.request_id:
                matching_response = response

        if matching_response is None:
            raise MCPProtocolError(
                f"No JSON-RPC response matched request id {request.request_id!r}."
            )
        if matching_response.error is not None:
            raise MCPRemoteError(
                matching_response.error.code,
                matching_response.error.message,
                matching_response.error.data,
            )
        return matching_response.result
