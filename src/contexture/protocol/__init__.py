"""The optional MCP wire layer.

Nothing in `contexture.core` imports this package. A project that only declares
context and renders agent surfaces never needs it; it exists for hosts that
also want to speak MCP, either outbound through MCPClient or inbound through
MCPHostPort.
"""

from .client import (
    MCPClient,
    ResourceCatalog,
    ResourceReadOutcome,
    ToolCallOutcome,
    ToolCatalog,
)
from .host import (
    InMemoryHost,
    MCPHostPort,
    ResourceContents,
    ResourceProvider,
    ToolHandler,
    ToolResult,
)
from .messages import (
    ClientInfo,
    JSONRPCRequest,
    JSONRPCResponse,
    MCPRequestFactory,
)
from .transport import InMemoryTransport, MCPTransport, StreamableHTTPTransport

__all__ = [
    "ClientInfo",
    "InMemoryHost",
    "InMemoryTransport",
    "JSONRPCRequest",
    "JSONRPCResponse",
    "MCPClient",
    "MCPHostPort",
    "MCPRequestFactory",
    "MCPTransport",
    "ResourceCatalog",
    "ResourceContents",
    "ResourceProvider",
    "ResourceReadOutcome",
    "StreamableHTTPTransport",
    "ToolCallOutcome",
    "ToolCatalog",
    "ToolHandler",
    "ToolResult",
]
