"""The bootstrap text a connecting host reads before anything else.

Two host limits shape this file, and both are real rather than defensive:

* Claude Code truncates server instructions at 2KB and loads them at session
  start, before any tool schema.
* Codex reads the same field and asks that the first 512 characters be
  self-contained, because that is what it has in hand while deciding whether
  to use the server at all.

So the opening sentences must be the whole contract. Everything after them is
elaboration a host may never show.
"""

from __future__ import annotations

from typing import Iterable

from ..core.role import Role

#: The self-contained opening. Keep this under 512 characters.
PREAMBLE = """\
Start with contexture_discover to find the role and skill for this task.
Load detail only for the capability you selected, using contexture_get_context.
Collect evidence with the tools before stating a diagnosis or a cause.
Do not assert system state you have not read from a tool or a resource.\
"""


def build(roots: Iterable[Role], *, preamble: str = PREAMBLE) -> str:
    """Return server instructions: the contract first, the roster second."""

    lines = [preamble.strip(), "", "Available roles:"]
    for root in roots:
        lines.append(f"- {root.name}: {root.description}")
    lines.append("")
    lines.append(
        "Every routing card carries a `ref`. Pass it back to "
        "contexture_get_context to open that node."
    )
    return "\n".join(lines)


__all__ = ["PREAMBLE", "build"]
