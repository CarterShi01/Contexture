"""The object model: what a capability *is*, before anything can reach it.

Four kinds of node, one disclosure lifecycle, and no idea that any of it will
be served over a protocol. Nothing here knows what a reference looks like, what
JSON Schema is, or that MCP exists. A node cannot *work out* where it hangs —
it is told, by the `ControllerManager` that registered it, in segments rather
than in an address, because how an address is spelled stays with `disclosure`.

This is the layer a business developer subclasses. Everything else in the
package exists to organise what is declared here or to put it on a wire.
"""

from .declarative import Declaration
from .manager import ControllerManager
from .node import CompileLevel, ContextNode
from .role import Role
from .skill import Skill
from .tool import Tool

__all__ = [
    "CompileLevel",
    "ContextNode",
    "ControllerManager",
    "Declaration",
    "Role",
    "Skill",
    "Tool",
]
