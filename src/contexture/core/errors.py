"""Domain-specific exceptions for Contexture."""

from __future__ import annotations


class ContextureError(Exception):
    """Base exception for the package."""


class ModelValidationError(ContextureError, ValueError):
    """Raised when a declared object violates a structural invariant."""


class DuplicateNameError(ModelValidationError):
    """Raised when names that must be unique collide in one scope."""


class DeclarationError(ModelValidationError):
    """Raised when a declarative class states something the model cannot accept."""


class NodeNotFoundError(ContextureError, KeyError):
    """Raised when a role or capability cannot be resolved.

    KeyError is kept in the bases so existing `except KeyError` handlers still
    work, but its `__str__` is not: KeyError reprs its argument, which wraps
    every message in quotes. That was cosmetic while these errors stayed inside
    Python. It is not cosmetic now that an unresolvable ref is reported to a
    connected agent, which reads the message and is expected to correct itself.
    """

    def __str__(self) -> str:
        if len(self.args) == 1 and isinstance(self.args[0], str):
            return self.args[0]
        return super(KeyError, self).__str__()


class TargetRenderError(ContextureError):
    """Raised when a target adapter cannot render a role into its surface."""
