"""MCP resource descriptors: the readable half of a server's catalog."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping

from .coercion import optional_str
from .context import ContextNode
from .errors import ModelValidationError
from .types import CompiledContext, JsonObject


@dataclass(slots=True, kw_only=True)
class MCPResource(ContextNode):
    """A protocol-compatible description of one readable MCP resource.

    A resource is a descriptor, never the content itself. Compiling a resource
    at any level yields metadata only; the bytes are fetched through
    resources/read after the execution layer authorizes the access.
    """

    uri: str
    title: str | None = None
    mime_type: str | None = None
    size: int | None = None
    meta: JsonObject = field(default_factory=dict)

    kind: ClassVar[str] = "mcp_resource"

    def __post_init__(self) -> None:
        ContextNode.__post_init__(self)
        if not self.uri.strip():
            raise ModelValidationError(
                f"MCP resource {self.name!r} must have a non-empty URI."
            )
        if self.size is not None and (
            isinstance(self.size, bool) or self.size < 0
        ):
            raise ModelValidationError(
                f"MCP resource {self.name!r} size must be a non-negative integer."
            )

    @property
    def display_name(self) -> str:
        return self.title or self.name

    def _compile_active(self) -> CompiledContext:
        compiled: CompiledContext = {
            **self._compile_route(),
            "uri": self.uri,
        }
        if self.title is not None:
            compiled["title"] = self.title
        if self.mime_type is not None:
            compiled["mimeType"] = self.mime_type
        if self.size is not None:
            compiled["size"] = self.size
        if self.meta:
            compiled["_meta"] = deepcopy(self.meta)
        return compiled

    def to_protocol_dict(self) -> JsonObject:
        """Return the protocol Resource shape without host-only routing fields."""

        payload: JsonObject = {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
        }
        if self.title is not None:
            payload["title"] = self.title
        if self.mime_type is not None:
            payload["mimeType"] = self.mime_type
        if self.size is not None:
            payload["size"] = self.size
        if self.meta:
            payload["_meta"] = deepcopy(self.meta)
        return payload

    @classmethod
    def from_protocol_dict(cls, payload: Mapping[str, Any]) -> MCPResource:
        uri = payload.get("uri")
        if not isinstance(uri, str) or not uri:
            raise ModelValidationError(
                "MCP Resource payload must contain a non-empty uri."
            )

        name = payload.get("name")
        if not isinstance(name, str) or not name:
            raise ModelValidationError(
                f"MCP resource {uri!r} must contain a non-empty name."
            )

        raw_size = payload.get("size")
        if raw_size is not None and (
            isinstance(raw_size, bool) or not isinstance(raw_size, int)
        ):
            raise ModelValidationError(
                f"MCP resource {uri!r} size must be an integer when present."
            )

        raw_meta = payload.get("_meta", {})
        if not isinstance(raw_meta, dict):
            raise ModelValidationError(
                f"MCP resource {uri!r} _meta must be an object when present."
            )

        description = payload.get("description")
        if not isinstance(description, str) or not description.strip():
            description = f"Read the MCP resource addressed by {uri}."

        return cls(
            name=name,
            description=description,
            uri=uri,
            title=optional_str(payload.get("title")),
            mime_type=optional_str(payload.get("mimeType")),
            size=raw_size,
            meta=deepcopy(raw_meta),
        )
