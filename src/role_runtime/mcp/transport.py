"""Transport abstraction and a small Streamable HTTP implementation."""

from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Protocol
from urllib import error as urllib_error
from urllib import request as urllib_request

from ..errors import MCPTransportError
from ..types import JsonObject


@dataclass(slots=True, frozen=True, kw_only=True)
class TransportResult:
    """All JSON-RPC messages carried by one transport response."""

    messages: tuple[JsonObject, ...]
    status_code: int = 200
    content_type: str = "application/json"
    response_headers: Mapping[str, str] = field(default_factory=dict)


class MCPTransport(Protocol):
    """The transport boundary used by MCPClient."""

    async def send(
        self,
        payload: JsonObject,
        headers: Mapping[str, str],
    ) -> TransportResult:
        """Send one self-contained JSON-RPC request."""


InMemoryHandler = Callable[
    [JsonObject, Mapping[str, str]],
    JsonObject | list[JsonObject] | Awaitable[JsonObject | list[JsonObject]],
]


@dataclass(slots=True, kw_only=True)
class InMemoryTransport:
    """A deterministic transport for tests and local demonstrations."""

    handler: InMemoryHandler
    requests: list[tuple[JsonObject, dict[str, str]]] = field(
        default_factory=list,
        init=False,
    )

    async def send(
        self,
        payload: JsonObject,
        headers: Mapping[str, str],
    ) -> TransportResult:
        copied_headers = dict(headers)
        self.requests.append((payload, copied_headers))
        output = self.handler(payload, copied_headers)
        if inspect.isawaitable(output):
            output = await output
        messages = output if isinstance(output, list) else [output]
        if not all(isinstance(message, dict) for message in messages):
            raise MCPTransportError(
                "In-memory MCP handler must return JSON objects."
            )
        return TransportResult(messages=tuple(messages))


@dataclass(slots=True, kw_only=True)
class StreamableHTTPTransport:
    """A standard-library Streamable HTTP request transport.

    The implementation supports single JSON responses and request-scoped SSE
    responses. It intentionally does not implement long-lived subscription
    streams; those can be added behind the same MCPTransport protocol.
    """

    endpoint: str
    timeout_seconds: float = 30.0
    default_headers: dict[str, str] = field(default_factory=dict)

    async def send(
        self,
        payload: JsonObject,
        headers: Mapping[str, str],
    ) -> TransportResult:
        return await asyncio.to_thread(self._send_sync, payload, headers)

    def _send_sync(
        self,
        payload: JsonObject,
        headers: Mapping[str, str],
    ) -> TransportResult:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        merged_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **self.default_headers,
            **dict(headers),
        }
        http_request = urllib_request.Request(
            self.endpoint,
            data=body,
            headers=merged_headers,
            method="POST",
        )

        try:
            with urllib_request.urlopen(
                http_request,
                timeout=self.timeout_seconds,
            ) as response:
                response_body = response.read()
                content_type = response.headers.get(
                    "Content-Type", "application/octet-stream"
                )
                return TransportResult(
                    messages=_decode_messages(response_body, content_type),
                    status_code=response.status,
                    content_type=content_type,
                    response_headers=dict(response.headers.items()),
                )
        except urllib_error.HTTPError as exc:
            response_body = exc.read()
            content_type = exc.headers.get(
                "Content-Type", "application/octet-stream"
            )
            try:
                messages = _decode_messages(response_body, content_type)
            except MCPTransportError as parse_error:
                raise MCPTransportError(
                    f"MCP HTTP request failed with status {exc.code}."
                ) from parse_error
            return TransportResult(
                messages=messages,
                status_code=exc.code,
                content_type=content_type,
                response_headers=dict(exc.headers.items()),
            )
        except urllib_error.URLError as exc:
            raise MCPTransportError(f"MCP HTTP request failed: {exc.reason}") from exc


def _decode_messages(
    body: bytes,
    content_type: str,
) -> tuple[JsonObject, ...]:
    media_type = content_type.split(";", 1)[0].strip().lower()
    text = body.decode("utf-8")

    if media_type == "application/json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise MCPTransportError("MCP response contains invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise MCPTransportError("MCP JSON response must be one object.")
        return (payload,)

    if media_type == "text/event-stream":
        messages = _parse_sse_messages(text)
        if not messages:
            raise MCPTransportError("MCP SSE response contained no JSON messages.")
        return tuple(messages)

    raise MCPTransportError(
        f"Unsupported MCP response content type {content_type!r}."
    )


def _parse_sse_messages(text: str) -> list[JsonObject]:
    messages: list[JsonObject] = []
    data_lines: list[str] = []

    def flush_event() -> None:
        if not data_lines:
            return
        raw_data = "\n".join(data_lines)
        data_lines.clear()
        try:
            payload = json.loads(raw_data)
        except json.JSONDecodeError as exc:
            raise MCPTransportError("MCP SSE event contains invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise MCPTransportError("Each MCP SSE event must contain one JSON object.")
        messages.append(payload)

    for line in text.splitlines():
        if line == "":
            flush_event()
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            value = line[5:]
            if value.startswith(" "):
                value = value[1:]
            data_lines.append(value)

    flush_event()
    return messages
