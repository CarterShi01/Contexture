"""What this host is told, and what a person reading a command is told.

The tree is a data structure; the SDK is a wire. Neither of them is talking to
anybody. This module is — but only on the two planes that belong to `server`.

**What one call answers with, refusals included, is no longer here.** Since
ADR 014 the four entry points are the kernel's, so the sentence a failed lookup
becomes is written beside the call that produces it, in
`core.model.system_api`. That module can name the call which recovers from a
wrong ref — the half of the reply worth having — and being unable to name it
from here was the reason this module was given the job in the first place.

What is left is everything that is *not* one call's answer:

    the opening      what a host loads before calling anything
    the person's     what a command says, and what `goto` offers

Both stay because both are shaped by their audience rather than by the model:
the opening is fitted to a host's byte budget by `instructions`, which moves
when a host ships, and a command is read by a person choosing from a menu.
"""

from __future__ import annotations

# Imported for the sentences below, not re-exported. Which names occupy the
# tool primitive is declared in `core.mcp_interface.tool`, and what they do is
# in `core.model.system_api`; both take the strings from the same shared
# ground, so nothing below can come to name an entry point that does not exist.
from ..core.constants import (
    INVOKE_READ_ONLY_TOOL,
    INVOKE_TOOL,
    OPEN_TOOL,
)


#: The one command every server offers, whatever the declaration marked.
GOTO_PROMPT = "goto"

#: The argument it takes.
GOTO_ARGUMENT = "ref"

#: What `completion/complete` may return in one response, per the protocol.
COMPLETION_LIMIT = 100



#: The self-contained opening. Keep this under 512 characters.
PREAMBLE = f"""\
Everything this server offers is behind {OPEN_TOOL}. Start from the list
below: open the role that fits the task to see its skills, tools and
sub-roles, then open the skill you chose for its procedure. Each call
reveals one level; keep opening down the branch that fits.
Run a tool with {INVOKE_READ_ONLY_TOOL} or {INVOKE_TOOL}, whichever its
card says, passing the ref and arguments from that card.
Collect evidence before stating a cause; never assert system state you have
not read.\
"""

#: Appended once the roster has been listed.
REF_RULE = (
    f"Every card carries a `ref`. Pass it back to {OPEN_TOOL} to open that "
    "node; never assemble a ref yourself."
)


#: What a person reads in the menu beside `goto`.
#:
#: It is the only entrance to the nodes nobody marked, and it earns its place
#: on a value the usual test for a command does not cover. Consistent
#: execution and guardrails belong to a declared command; saved typing is
#: weak, and a person who knows the ref can simply say it. What nothing else
#: offers is **seeing what the server holds without spending a model turn** —
#: and unlike a repository, this tree belongs to somebody else and the person
#: may never have laid eyes on it.
GOTO_DESCRIPTION = (
    "Open any capability this server holds, by reference. The reference "
    "completes as you type, so the whole tree can be browsed here without "
    "asking the agent to go and look."
)

#: What a person reads about the argument.
GOTO_ARGUMENT_DESCRIPTION = (
    "A reference such as payments/ledger/settlement. Completes on any part of "
    "the path."
)


def truncated_completion(shown: int, total: int) -> str:
    """Say that a completion list was cut, in the one place it can be said.

    The protocol carries `total` and `hasMore` beside the values for exactly
    this, and a host is free to ignore both. Saying it in a value keeps the
    fact where a person will actually see it.
    """

    return f"... {total - shown} more match; keep typing to narrow."


#: How a command's text opens. The node's own payload follows it.
COMMAND_PREAMBLE = "You are at {ref}, opened by name at a person's request."

#: Introduces the path above a directly-opened node.
SIGNPOST_PREAMBLE = (
    "Signposts for the path above it. These are **not disclosed**: you may "
    f"open one with {OPEN_TOOL}, and until you do you know only that it "
    "exists. Do not assert anything about what any of them holds."
)

#: Closes a command's text, pointing back at the ordinary surface.
COMMAND_CLOSING = (
    f"Continue with {OPEN_TOOL}, {INVOKE_READ_ONLY_TOOL} or "
    f"{INVOKE_TOOL}, using refs taken from what is above. Nothing listed here "
    "was reached by navigating, so nothing beside it has been shown to you."
)


def signpost(levels: tuple[tuple[str, int], ...]) -> str:
    """Render the path above a node as one line per level.

    Reports that siblings exist and how many, never their names. Same shape as
    the roster's truncation line: name the call that restores what was left
    out rather than spending the budget on it.
    """

    if not levels:
        return ""
    lines = [
        f"- {ref}: {count} sub-role(s) here; {OPEN_TOOL} to see them."
        if count
        else f"- {ref}: no sub-roles; {OPEN_TOOL} to see what it holds."
        for ref, count in levels
    ]
    return "\n".join([SIGNPOST_PREAMBLE, *lines])


def command_description(ref: str, description: str) -> str:
    """What a person reads in the command menu before choosing.

    The node's own routing sentence, which is the sentence written for exactly
    this decision, plus where it lives. The ref is worth the characters: two
    branches can hold capabilities that read alike, and the menu is the only
    place a person sees them side by side.
    """

    return f"{description} ({ref})"


__all__ = [
    "COMMAND_CLOSING",
    "COMPLETION_LIMIT",
    "COMMAND_PREAMBLE",
    "GOTO_ARGUMENT",
    "GOTO_ARGUMENT_DESCRIPTION",
    "GOTO_DESCRIPTION",
    "GOTO_PROMPT",
    "PREAMBLE",
    "REF_RULE",
    "SIGNPOST_PREAMBLE",
    "command_description",
    "signpost",
    "truncated_completion",
]
