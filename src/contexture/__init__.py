"""Contexture — a context framework for agents.

An application declares its roles, skills, tools, and resources once against
this object model. Contexture then serves that declaration as a native MCP
server, which any number of agent runtimes connect to.

It does not run an agent loop, choose tools, or talk to a model. Those belong
to the runtime that connects.

The package is layered, and the layering is the architecture:

    contexture.core        the object model; no I/O, no wire, no SDK
    contexture.tree        the multi-headed tree, disclosed lazily
    contexture.server      the native MCP server; the only layer importing mcp

Each layer may import the ones below it and never the reverse. This facade
exports what a business developer *declares* with, and nothing the framework
*runs* with: importing it loads neither `contexture.tree` nor
`contexture.server` nor the SDK, so a project that only models context pays
for only that.
"""

from .core.constants import PACKAGE_VERSION as __version__
from .core import (
    CompileLevel,
    ContextNode,
    ContextureError,
    DeclarationError,
    DuplicateNameError,
    ModelValidationError,
    NodeNotFoundError,
    Opener,
    Resource,
    Role,
    Skill,
    Tool,
)

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
    "__version__",
]
