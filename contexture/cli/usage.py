"""The one failure this layer raises.

A module of its own, for the reason `core/types.py` and `core/constants.py`
are: all three of `scaffold`, `project` and `main` stand on it, and it stands
on nothing. Putting it in any one of them would make the other two import a
sibling to raise an error.

It is not a `core` exception. `core` describes what a capability is and has no
notion of a command line, an argument, or a mistake made while typing one.
"""

from __future__ import annotations

from ..core.errors import ContextureError


class UsageError(ContextureError):
    """Raised for a mistake in how the command was invoked."""


__all__ = ["UsageError"]
