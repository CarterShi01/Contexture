"""Contexture — a context framework for agents.

An application declares its roles, skills, tools, and resources once against
this object model. Contexture then progressively discloses that declaration and
translates it into the skill and MCP surfaces different agent runtimes consume.

It does not run an agent loop, choose tools, or talk to a model. Those belong
to the runtime that consumes what Contexture produces.

The package is layered, and the layering is the architecture:

    contexture.core        the object model; no I/O, no wire, no targets
    contexture.compiler    route/active disclosure over the model
    contexture.targets     per-agent rendering into artifacts
    contexture.protocol    optional MCP wire layer, outbound and inbound
    contexture.execution   optional authorization and dispatch

Only `core` is mandatory. Each layer above may import the ones below it and
never the reverse.
"""

from .compiler import (
    CapabilitySelection,
    CompileRequest,
    CompiledRoleContext,
    RoleCompiler,
)
from .core.constants import PACKAGE_VERSION as __version__
from .core import (
    CapabilityDeniedError,
    CompileLevel,
    ConfirmationRequired,
    ContextNode,
    ContextureError,
    DeclarationError,
    DuplicateNameError,
    HTTPConnection,
    JSON_RPC_VERSION,
    MCPBinding,
    MCPProtocolError,
    MCPRemoteError,
    MCPResource,
    MCPServer,
    MCPTool,
    MCPTransportError,
    MCP_PROTOCOL_VERSION,
    ModelValidationError,
    NodeNotFoundError,
    Role,
    RoleRegistry,
    ServerConnection,
    Skill,
    StdioConnection,
    TargetRenderError,
    ToolAnnotations,
)

__all__ = [
    "CapabilityDeniedError",
    "CapabilitySelection",
    "CompileLevel",
    "CompileRequest",
    "CompiledRoleContext",
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
    "Role",
    "RoleCompiler",
    "RoleRegistry",
    "ServerConnection",
    "Skill",
    "StdioConnection",
    "TargetRenderError",
    "ToolAnnotations",
    "__version__",
]
