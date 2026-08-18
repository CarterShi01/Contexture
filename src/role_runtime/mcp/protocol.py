"""JSON-RPC 2.0 and MCP 2026-07-28 request construction."""

from __future__ import annotations

import base64
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..constants import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    JSON_RPC_VERSION,
    MCP_PROTOCOL_VERSION,
    PROTOCOL_VERSION_META_KEY,
)
from ..errors import MCPProtocolError, ModelValidationError
from ..types import JsonObject, JsonValue, RequestId
from .models import MCPTool

_HEADER_TOKEN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_BASE64_SENTINEL = re.compile(r"^=\?base64\?.*\?=$", re.DOTALL)
_MAX_SAFE_INTEGER = (2**53) - 1


@dataclass(slots=True, frozen=True, kw_only=True)
class ClientInfo:
    """Self-reported MCP client implementation information."""

    name: str
    version: str
    title: str | None = None
    description: str | None = None
    website_url: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.version.strip():
            raise ModelValidationError(
                "MCP client name and version must both be non-empty."
            )

    def to_protocol_dict(self) -> JsonObject:
        result: JsonObject = {
            "name": self.name,
            "version": self.version,
        }
        if self.title is not None:
            result["title"] = self.title
        if self.description is not None:
            result["description"] = self.description
        if self.website_url is not None:
            result["websiteUrl"] = self.website_url
        return result


@dataclass(slots=True, frozen=True, kw_only=True)
class JSONRPCRequest:
    """A JSON-RPC 2.0 request with a non-null request id."""

    request_id: RequestId
    method: str
    params: JsonObject

    def __post_init__(self) -> None:
        if isinstance(self.request_id, bool):
            raise MCPProtocolError("A JSON-RPC request id cannot be a boolean.")
        if not isinstance(self.request_id, (str, int)):
            raise MCPProtocolError("A JSON-RPC request id must be a string or integer.")
        if not self.method:
            raise MCPProtocolError("A JSON-RPC method must not be empty.")

    def to_dict(self) -> JsonObject:
        return {
            "jsonrpc": JSON_RPC_VERSION,
            "id": self.request_id,
            "method": self.method,
            "params": deepcopy(self.params),
        }


@dataclass(slots=True, frozen=True, kw_only=True)
class JSONRPCErrorObject:
    """The error member of a JSON-RPC error response."""

    code: int
    message: str
    data: JsonValue | None = None


@dataclass(slots=True, frozen=True, kw_only=True)
class JSONRPCResponse:
    """A validated JSON-RPC result or error response."""

    request_id: RequestId | None
    result: JsonValue | None = None
    error: JSONRPCErrorObject | None = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> JSONRPCResponse:
        if payload.get("jsonrpc") != JSON_RPC_VERSION:
            raise MCPProtocolError("Response jsonrpc must equal '2.0'.")

        has_result = "result" in payload
        has_error = "error" in payload
        if has_result == has_error:
            raise MCPProtocolError(
                "A JSON-RPC response must contain exactly one of result or error."
            )

        request_id = payload.get("id")
        if request_id is not None and (
            isinstance(request_id, bool) or not isinstance(request_id, (str, int))
        ):
            raise MCPProtocolError("Response id must be a string, integer, or null.")

        if has_error:
            raw_error = payload["error"]
            if not isinstance(raw_error, Mapping):
                raise MCPProtocolError("JSON-RPC error must be an object.")
            code = raw_error.get("code")
            message = raw_error.get("message")
            if isinstance(code, bool) or not isinstance(code, int):
                raise MCPProtocolError("JSON-RPC error code must be an integer.")
            if not isinstance(message, str):
                raise MCPProtocolError("JSON-RPC error message must be a string.")
            return cls(
                request_id=request_id,
                error=JSONRPCErrorObject(
                    code=code,
                    message=message,
                    data=deepcopy(raw_error.get("data")),
                ),
            )

        return cls(
            request_id=request_id,
            result=deepcopy(payload.get("result")),
        )


@dataclass(slots=True, kw_only=True)
class MCPRequestFactory:
    """Build self-contained requests for MCP protocol version 2026-07-28."""

    client_info: ClientInfo
    client_capabilities: JsonObject = field(default_factory=dict)
    protocol_version: str = MCP_PROTOCOL_VERSION

    def build(
        self,
        *,
        request_id: RequestId,
        method: str,
        params: Mapping[str, Any] | None = None,
        progress_token: RequestId | None = None,
        extra_meta: Mapping[str, Any] | None = None,
    ) -> JSONRPCRequest:
        parameter_object: dict[str, Any] = deepcopy(dict(params or {}))
        caller_meta = parameter_object.pop("_meta", {})
        if not isinstance(caller_meta, Mapping):
            raise MCPProtocolError("Request params._meta must be an object.")

        meta: dict[str, Any] = {
            **deepcopy(dict(caller_meta)),
            **deepcopy(dict(extra_meta or {})),
            PROTOCOL_VERSION_META_KEY: self.protocol_version,
            CLIENT_INFO_META_KEY: self.client_info.to_protocol_dict(),
            CLIENT_CAPABILITIES_META_KEY: deepcopy(self.client_capabilities),
        }
        if progress_token is not None:
            meta["progressToken"] = progress_token

        parameter_object["_meta"] = meta
        return JSONRPCRequest(
            request_id=request_id,
            method=method,
            params=parameter_object,
        )


def build_request_headers(
    request: JSONRPCRequest,
    *,
    tool: MCPTool | None = None,
) -> dict[str, str]:
    """Build the required Streamable HTTP routing headers."""

    meta = request.params.get("_meta")
    if not isinstance(meta, Mapping):
        raise MCPProtocolError("MCP requests must contain params._meta.")
    body_version = meta.get(PROTOCOL_VERSION_META_KEY)
    if not isinstance(body_version, str):
        raise MCPProtocolError("MCP request metadata is missing protocolVersion.")

    headers = {
        "MCP-Protocol-Version": body_version,
        "Mcp-Method": request.method,
    }

    name_value: Any = None
    name_required = request.method in {
        "tools/call",
        "prompts/get",
        "resources/read",
    }
    if request.method in {"tools/call", "prompts/get"}:
        name_value = request.params.get("name")
    elif request.method == "resources/read":
        name_value = request.params.get("uri")

    if name_required and name_value is None:
        raise MCPProtocolError(
            f"MCP method {request.method!r} requires a value for Mcp-Name."
        )
    if name_value is not None:
        if not isinstance(name_value, str) or not name_value:
            raise MCPProtocolError(
                "The Mcp-Name source value must be a non-empty string."
            )
        headers["Mcp-Name"] = encode_header_value(name_value)

    if request.method == "tools/call" and tool is not None:
        request_tool_name = request.params.get("name")
        if request_tool_name != tool.name:
            raise MCPProtocolError(
                "The selected MCPTool does not match params.name in tools/call."
            )
        arguments = request.params.get("arguments", {})
        if not isinstance(arguments, Mapping):
            raise MCPProtocolError("tools/call arguments must be an object.")
        headers.update(extract_tool_parameter_headers(tool, arguments))

    return headers


def validate_x_mcp_headers(tool: MCPTool) -> None:
    """Validate every x-mcp-header annotation in a tool input schema."""

    _collect_header_bindings(tool.input_schema)


def extract_tool_parameter_headers(
    tool: MCPTool,
    arguments: Mapping[str, Any],
) -> dict[str, str]:
    """Extract and encode Mcp-Param-* headers from tools/call arguments."""

    headers: dict[str, str] = {}
    for path, header_suffix, expected_type in _collect_header_bindings(
        tool.input_schema
    ):
        found, value = _read_path(arguments, path)
        if not found:
            continue
        _validate_header_argument_type(value, expected_type, path)
        headers[f"Mcp-Param-{header_suffix}"] = encode_header_value(value)
    return headers


def encode_header_value(value: str | int | bool) -> str:
    """Encode an MCP mirrored header value using the 2026-07-28 rules."""

    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, int):
        text = str(value)
    elif isinstance(value, str):
        text = value
    else:
        raise MCPProtocolError(
            f"MCP header values must be string, integer, or boolean; received "
            f"{type(value).__name__}."
        )

    is_ascii_safe = all(
        character == "\t" or 0x20 <= ord(character) <= 0x7E
        for character in text
    )
    has_outer_whitespace = text != text.strip(" \t")
    matches_sentinel = bool(_BASE64_SENTINEL.match(text))

    if is_ascii_safe and not has_outer_whitespace and not matches_sentinel:
        return text

    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return f"=?base64?{encoded}?="


def _collect_header_bindings(
    schema: Mapping[str, Any],
) -> list[tuple[tuple[str, ...], str, str]]:
    bindings: list[tuple[tuple[str, ...], str, str]] = []
    seen_headers: set[str] = set()

    def walk(
        node: Any,
        *,
        path: tuple[str, ...],
        property_node: bool,
        direct_properties_chain: bool,
    ) -> None:
        if isinstance(node, Mapping):
            if "x-mcp-header" in node:
                if not property_node or not direct_properties_chain or not path:
                    raise ModelValidationError(
                        "x-mcp-header may only appear on properties reachable "
                        "through a direct properties chain."
                    )
                suffix = node["x-mcp-header"]
                if not isinstance(suffix, str) or not suffix:
                    raise ModelValidationError(
                        "x-mcp-header must be a non-empty string."
                    )
                if not _HEADER_TOKEN.fullmatch(suffix):
                    raise ModelValidationError(
                        f"Invalid x-mcp-header token {suffix!r}."
                    )
                normalized = suffix.lower()
                if normalized in seen_headers:
                    raise ModelValidationError(
                        f"Duplicate x-mcp-header token {suffix!r}."
                    )
                expected_type = node.get("type")
                if expected_type not in {"string", "integer", "boolean"}:
                    raise ModelValidationError(
                        "x-mcp-header is only valid on string, integer, or "
                        "boolean properties."
                    )
                seen_headers.add(normalized)
                bindings.append((path, suffix, expected_type))

            for key, value in node.items():
                if key == "properties" and isinstance(value, Mapping):
                    for property_name, property_schema in value.items():
                        if not isinstance(property_name, str):
                            raise ModelValidationError(
                                "JSON Schema property names must be strings."
                            )
                        walk(
                            property_schema,
                            path=path + (property_name,),
                            property_node=True,
                            direct_properties_chain=direct_properties_chain,
                        )
                elif key != "x-mcp-header":
                    walk(
                        value,
                        path=path,
                        property_node=False,
                        direct_properties_chain=False,
                    )
        elif isinstance(node, Sequence) and not isinstance(
            node, (str, bytes, bytearray)
        ):
            for item in node:
                walk(
                    item,
                    path=path,
                    property_node=False,
                    direct_properties_chain=False,
                )

    walk(
        schema,
        path=(),
        property_node=False,
        direct_properties_chain=True,
    )
    return bindings


def _read_path(
    payload: Mapping[str, Any],
    path: tuple[str, ...],
) -> tuple[bool, Any]:
    current: Any = payload
    for segment in path:
        if not isinstance(current, Mapping) or segment not in current:
            return False, None
        current = current[segment]
    return True, current


def _validate_header_argument_type(
    value: Any,
    expected_type: str,
    path: tuple[str, ...],
) -> None:
    location = ".".join(path)
    if expected_type == "string" and not isinstance(value, str):
        raise MCPProtocolError(f"Header argument {location!r} must be a string.")
    if expected_type == "boolean" and not isinstance(value, bool):
        raise MCPProtocolError(f"Header argument {location!r} must be a boolean.")
    if expected_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise MCPProtocolError(f"Header argument {location!r} must be an integer.")
        if not -_MAX_SAFE_INTEGER <= value <= _MAX_SAFE_INTEGER:
            raise MCPProtocolError(
                f"Header argument {location!r} exceeds the JavaScript safe "
                "integer range."
            )
