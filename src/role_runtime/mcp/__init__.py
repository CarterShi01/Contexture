"""MCP descriptors, bindings, protocol messages, clients, and transports."""

from .binding import MCPBinding
from .client import MCPClient, ToolCallOutcome, ToolCatalog
from .models import MCPServer, MCPTool, ToolAnnotations
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
    "MCPServer",
    "MCPTool",
    "MCPTransport",
    "StreamableHTTPTransport",
    "ToolAnnotations",
    "ToolCallOutcome",
    "ToolCatalog",
]
