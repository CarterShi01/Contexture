"""What this server exposes on MCP's **tool** primitive.

Tools are the model-controlled primitive: the model decides when one is called.
Everything in the object model reaches an agent through this one primitive, and
it reaches it through a fixed system API rather than by being listed.

**This is the one plane a business may not extend, and that is the design.**
On the other two, a declaration adds entries: a `Prompt` names a node a person
may trigger, a `Resource` names one a host may take up. Here it adds none. Tool
lists are flat and, since the 2026-07-28 revision, stateless — a server may not
vary them per connection or as a consequence of an earlier call — so a
capability that is registered is one every session pays for, forever, whatever
the user asked. The only way a capability becomes deferrable is for it not to be
listed at all: its name, description and schema travel inside a payload and
arrive when the role holding it is opened.

So what occupies this plane is the framework's own four entry points, and this
module declares **which** they are and nothing else. Their descriptions and
their behaviour live together in `core.model.system_api`, because since ADR 014
navigation is part of the kernel. The names arrive from the shared ground, so
that naming them here and implementing them there cannot drift into two lists.

Declaration only. Nothing here imports the SDK, builds an annotation, or knows
how a call is dispatched; `server` does all of that.
"""

from __future__ import annotations

from ..constants import (
    DISCOVER_TOOL,
    INVOKE_READ_ONLY_TOOL,
    INVOKE_TOOL,
    OPEN_TOOL,
)

#: Every name on this primitive, in the order they are registered. Four,
#: whatever the declaration contains.
PUBLISHED = (
    DISCOVER_TOOL,
    OPEN_TOOL,
    INVOKE_READ_ONLY_TOOL,
    INVOKE_TOOL,
)

__all__ = [
    "DISCOVER_TOOL",
    "INVOKE_READ_ONLY_TOOL",
    "INVOKE_TOOL",
    "OPEN_TOOL",
    "PUBLISHED",
]
