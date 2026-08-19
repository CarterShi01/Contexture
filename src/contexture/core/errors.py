"""Domain-specific exceptions for Contexture."""

from __future__ import annotations

from typing import Any


class ContextureError(Exception):
    """Base exception for the package."""


class ModelValidationError(ContextureError, ValueError):
    """Raised when a declared object violates a structural invariant."""


class DuplicateNameError(ModelValidationError):
    """Raised when names that must be unique collide in one scope."""


class DeclarationError(ModelValidationError):
    """Raised when a declarative class states something the model cannot accept."""


class NodeNotFoundError(ContextureError, KeyError):
    """Raised when a role or capability cannot be resolved."""


class CapabilityDeniedError(ContextureError, PermissionError):
    """Raised when a role attempts to use a capability it was not granted."""


class ConfirmationRequired(ContextureError, PermissionError):
    """Raised when an operation needs explicit approval before execution."""


class TargetRenderError(ContextureError):
    """Raised when a target adapter cannot render a role into its surface."""


class MCPProtocolError(ContextureError):
    """Raised when an MCP or JSON-RPC message is structurally invalid."""


class MCPTransportError(ContextureError):
    """Raised when the underlying MCP transport fails."""


class MCPRemoteError(ContextureError):
    """Raised for a JSON-RPC error response returned by an MCP server."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"MCP remote error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data
