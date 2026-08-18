"""Progressive role modeling and MCP execution boundaries."""

from .compiler import (
    CapabilitySelection,
    CompileRequest,
    CompiledRoleContext,
    RoleCompiler,
)
from .constants import JSON_RPC_VERSION, MCP_PROTOCOL_VERSION
from .context import CompileLevel, ContextNode
from .data import (
    DataAccess,
    DataBinding,
    DataClassification,
    DataProvider,
    DataReadResult,
    DataSource,
    InMemoryDataProvider,
)
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
    MCPServer,
    MCPTool,
    MCPTransport,
    StreamableHTTPTransport,
    ToolAnnotations,
    ToolCallOutcome,
    ToolCatalog,
)
from .registry import RoleRegistry
from .role import Role
from .runtime import RoleRuntime
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
    "DataAccess",
    "DataBinding",
    "DataClassification",
    "DataProvider",
    "DataReadResult",
    "DataSource",
    "DuplicateNameError",
    "InMemoryDataProvider",
    "InMemoryTransport",
    "JSONRPCRequest",
    "JSONRPCResponse",
    "JSON_RPC_VERSION",
    "MCPBinding",
    "MCPClient",
    "MCPProtocolError",
    "MCPRemoteError",
    "MCPRequestFactory",
    "MCPServer",
    "MCPTool",
    "MCPTransport",
    "MCPTransportError",
    "MCP_PROTOCOL_VERSION",
    "ModelValidationError",
    "NodeNotFoundError",
    "Role",
    "RoleCompiler",
    "RoleRegistry",
    "RoleRuntime",
    "RoleRuntimeError",
    "Skill",
    "StreamableHTTPTransport",
    "ToolAnnotations",
    "ToolCallOutcome",
    "ToolCatalog",
]
