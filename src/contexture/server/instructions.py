"""The bootstrap text a connecting host reads before anything else.

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

#: The self-contained opening. Keep this under 512 characters.
PREAMBLE = """\
Everything this server offers is behind contexture_open. The roles listed below
are the whole map: open the one that fits the task to see its skills, tools and
resources, then open the skill you chose to get its procedure.
Run a tool with contexture_invoke_read_only or contexture_invoke, whichever its
card says, passing the ref and arguments from that card.
Collect evidence with the tools before stating a cause, and do not assert system
state you have not read.\
"""

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
                f"- ...and {remaining} more role(s); call contexture_discover "
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
            "Every card carries a `ref`. Pass it back to contexture_open to "
            "open that node; never assemble a ref yourself.",
        ]
    )


__all__ = ["PREAMBLE", "ROSTER_BUDGET", "build"]
