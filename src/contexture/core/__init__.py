"""The Contexture object model.

This layer is pure declaration: no I/O, no wire protocol, no agent runtime. It
owns what a role is, what it may reach, and how much of that becomes visible at
each disclosure level. Everything above it — the compiler, the target adapters,
the optional MCP protocol and execution layers — depends on this package, and
this package depends on none of them.
"""

from .binding import MCPBinding
from .constants import JSON_RPC_VERSION, MCP_PROTOCOL_VERSION
from .context import CompileLevel, ContextNode
from .errors import (
    CapabilityDeniedError,
    ConfirmationRequired,
    ContextureError,
    DeclarationError,
    DuplicateNameError,
    MCPProtocolError,
    MCPRemoteError,
    MCPTransportError,
    ModelValidationError,
    NodeNotFoundError,
    TargetRenderError,
)
from .registry import RoleRegistry
from .resources import MCPResource, Resource
from .role import Role
from .servers import HTTPConnection, MCPServer, ServerConnection, StdioConnection
from .skill import Skill
from .tools import MCPTool, Tool, ToolAnnotations

__all__ = [
    "CapabilityDeniedError",
    "CompileLevel",
    "ConfirmationRequired",
    "ContextNode",
    "ContextureError",
    "DeclarationError",
    "DuplicateNameError",
    "HTTPConnection",
    "JSON_RPC_VERSION",
    "MCPBinding",
    "MCPProtocolError",
    "MCPRemoteError",
    "MCPResource",
    "MCPServer",
    "MCPTool",
    "MCPTransportError",
    "MCP_PROTOCOL_VERSION",
    "ModelValidationError",
    "NodeNotFoundError",
    "Resource",
    "Role",
    "RoleRegistry",
    "ServerConnection",
    "Skill",
    "StdioConnection",
    "TargetRenderError",
    "Tool",
    "ToolAnnotations",
]
