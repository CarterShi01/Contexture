"""Host-side orchestration for compilation and MCP execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .compiler import CompileRequest, CompiledRoleContext, RoleCompiler
from .errors import (
    ConfirmationRequired,
    ModelValidationError,
    NodeNotFoundError,
)
from .mcp.client import (
    MCPClient,
    ResourceCatalog,
    ResourceReadOutcome,
    ToolCallOutcome,
    ToolCatalog,
)
from .mcp.models import MCPServer
from .registry import RoleRegistry
from .role import Role


@dataclass(slots=True, frozen=True, kw_only=True)
class ServerCatalogRefresh:
    """The tool and resource catalogs discovered by one refresh."""

    tools: ToolCatalog
    resources: ResourceCatalog


@dataclass(slots=True, kw_only=True)
class RoleRuntime:
    """The host boundary that enforces bindings again at execution time."""

    root_role: Role
    mcp_clients: dict[str, MCPClient] = field(default_factory=dict)
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

        client = self._require_client(binding.server.server_id)
        return await client.call_tool(tool, arguments)

    async def read_resource(
        self,
        role_path: str,
        resource_ref: str,
    ) -> ResourceReadOutcome:
        """Read a granted resource after a second host-side authorization check.

        No approval gate exists here because MCP resources are read-only at the
        protocol level. The allowlist on MCPBinding is the whole grant.
        """

        role = self.registry.resolve(role_path)
        binding = role.get_mcp_binding_for_resource_ref(resource_ref)
        resource = binding.require_resource_ref(resource_ref)

        client = self._require_client(binding.server.server_id)
        return await client.read_resource(resource)

    async def refresh_server_catalog(self, server_id: str) -> ServerCatalogRefresh:
        """Rediscover one server without silently breaking existing role grants.

        Both catalogs are validated before either is replaced, so a rejected
        resource catalog cannot leave the server holding refreshed tools.
        """

        server = self.get_server(server_id)
        client = self._require_client(server_id)

        tool_catalog = await client.list_tools()
        resource_catalog = await client.list_resources()

        self._require_grants_survive(
            server_id,
            discovered={tool.name for tool in tool_catalog.tools},
            granted=self._granted_names(server_id, "allowed_tools"),
            label="tools",
        )
        self._require_grants_survive(
            server_id,
            discovered={resource.uri for resource in resource_catalog.resources},
            granted=self._granted_names(server_id, "allowed_resources"),
            label="resources",
        )

        server.replace_tools(list(tool_catalog.tools))
        server.replace_resources(list(resource_catalog.resources))
        return ServerCatalogRefresh(tools=tool_catalog, resources=resource_catalog)

    def get_server(self, server_id: str) -> MCPServer:
        try:
            return self._servers[server_id]
        except KeyError as exc:
            raise NodeNotFoundError(
                f"MCP server {server_id!r} is not referenced by this role tree."
            ) from exc

    def _require_client(self, server_id: str) -> MCPClient:
        client = self.mcp_clients.get(server_id)
        if client is None:
            raise NodeNotFoundError(
                f"No MCP client is registered for server {server_id!r}."
            )
        return client

    def _granted_names(self, server_id: str, attribute: str) -> set[str]:
        return {
            name
            for _, role in self.registry.iter_roles()
            for binding in role.mcp_bindings
            if binding.server.server_id == server_id
            for name in getattr(binding, attribute)
        }

    @staticmethod
    def _require_grants_survive(
        server_id: str,
        *,
        discovered: set[str],
        granted: set[str],
        label: str,
    ) -> None:
        missing = sorted(granted - discovered)
        if missing:
            raise ModelValidationError(
                f"Refreshed server catalog {server_id!r} is missing {label} that "
                f"existing role bindings grant: {missing}."
            )

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
