"""MCP descriptors, bindings, protocol messages, clients, and transports."""

from .binding import MCPBinding
from .client import (
    MCPClient,
    ResourceCatalog,
    ResourceReadOutcome,
    ToolCallOutcome,
    ToolCatalog,
)
from .models import MCPResource, MCPServer, MCPTool, ToolAnnotations
from .protocol import ClientInfo, JSONRPCRequest, JSONRPCResponse, MCPRequestFactory
from .transport import InMemoryTransport, MCPTransport, StreamableHTTPTransport

__all__ = [
    "ClientInfo",
    "InMemoryTransport",
    "JSONRPCRequest",
    "JSONRPCResponse",
    "MCPBinding",
    "MCPClient",
    "MCPRequestFactory",
    "MCPResource",
    "MCPServer",
    "MCPTool",
    "MCPTransport",
    "ResourceCatalog",
    "ResourceReadOutcome",
    "StreamableHTTPTransport",
    "ToolAnnotations",
    "ToolCallOutcome",
    "ToolCatalog",
]
