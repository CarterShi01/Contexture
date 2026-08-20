"""The Contexture object model.

This layer is pure declaration: no I/O, no wire protocol, no agent runtime, and
no knowledge that MCP exists. It owns what a role is, what it declares, and how
much of that becomes visible at each disclosure level. Everything above it
depends on this package, and this package depends on none of them.

Three directories live here, because they answer three different questions:

    model            what a capability *is* — role, skill, tool, resource
    disclosure       where it sits, and how much of it arrives at a time
    mcp_interface    what this server exposes on each of MCP's primitives

`errors`, `types`, `constants` and `principal` sit directly here as shared
ground: all three
directories may stand on them, and they stand on nothing. That is what lets the
three stay independent of *each other* without each growing its own copy of an
exception hierarchy.

This facade re-exports the object model, which is what a business developer
declares against, and resolves each name on first use. Eager re-exports would
make this file import its own sub-layers, which is the one dependency the
shared ground is not allowed to have — and would quietly load `disclosure` for
a project that only wanted to declare a Role.
"""

from __future__ import annotations

import importlib
from typing import Any

#: Exported name -> the submodule that defines it.
_EXPORTS = {
    "ContextureError": ".errors",
    "DeclarationError": ".errors",
    "DuplicateNameError": ".errors",
    "ModelValidationError": ".errors",
    "NodeNotFoundError": ".errors",
    "Principal": ".principal",
    "bound": ".principal",
    "current_principal": ".principal",
    "CompileLevel": ".model",
    "ContextNode": ".model",
    "Role": ".model",
    "Skill": ".model",
    "Tool": ".model",
}


def __getattr__(name: str) -> Any:
    """Resolve an export on first use, then cache it in the module globals."""

    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(__all__)


__all__ = sorted(_EXPORTS)
