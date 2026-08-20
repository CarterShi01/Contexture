"""What this server exposes on MCP's **tool** primitive.

Tools are the model-controlled primitive: the model decides when one is called.
Everything in `core.model` reaches an agent through this one primitive, and it
reaches it through a fixed gateway rather than by being listed.

**Business capabilities are not on the surface.** Tool lists are flat and,
since the 2026-07-28 revision, stateless: a server may not vary them per
connection or as a consequence of an earlier call. So a capability that is
registered is one every session pays for, forever, whatever the user asked.
The only way a capability becomes deferrable is for it not to be listed at
all — its name, description and schema travel inside a payload and arrive
when the role holding it is opened.

Declaration only. Nothing here imports the SDK, builds an annotation, or knows
how a tool is invoked; `server` does all of that. What lives here is the answer
to one question — *what does this server put on the tool primitive?* — and the
answer is these four, whatever the declaration contains.
"""

from __future__ import annotations

from dataclasses import dataclass

DISCOVER_TOOL = "contexture_discover"
OPEN_TOOL = "contexture_open"
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
            "List the top-level capabilities this server serves, as short "
            "routing cards. Most are roles: open the one that matches the task; its "
            "sub-roles arrive with it, one level at a time, so a large tree "
            "costs only the branch you enter. A role card is a name, a "
            "sentence, and the ref that opens it — instructions and what a "
            "role holds arrive on opening, never here."
        ),
    ),
    GatewayTool(
        name=OPEN_TOOL,
        read_only=True,
        description=(
            "Open one role, skill or tool by ref. Opening a role "
            "returns its instructions and a card for every skill, tool "
            "and sub-role it holds, each with the ref that opens it "
            "and each tool with the schema needed to call it. Opening a skill "
            "returns its complete procedure, available here and nowhere else. "
            "A tool's card is already complete, so run the tool rather than "
            "opening it. Pass a ref taken from a card; never assemble one."
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

__all__ = [
    "DISCOVER_TOOL",
    "GATEWAY",
    "GATEWAY_TOOLS",
    "GatewayTool",
    "INVOKE_READ_ONLY_TOOL",
    "INVOKE_TOOL",
    "OPEN_TOOL",
]
