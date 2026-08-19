"""MCP server descriptors: catalog ownership and host-side reference routing."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

from .constants import MCP_PROTOCOL_VERSION
from .context import CompileLevel
from .errors import DuplicateNameError, ModelValidationError, NodeNotFoundError
from .resources import MCPResource
from .tools import MCPTool
from .types import CompiledContext, JsonObject


class ServerConnection(ABC):
    """How a client reaches one MCP server.

    The model states the connection in a transport-neutral shape. Rendering it
    into a specific agent's configuration file belongs to a target adapter,
    which is why this base exposes one polymorphic method instead of letting
    adapters branch on the concrete connection type.
    """

    transport: ClassVar[str]

    @abstractmethod
    def to_client_config(self) -> JsonObject:
        """Return the entry shape shared by the common `mcpServers` JSON files."""


@dataclass(slots=True, frozen=True, kw_only=True)
class StdioConnection(ServerConnection):
    """A server launched as a child process speaking MCP over stdio."""

    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)

    transport: ClassVar[str] = "stdio"

    def __post_init__(self) -> None:
        if not self.command.strip():
            raise ModelValidationError("A stdio connection needs a command.")

    def to_client_config(self) -> JsonObject:
        config: JsonObject = {
            "type": self.transport,
            "command": self.command,
        }
        if self.args:
            config["args"] = list(self.args)
        if self.env:
            config["env"] = dict(self.env)
        return config


@dataclass(slots=True, frozen=True, kw_only=True)
class HTTPConnection(ServerConnection):
    """A server reached over Streamable HTTP."""

    url: str
    headers: dict[str, str] = field(default_factory=dict)

    transport: ClassVar[str] = "http"

    def __post_init__(self) -> None:
        if not self.url.strip():
            raise ModelValidationError("An HTTP connection needs a URL.")

    def to_client_config(self) -> JsonObject:
        config: JsonObject = {
            "type": self.transport,
            "url": self.url,
        }
        if self.headers:
            config["headers"] = dict(self.headers)
        return config


@dataclass(slots=True, kw_only=True)
class MCPServer:
    """A host-side descriptor for one MCP capability provider.

    The server is infrastructure, not an LLM-selectable ContextNode. The LLM
    selects tools and resources. The host uses server_id to route the selection
    to the correct client, and target adapters use `connection` to write the
    agent's own MCP configuration.
    """

    server_id: str
    name: str
    description: str
    tools: list[MCPTool] = field(default_factory=list)
    resources: list[MCPResource] = field(default_factory=list)
    connection: ServerConnection | None = None
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
        return self._parse_ref(tool_ref, "Tool", "tool name")

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
        return self._parse_ref(resource_ref, "Resource", "URI")

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

    def _parse_ref(self, ref: str, label: str, remainder_label: str) -> str:
        """Strip this server's prefix, splitting on the first separator only.

        Server ids may not contain '/', which is what lets a resource URI keep
        its own scheme and slashes in the remainder.
        """

        prefix = f"{self.server_id}/"
        if not ref.startswith(prefix):
            raise NodeNotFoundError(
                f"{label} reference {ref!r} does not belong to server "
                f"{self.server_id!r}."
            )
        remainder = ref[len(prefix) :]
        if not remainder:
            raise NodeNotFoundError(
                f"{label} reference {ref!r} has no {remainder_label}."
            )
        return remainder
