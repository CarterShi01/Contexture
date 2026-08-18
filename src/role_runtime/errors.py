"""Domain-specific exceptions for the role runtime."""

from __future__ import annotations

from typing import Any


class RoleRuntimeError(Exception):
    """Base exception for the package."""


class ModelValidationError(RoleRuntimeError, ValueError):
    """Raised when a role-model object violates a structural invariant."""


class DuplicateNameError(ModelValidationError):
    """Raised when names that must be unique collide in one scope."""


class NodeNotFoundError(RoleRuntimeError, KeyError):
    """Raised when a role or capability cannot be resolved."""


class CapabilityDeniedError(RoleRuntimeError, PermissionError):
    """Raised when a role attempts to use a capability it was not granted."""


class ConfirmationRequired(RoleRuntimeError, PermissionError):
    """Raised when an operation needs explicit approval before execution."""


class MCPProtocolError(RoleRuntimeError):
    """Raised when an MCP or JSON-RPC message is structurally invalid."""


class MCPTransportError(RoleRuntimeError):
    """Raised when the underlying MCP transport fails."""


class MCPRemoteError(RoleRuntimeError):
    """Raised for a JSON-RPC error response returned by an MCP server."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"MCP remote error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data
