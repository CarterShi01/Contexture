"""The object model: what a capability *is*, before anything can reach it.

Four kinds of node, one disclosure lifecycle, and no idea that any of it will
be served over a protocol. Nothing here knows what a reference looks like, what
JSON Schema is, or that MCP exists — a node cannot say where it hangs, because
where it hangs is the tree's answer and not its own.

This is the layer a business developer subclasses. Everything else in the
package exists to organise what is declared here or to put it on a wire.
"""

from .declarative import Declaration
from .node import CompileLevel, ContextNode
from .role import Role
from .skill import Skill
from .tool import Tool

__all__ = [
    "CompileLevel",
    "ContextNode",
    "Declaration",
    "Role",
    "Skill",
    "Tool",
]
