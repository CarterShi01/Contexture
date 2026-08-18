"""MCP tool, resource, and server descriptors used by the host object model."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping

from ..constants import MCP_PROTOCOL_VERSION
from ..context import CompileLevel, ContextNode
from ..errors import DuplicateNameError, ModelValidationError, NodeNotFoundError
from ..types import CompiledContext, JsonObject


@dataclass(slots=True, frozen=True, kw_only=True)
class ToolAnnotations:
    """Protocol annotations retained as untrusted behavioral hints.

    These values are never used as the host's authorization source of truth.
    Trusted execution policy belongs to MCPBinding and RoleRuntime.
    """

    title: str | None = None
    read_only_hint: bool | None = None
    destructive_hint: bool | None = None
    idempotent_hint: bool | None = None
    open_world_hint: bool | None = None

    def to_protocol_dict(self) -> JsonObject:
        result: JsonObject = {}
        if self.title is not None:
            result["title"] = self.title
        if self.read_only_hint is not None:
            result["readOnlyHint"] = self.read_only_hint
        if self.destructive_hint is not None:
            result["destructiveHint"] = self.destructive_hint
        if self.idempotent_hint is not None:
            result["idempotentHint"] = self.idempotent_hint
        if self.open_world_hint is not None:
            result["openWorldHint"] = self.open_world_hint
        return result

    @classmethod
    def from_protocol_dict(
        cls,
        payload: Mapping[str, Any] | None,
    ) -> ToolAnnotations | None:
        if payload is None:
            return None
        return cls(
            title=_optional_str(payload.get("title")),
            read_only_hint=_optional_bool(payload.get("readOnlyHint")),
            destructive_hint=_optional_bool(payload.get("destructiveHint")),
            idempotent_hint=_optional_bool(payload.get("idempotentHint")),
            open_world_hint=_optional_bool(payload.get("openWorldHint")),
        )


@dataclass(slots=True, kw_only=True)
class MCPTool(ContextNode):
    """A protocol-compatible description of a callable MCP tool."""

    input_schema: JsonObject
    title: str | None = None
    output_schema: JsonObject | None = None
    annotations: ToolAnnotations | None = None
    meta: JsonObject = field(default_factory=dict)

    kind: ClassVar[str] = "mcp_tool"

    def __post_init__(self) -> None:
        ContextNode.__post_init__(self)
        if self.input_schema.get("type") != "object":
            raise ModelValidationError(
                f"MCP tool {self.name!r} must have inputSchema.type == 'object'."
            )

    @property
    def display_name(self) -> str:
        if self.title:
            return self.title
        if self.annotations and self.annotations.title:
            return self.annotations.title
        return self.name

    def _compile_active(self) -> CompiledContext:
        compiled: CompiledContext = {
            **self._compile_route(),
            "inputSchema": deepcopy(self.input_schema),
        }
        if self.title is not None:
            compiled["title"] = self.title
        if self.output_schema is not None:
            compiled["outputSchema"] = deepcopy(self.output_schema)
        if self.annotations is not None:
            compiled["annotations"] = self.annotations.to_protocol_dict()
        if self.meta:
            compiled["_meta"] = deepcopy(self.meta)
        return compiled

    def to_protocol_dict(self) -> JsonObject:
        """Return the protocol Tool shape without host-only routing fields."""

        payload: JsonObject = {
            "name": self.name,
            "description": self.description,
            "inputSchema": deepcopy(self.input_schema),
        }
        if self.title is not None:
            payload["title"] = self.title
        if self.output_schema is not None:
            payload["outputSchema"] = deepcopy(self.output_schema)
        if self.annotations is not None:
            payload["annotations"] = self.annotations.to_protocol_dict()
        if self.meta:
            payload["_meta"] = deepcopy(self.meta)
        return payload

    @classmethod
    def from_protocol_dict(cls, payload: Mapping[str, Any]) -> MCPTool:
        name = payload.get("name")
        if not isinstance(name, str) or not name:
            raise ModelValidationError("MCP Tool payload must contain a non-empty name.")

        raw_schema = payload.get("inputSchema")
        if not isinstance(raw_schema, dict):
            raise ModelValidationError(
                f"MCP tool {name!r} must contain an object inputSchema."
            )

        raw_output = payload.get("outputSchema")
        if raw_output is not None and not isinstance(raw_output, dict):
            raise ModelValidationError(
                f"MCP tool {name!r} outputSchema must be an object when present."
            )

        raw_annotations = payload.get("annotations")
        if raw_annotations is not None and not isinstance(raw_annotations, dict):
            raise ModelValidationError(
                f"MCP tool {name!r} annotations must be an object when present."
            )

        raw_meta = payload.get("_meta", {})
        if not isinstance(raw_meta, dict):
            raise ModelValidationError(
                f"MCP tool {name!r} _meta must be an object when present."
            )

        description = payload.get("description")
        if not isinstance(description, str) or not description.strip():
            description = f"Invoke the MCP tool named {name}."

        return cls(
            name=name,
            description=description,
            title=_optional_str(payload.get("title")),
            input_schema=deepcopy(raw_schema),
            output_schema=deepcopy(raw_output),
            annotations=ToolAnnotations.from_protocol_dict(raw_annotations),
            meta=deepcopy(raw_meta),
        )


@dataclass(slots=True, kw_only=True)
class MCPResource(ContextNode):
    """A protocol-compatible description of one readable MCP resource.

    A resource is a descriptor, never the content itself. Compiling a resource
    at any level yields metadata only; the bytes are fetched by MCPClient
    through resources/read after RoleRuntime authorizes the access.
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
            title=_optional_str(payload.get("title")),
            mime_type=_optional_str(payload.get("mimeType")),
            size=raw_size,
            meta=deepcopy(raw_meta),
        )


@dataclass(slots=True, kw_only=True)
class MCPServer:
    """A host-side descriptor for one MCP capability provider.

    The server is infrastructure, not an LLM-selectable ContextNode. The LLM
    selects tools and resources. The host uses server_id to route the selection
    to the correct MCP client and transport.
    """

    server_id: str
    name: str
    description: str
    tools: list[MCPTool] = field(default_factory=list)
    resources: list[MCPResource] = field(default_factory=list)
    protocol_version: str = MCP_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if not self.server_id.strip():
            raise ModelValidationError("MCP server id must not be empty.")
        if "/" in self.server_id:
            raise ModelValidationError(
                "MCP server id must not contain '/' because tool_ref and "
                "resource_ref use it as the server delimiter."
            )
        if not self.name.strip():
            raise ModelValidationError("MCP server name must not be empty.")
        if not self.description.strip():
            raise ModelValidationError(
                f"MCP server {self.server_id!r} must have a description."
            )
        self._validate_tools(self.tools)
        self._validate_resources(self.resources)

    @staticmethod
    def _validate_tools(tools: list[MCPTool]) -> None:
        names = [tool.name for tool in tools]
        if len(names) != len(set(names)):
            raise DuplicateNameError(
                "Tool names must be unique inside one MCP server catalog."
            )

    @staticmethod
    def _validate_resources(resources: list[MCPResource]) -> None:
        uris = [resource.uri for resource in resources]
        if len(uris) != len(set(uris)):
            raise DuplicateNameError(
                "Resource URIs must be unique inside one MCP server catalog."
            )

    def replace_tools(self, tools: list[MCPTool]) -> None:
        """Atomically replace the discovered catalog after validation."""

        self._validate_tools(tools)
        self.tools = list(tools)

    def replace_resources(self, resources: list[MCPResource]) -> None:
        """Atomically replace the discovered resource catalog after validation."""

        self._validate_resources(resources)
        self.resources = list(resources)

    def has_tool(self, tool_name: str) -> bool:
        return any(tool.name == tool_name for tool in self.tools)

    def get_tool(self, tool_name: str) -> MCPTool:
        for tool in self.tools:
            if tool.name == tool_name:
                return tool
        raise NodeNotFoundError(
            f"MCP tool {tool_name!r} was not found on server {self.server_id!r}."
        )

    def make_tool_ref(self, tool_name: str) -> str:
        """Create the host-only globally unique reference for a tool."""

        return f"{self.server_id}/{tool_name}"

    def parse_tool_ref(self, tool_ref: str) -> str:
        prefix = f"{self.server_id}/"
        if not tool_ref.startswith(prefix):
            raise NodeNotFoundError(
                f"Tool reference {tool_ref!r} does not belong to server "
                f"{self.server_id!r}."
            )
        tool_name = tool_ref[len(prefix) :]
        if not tool_name:
            raise NodeNotFoundError(f"Tool reference {tool_ref!r} has no tool name.")
        return tool_name

    def compile_tool(
        self,
        tool_name: str,
        level: CompileLevel | str = CompileLevel.ROUTE,
    ) -> CompiledContext:
        tool = self.get_tool(tool_name)
        return {
            **tool.compile(level),
            "server_id": self.server_id,
            "server_name": self.name,
            "tool_ref": self.make_tool_ref(tool.name),
        }

    def compile_tool_routes(self) -> list[CompiledContext]:
        return [
            self.compile_tool(tool.name, CompileLevel.ROUTE)
            for tool in self.tools
        ]

    def has_resource(self, uri: str) -> bool:
        return any(resource.uri == uri for resource in self.resources)

    def get_resource(self, uri: str) -> MCPResource:
        for resource in self.resources:
            if resource.uri == uri:
                return resource
        raise NodeNotFoundError(
            f"MCP resource {uri!r} was not found on server {self.server_id!r}."
        )

    def make_resource_ref(self, uri: str) -> str:
        """Create the host-only globally unique reference for a resource."""

        return f"{self.server_id}/{uri}"

    def parse_resource_ref(self, resource_ref: str) -> str:
        prefix = f"{self.server_id}/"
        if not resource_ref.startswith(prefix):
            raise NodeNotFoundError(
                f"Resource reference {resource_ref!r} does not belong to server "
                f"{self.server_id!r}."
            )
        uri = resource_ref[len(prefix) :]
        if not uri:
            raise NodeNotFoundError(f"Resource reference {resource_ref!r} has no URI.")
        return uri

    def compile_resource(
        self,
        uri: str,
        level: CompileLevel | str = CompileLevel.ROUTE,
    ) -> CompiledContext:
        resource = self.get_resource(uri)
        return {
            **resource.compile(level),
            "server_id": self.server_id,
            "server_name": self.name,
            "resource_ref": self.make_resource_ref(resource.uri),
        }

    def compile_resource_routes(self) -> list[CompiledContext]:
        return [
            self.compile_resource(resource.uri, CompileLevel.ROUTE)
            for resource in self.resources
        ]


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ModelValidationError(f"Expected a string, received {type(value).__name__}.")
    return value


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ModelValidationError(f"Expected a boolean, received {type(value).__name__}.")
    return value
