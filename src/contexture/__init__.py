"""Contexture — a context framework for agents.

An application declares its roles, skills, tools, and resources once against
this object model. Contexture then serves that declaration as a native MCP
server, which any number of agent runtimes connect to.

It does not run an agent loop, choose tools, or talk to a model. Those belong
to the runtime that connects.

The package is layered, and the layering is the architecture:

    contexture.core        the object model; no I/O, no wire, no SDK
    contexture.compiler    route/active disclosure of one node
    contexture.discovery   refs, the capability graph, discover / get_context
    contexture.server      the native MCP server; the only layer importing mcp

    contexture.targets     rendered context files, for runtimes that cannot
                           connect
    contexture.protocol    the outbound half: calling somebody else's server
    contexture.execution   authorization and dispatch for outbound calls

Each layer may import the ones below it and never the reverse. Importing this
facade does not load the server layer or the SDK; `contexture.server` is an
explicit import, so a project that only models context pays for only that.
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
    Resource,
    Role,
    RoleRegistry,
    ServerConnection,
    Skill,
    StdioConnection,
    TargetRenderError,
    Tool,
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
    "Resource",
    "Role",
    "RoleCompiler",
    "RoleRegistry",
    "ServerConnection",
    "Skill",
    "StdioConnection",
    "TargetRenderError",
    "Tool",
    "ToolAnnotations",
    "__version__",
]
