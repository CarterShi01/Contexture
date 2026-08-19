"""Fitting the contract into one host's budget.

What this text *says* is `contexture.server.contract`'s business. What fits is
this module's, and the two are separated because they change for unrelated
reasons: the contract moves when the navigation model does, these numbers move
when a host ships a release.

Two host limits shape this file, and both are real rather than defensive:

* Claude Code truncates server instructions at 2KB and loads them at session
  start, before any tool schema.
* Codex reads the same field and asks that the first 512 characters be
  self-contained, because that is what it has in hand while deciding whether
  to use the server at all.

The role skeleton is included here rather than left for the first
`contexture_discover` call. It is static, it is small — a role card is a name,
a sentence and a path — and putting it here answers the question a host asks
before it has called anything: *what is this server for?* Without it, a gateway
server presents five tools whose names all begin with `contexture_` and no
sign that any of them lead to Kubernetes. With it, the first call can be the
one that opens the right role.

When a forest is too large for the budget, the roster is cut and says so;
`contexture_discover` is the way to read the rest.
"""

from __future__ import annotations

from ..tree import ContextTree
from .contract import DISCOVER_TOOL, PREAMBLE, REF_RULE

#: Claude Code truncates server instructions at 2KB; leave room for the rest.
ROSTER_BUDGET = 1200


def build(
    tree: ContextTree,
    *,
    preamble: str = PREAMBLE,
    budget: int = ROSTER_BUDGET,
) -> str:
    """Return server instructions: the contract first, the roster second."""

    entries = [
        f"- {ref}: {role.description}" for ref, role in tree.roles_with_refs()
    ]

    roster: list[str] = []
    spent = 0
    for index, entry in enumerate(entries):
        if spent + len(entry) > budget:
            remaining = len(entries) - index
            roster.append(
                f"- ...and {remaining} more role(s); call {DISCOVER_TOOL} "
                "for the full list."
            )
            break
        roster.append(entry)
        spent += len(entry) + 1

    return "\n".join(
        [
            preamble.strip(),
            "",
            "Roles:",
            *roster,
            "",
            REF_RULE,
        ]
    )


__all__ = ["ROSTER_BUDGET", "build"]
