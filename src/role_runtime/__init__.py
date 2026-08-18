"""Progressive role modeling and MCP execution boundaries."""

from .compiler import (
    CapabilitySelection,
    CompileRequest,
    CompiledRoleContext,
    RoleCompiler,
)
from .constants import JSON_RPC_VERSION, MCP_PROTOCOL_VERSION
from .context import CompileLevel, ContextNode
from .errors import (
    CapabilityDeniedError,
    ConfirmationRequired,
    DuplicateNameError,
    MCPProtocolError,
    MCPRemoteError,
    MCPTransportError,
    ModelValidationError,
    NodeNotFoundError,
    RoleRuntimeError,
)
from .mcp import (
    ClientInfo,
    InMemoryTransport,
    JSONRPCRequest,
    JSONRPCResponse,
    MCPBinding,
    MCPClient,
    MCPRequestFactory,
    MCPResource,
    MCPServer,
    MCPTool,
    MCPTransport,
    ResourceCatalog,
    ResourceReadOutcome,
    StreamableHTTPTransport,
    ToolAnnotations,
    ToolCallOutcome,
    ToolCatalog,
)
from .registry import RoleRegistry
from .role import Role
from .runtime import RoleRuntime, ServerCatalogRefresh
from .skill import Skill

__all__ = [
    "CapabilityDeniedError",
    "CapabilitySelection",
    "ClientInfo",
    "CompileLevel",
    "CompileRequest",
    "CompiledRoleContext",
    "ConfirmationRequired",
    "ContextNode",
    "DuplicateNameError",
    "InMemoryTransport",
    "JSONRPCRequest",
    "JSONRPCResponse",
    "JSON_RPC_VERSION",
    "MCPBinding",
    "MCPClient",
    "MCPProtocolError",
    "MCPRemoteError",
    "MCPRequestFactory",
    "MCPResource",
    "MCPServer",
    "MCPTool",
    "MCPTransport",
    "MCPTransportError",
    "MCP_PROTOCOL_VERSION",
    "ModelValidationError",
    "NodeNotFoundError",
    "ResourceCatalog",
    "ResourceReadOutcome",
    "Role",
    "RoleCompiler",
    "RoleRegistry",
    "RoleRuntime",
    "RoleRuntimeError",
    "ServerCatalogRefresh",
    "Skill",
    "StreamableHTTPTransport",
    "ToolAnnotations",
    "ToolCallOutcome",
    "ToolCatalog",
]
