"""Host-side orchestration for compilation, MCP execution, and data access."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .compiler import CompileRequest, CompiledRoleContext, RoleCompiler
from .data import DataProvider, DataReadResult
from .errors import (
    ConfirmationRequired,
    ModelValidationError,
    NodeNotFoundError,
)
from .mcp.client import MCPClient, ToolCallOutcome, ToolCatalog
from .mcp.models import MCPServer
from .registry import RoleRegistry
from .role import Role


@dataclass(slots=True, kw_only=True)
class RoleRuntime:
    """The host boundary that enforces bindings again at execution time."""

    root_role: Role
    mcp_clients: dict[str, MCPClient] = field(default_factory=dict)
    data_providers: dict[str, DataProvider] = field(default_factory=dict)
    compiler: RoleCompiler = field(default_factory=RoleCompiler)

    registry: RoleRegistry = field(init=False)
    _servers: dict[str, MCPServer] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.registry = RoleRegistry(root=self.root_role)
        self._servers = self._index_servers()

    def compile(
        self,
        role_path: str,
        request: CompileRequest | None = None,
    ) -> CompiledRoleContext:
        role = self.registry.resolve(role_path)
        return self.compiler.compile(role, request)

    async def call_tool(
        self,
        role_path: str,
        tool_ref: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        approved: bool = False,
    ) -> ToolCallOutcome:
        """Execute a granted tool after a second host-side authorization check."""

        role = self.registry.resolve(role_path)
        binding = role.get_mcp_binding_for_tool_ref(tool_ref)
        tool = binding.require_tool_ref(tool_ref)

        if not binding.is_tool_read_only(tool.name) and not approved:
            raise ConfirmationRequired(
                f"Tool {tool_ref!r} is not host-classified as read-only and "
                "requires explicit approval."
            )

        client = self.mcp_clients.get(binding.server.server_id)
        if client is None:
            raise NodeNotFoundError(
                f"No MCP client is registered for server "
                f"{binding.server.server_id!r}."
            )
        return await client.call_tool(tool, arguments)

    async def read_data(
        self,
        role_path: str,
        source_ref: str,
    ) -> DataReadResult:
        role = self.registry.resolve(role_path)
        binding = role.get_data_binding(source_ref)
        binding.require_read()
        provider = self.data_providers.get(binding.source.provider_id)
        if provider is None:
            raise NodeNotFoundError(
                f"No data provider is registered with id "
                f"{binding.source.provider_id!r}."
            )
        return await provider.read(binding.source)

    async def write_data(
        self,
        role_path: str,
        source_ref: str,
        value: Any,
        *,
        approved: bool = False,
    ) -> None:
        role = self.registry.resolve(role_path)
        binding = role.get_data_binding(source_ref)
        binding.require_write()
        if not approved:
            raise ConfirmationRequired(
                f"Writing data source {source_ref!r} requires explicit approval."
            )
        provider = self.data_providers.get(binding.source.provider_id)
        if provider is None:
            raise NodeNotFoundError(
                f"No data provider is registered with id "
                f"{binding.source.provider_id!r}."
            )
        await provider.write(binding.source, value)

    async def refresh_server_catalog(self, server_id: str) -> ToolCatalog:
        """Discover a new tool catalog without silently breaking role grants."""

        server = self.get_server(server_id)
        client = self.mcp_clients.get(server_id)
        if client is None:
            raise NodeNotFoundError(
                f"No MCP client is registered for server {server_id!r}."
            )

        catalog = await client.list_tools()
        discovered_names = {tool.name for tool in catalog.tools}
        granted_names = {
            tool_name
            for _, role in self.registry.iter_roles()
            for binding in role.mcp_bindings
            if binding.server.server_id == server_id
            for tool_name in binding.allowed_tools
        }
        missing_grants = sorted(granted_names - discovered_names)
        if missing_grants:
            raise ModelValidationError(
                f"Refreshed server catalog {server_id!r} is missing tools that "
                f"existing role bindings grant: {missing_grants}."
            )

        server.replace_tools(list(catalog.tools))
        return catalog

    def get_server(self, server_id: str) -> MCPServer:
        try:
            return self._servers[server_id]
        except KeyError as exc:
            raise NodeNotFoundError(
                f"MCP server {server_id!r} is not referenced by this role tree."
            ) from exc

    def _index_servers(self) -> dict[str, MCPServer]:
        indexed: dict[str, MCPServer] = {}
        for _, role in self.registry.iter_roles():
            for binding in role.mcp_bindings:
                server = binding.server
                existing = indexed.get(server.server_id)
                if existing is not None and existing is not server:
                    raise ModelValidationError(
                        f"Server id {server.server_id!r} is associated with "
                        "multiple MCPServer objects. Reuse one shared object."
                    )
                indexed[server.server_id] = server
        return indexed
