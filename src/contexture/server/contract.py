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

from dataclasses import dataclass

from ..core.errors import LookupFailure, NodeNotFoundError

DISCOVER_TOOL = "contexture_discover"
OPEN_TOOL = "contexture_open"
READ_TOOL = "contexture_read"
INVOKE_READ_ONLY_TOOL = "contexture_invoke_read_only"
INVOKE_TOOL = "contexture_invoke"


@dataclass(slots=True, frozen=True, kw_only=True)
class GatewayTool:
    """One entry point, and everything the agent learns about it.

    The description is stated once, here, rather than once on the function and
    again at registration. Two copies of a control's label is how the worse one
    ends up being the one that ships.
    """

    name: str
    description: str
    read_only: bool


#: The whole surface, in registration order. A declaration of any size projects
#: onto exactly this: business capabilities travel inside payloads, never here.
GATEWAY = (
    GatewayTool(
        name=DISCOVER_TOOL,
        read_only=True,
        description=(
            "List the top-level roles this server serves, as short routing "
            "cards. Start here, then open the one that matches the task; its "
            "sub-roles arrive with it, one level at a time, so a large tree "
            "costs only the branch you enter. A role card is a name, a "
            "sentence, and the ref that opens it — instructions and document "
            "content arrive on opening, never here."
        ),
    ),
    GatewayTool(
        name=OPEN_TOOL,
        read_only=True,
        description=(
            "Open one role, skill, tool, or resource by ref. Opening a role "
            "returns its instructions and a card for every skill, tool, "
            "resource and sub-role it holds, each with the ref that opens it "
            "and each tool with the schema needed to call it. Opening a skill "
            "returns its complete procedure, available here and nowhere else. "
            "A tool's card is already complete, so run the tool rather than "
            "opening it. Pass a ref taken from a card; never assemble one."
        ),
    ),
    GatewayTool(
        name=READ_TOOL,
        read_only=True,
        description=(
            "Return the content of one resource, addressed either by the ref "
            "from its card or by the resource's own URI — so a procedure that "
            "names a document the way the document names itself can be "
            "followed literally."
        ),
    ),
    GatewayTool(
        name=INVOKE_READ_ONLY_TOOL,
        read_only=True,
        description=(
            "Run a tool that leaves the world unchanged. Use this for every "
            "tool whose card says read_only: true. The ref and arguments come "
            "from that card. A tool that is not read-only is refused here."
        ),
    ),
    GatewayTool(
        name=INVOKE_TOOL,
        read_only=False,
        description=(
            "Run a tool that changes something. Use this for every tool whose "
            "card says read_only: false. The ref and arguments come from that "
            "card. A read-only tool is refused here, so that a host can tell "
            "the two apart before a human is asked to approve anything."
        ),
    ),
)

#: Every tool this server will ever expose, in the order they are registered.
GATEWAY_TOOLS = tuple(entry.name for entry in GATEWAY)

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

    if reason is LookupFailure.NO_SUCH_URI:
        return (
            f"No resource is published at {ref!r}. Open the role that owns it "
            f"with {OPEN_TOOL}; its resource cards carry both the ref and the "
            "URI."
        )

    if reason is LookupFailure.WRONG_KIND:
        # The kind that was actually found decides the recovery, so name the
        # one call that works rather than offering a menu of three.
        recovery = {
            "tool": (
                f"Run it with {INVOKE_READ_ONLY_TOOL} or {INVOKE_TOOL}, "
                "whichever its card says."
            ),
            "resource": f"Read it with {READ_TOOL}.",
        }.get(failure.kind, f"Open it with {OPEN_TOOL}.")
        return f"{ref} names a {failure.kind}, not a {failure.wanted}. {recovery}"

    # Unreachable while `test_every_lookup_failure_has_a_rendering` passes; an
    # agent must never be handed a bare repr, so this stays as the floor.
    return f"{ref!r} could not be resolved."


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
    "DISCOVER_TOOL",
    "GATEWAY",
    "GATEWAY_TOOLS",
    "GatewayTool",
    "INVOKE_READ_ONLY_TOOL",
    "INVOKE_TOOL",
    "OPEN_TOOL",
    "PREAMBLE",
    "READ_TOOL",
    "REF_RULE",
    "unresolved",
    "wrong_door",
]
