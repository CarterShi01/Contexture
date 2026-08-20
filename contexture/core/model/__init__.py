"""The object model: what a capability *is*, before anything can reach it.

Four kinds of node, one disclosure lifecycle, and no idea that any of it will
be served over a protocol. Nothing here knows what a reference looks like, what
JSON Schema is, or that MCP exists. A node cannot *work out* where it hangs —
it is told, by the `ControllerManager` that registered it, in segments rather
than in an address, because how an address is spelled stays with `disclosure`.

A business subclasses these and states what each one is in its constructor,
which hands that identity to the base and builds whatever the node holds.
Nothing is inferred from a class name or a docstring, and nothing is built when
a declaration is imported: a class is a zero-argument factory, and a
`ControllerManager` is the one place every node comes into existence.
"""

from .manager import ControllerManager
from .node import CompileLevel, ContextNode
from .role import Role
from .skill import Skill
from .tool import Tool

__all__ = [
    "CompileLevel",
    "ContextNode",
    "ControllerManager",
    "Role",
    "Skill",
    "Tool",
]
