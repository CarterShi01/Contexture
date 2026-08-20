"""Everything a connected agent reads, and the only place it is written.

The tree is a data structure; the SDK is a wire. Neither of them is talking to
anybody. This module is: it holds the gateway's vocabulary, the bootstrap
contract, the description on each entry point, and the sentence an agent gets
when a reference does not resolve.

Collecting it here is not tidiness. **The best version of several of these
sentences cannot be written anywhere else.** When a lookup fails inside
`contexture.tree`, the useful half of the reply is "call `contexture_open` on
the role you came from to see what it holds" — and the tree does not know the
gateway tool names, and must not. So the failure travels as facts and is
rendered here, where the vocabulary is.

Three things share the `server` package and change at three different rates.
This is the slowest of them: it moves when the way an agent is taught to walk
the tree changes. `instructions` fits this text into one host's budget and
moves when a host ships. `projection` hangs it on the SDK and moves when the
SDK does.
"""

from __future__ import annotations

from ..core.errors import LookupFailure, NodeNotFoundError

# Imported for the sentences below, not re-exported. The five entry points are
# declared in `core.mcp_interface.tool` — what this server exposes on a
# primitive is a fact about the surface, not about the wording. What lives here
# is everything said *to* somebody: an agent that took a wrong turn, or a
# person reading a command.
from ..core.mcp_interface.tool import (
    DISCOVER_TOOL,
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
Everything this server offers is behind {OPEN_TOOL}. Start from the roles
below: open the one that fits the task to see its skills, tools, resources
and sub-roles, then open the skill you chose for its procedure. Each call
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


def unresolved(failure: NodeNotFoundError) -> str:
    """Render a failed lookup as something an agent can act on.

    Every branch ends by naming the call that recovers from it. A wrong ref is
    a routine, correctable mistake, and the reply is worth spending words on:
    the agent reads it and picks again, so a sentence that only says what went
    wrong has done half the job.
    """

    reason = failure.reason
    ref = failure.ref
    known = ", ".join(failure.known)

    if reason is LookupFailure.EMPTY_REF:
        return (
            "A reference must name at least a root role. Call "
            f"{DISCOVER_TOOL} for the roles this server serves."
        )

    if reason is LookupFailure.NO_SUCH_ROOT:
        return (
            f"No root role named {failure.scope!r}. This server serves: "
            f"{known}. Call {DISCOVER_TOOL} for their cards, then open one to "
            "reach what is beneath it."
        )

    if reason is LookupFailure.NOT_A_CONTAINER:
        return (
            f"Reference {ref!r} continues past {failure.scope!r}, which is a "
            f"{failure.kind} and holds nothing. Open {failure.scope!r} itself "
            f"with {OPEN_TOOL}, or go back to the card the ref came from."
        )

    if reason is LookupFailure.NO_SUCH_MEMBER:
        holds = f"It holds: {known}." if failure.known else "It holds nothing."
        return (
            f"Role {failure.scope!r} holds no member named "
            f"{failure.segment!r}. {holds} Call {OPEN_TOOL} on "
            f"{failure.scope!r} to see each member with the ref that opens it."
        )

    if reason is LookupFailure.WRONG_KIND:
        # The kind that was actually found decides the recovery, so name the
        # one call that works rather than offering a menu of three.
        recovery = {
            "tool": (
                f"Run it with {INVOKE_READ_ONLY_TOOL} or {INVOKE_TOOL}, "
                "whichever its card says."
            ),
        }.get(failure.kind, f"Open it with {OPEN_TOOL}.")
        return f"{ref} names a {failure.kind}, not a {failure.wanted}. {recovery}"

    # Unreachable while `test_every_lookup_failure_has_a_rendering` passes; an
    # agent must never be handed a bare repr, so this stays as the floor.
    return f"{ref!r} could not be resolved."


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


def command_taken_by_a_person(ref: str) -> str:
    """Refuse a model the door that was reserved for a person.

    Named after `wrong_door`, and for the same reason: the reply names what
    does work. Here that is a command rather than another tool, so the agent's
    correct next move is to say so rather than to try again.

    The node keeps its card, so this is reached by a model that has seen the
    capability and chosen it. Refusing without naming the command would leave
    it to guess whether the thing is broken, forbidden, or merely elsewhere.
    """

    return (
        f"{ref} is opened by a person, not by an agent. It is reachable only "
        "as a command in this host's menu. Do not reproduce its steps another "
        "way; tell the user which command runs it and let them decide when."
    )


def wrong_door(ref: str, *, is_read_only: bool) -> str:
    """Render a call that came through the entry point it does not belong to.

    The host decided whether to involve a human from the hint on the entry
    point, so a mismatch is refused rather than honoured. The reply names the
    other door, because this is a mistake the agent can fix on the next call.
    """

    correct = INVOKE_READ_ONLY_TOOL if is_read_only else INVOKE_TOOL
    stated = "read-only" if is_read_only else "not read-only"
    return f"{ref} is {stated}, so it must be run through {correct}."


__all__ = [
    "COMMAND_CLOSING",
    "COMPLETION_LIMIT",
    "COMMAND_PREAMBLE",
    "GOTO_ARGUMENT",
    "GOTO_ARGUMENT_DESCRIPTION",
    "GOTO_DESCRIPTION",
    "GOTO_PROMPT",
    "SIGNPOST_PREAMBLE",
    "command_description",
    "command_taken_by_a_person",
    "signpost",
    "truncated_completion",
    "PREAMBLE",
    "REF_RULE",
    "unresolved",
    "wrong_door",
]
