"""Where a node sits, and how much of it arrives at a time.

`core.model` says what a capability *is*. It cannot say where it hangs: a node
knows its own name and nothing about its neighbours, and `core.model` does not
know what a separator is. This layer supplies the missing half — it joins
declared objects into a forest, gives every one of them an address, and decides
which of them a single call answers with.

Two things are therefore invented here and exist nowhere below:

    the reference    a path, and a node's only address
    the level        one sibling set per call, never a subtree

Both are the tree's, not the node's. A node compiles itself to ROUTE or ACTIVE
on request; this layer decides *which* nodes are asked, and it is that decision
— not the compiling — that keeps a forest of eleven thousand roles as cheap to
enter as one of three.
"""

from .tree import SEPARATOR, ContextTree

__all__ = ["SEPARATOR", "ContextTree"]
