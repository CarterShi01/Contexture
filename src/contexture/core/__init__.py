"""The Contexture object model.

This layer is pure declaration: no I/O, no wire protocol, no agent runtime, and
no knowledge that MCP exists. It owns what a role is, what it declares, and how
much of that becomes visible at each disclosure level. Everything above it — the
tree, the server, the target adapters — depends on this package, and this
package depends on none of them.
"""

from .context import CompileLevel, ContextNode, Opener
from .errors import (
    ContextureError,
    DeclarationError,
    DuplicateNameError,
    ModelValidationError,
    NodeNotFoundError,
)
from .resources import Resource
from .role import Role
from .skill import Skill
from .tools import Tool

__all__ = [
    "CompileLevel",
    "ContextNode",
    "ContextureError",
    "DeclarationError",
    "DuplicateNameError",
    "ModelValidationError",
    "NodeNotFoundError",
    "Opener",
    "Resource",
    "Role",
    "Skill",
    "Tool",
]
