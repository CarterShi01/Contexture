"""Hanging a sealed assembly on the SDK's three primitives, one module each.

    gateway.py     the four entry points a model drives
    prompts.py     what a person triggers by name
    resources.py   what a host may take up on its own

One module per plane, mirroring `core.mcp_interface`, which declares *what*
each primitive carries. This package is *how it gets there*, and it is the only
place in Contexture that writes to an SDK server.

**Three planes, three sets of rules, and that is why they are three objects.**
A business may not add to the tool plane at all; it may add to the other two,
and what makes an addition legal differs completely between them — a prompt
needs a name nothing else in the menu answers to, a resource needs that plus a
node that is read-only and takes no arguments. Those rules used to share one
`if/else` over a mixed list.

**Constructed, then projected.** Each plane validates in its constructor and
writes in `project`, and `ContextureServer.build` constructs all three before it
writes any of them. So a declaration error is raised while the SDK server does
not yet exist, instead of half way through hanging things on one — which is
what used to happen, leaving four gateway tools and some prompts registered on
a server nobody would ever serve. It is also this package's own idiom: a
constructor is where a declaration is checked (ADR 013).

What is checked *here* rather than in `core.model.assembly` is what would stop
being true if MCP were replaced. That a published entry names a node the tree
holds is about addresses and is sealed with the tree; that two entries cannot
share a name is about a flat menu, and that a resource must be read-only and
argument-free is about a primitive that is fetched rather than called. Both of
those are facts about this protocol, so they live beside the code that speaks
it.
"""

from __future__ import annotations

from typing import Any

from ...core.errors import ContextureError
from ...core.model.disclosure import SEPARATOR
from ...core.mcp_interface.prompt import Prompt
from ...core.mcp_interface.resource import Resource

from mcp.server.mcpserver.exceptions import ToolError


def published_name(entry: Prompt | Resource) -> str:
    """The name a host shows, defaulting to the last segment of the ref.

    A second name, independent of position — the same thing a URI has always
    been for a document, now the only kind of second name in the package.
    """

    return entry.name or entry.opens.rsplit(SEPARATOR, 1)[-1]


class translated:
    """Put a Contexture failure on the wire as the protocol's own error.

    One branch, and that is the point: every failure that reaches here already
    carries the sentence its audience needs. A `Refused` was composed by the
    kernel, which is the only layer that knows both what went wrong and the
    name of the call that recovers from it; anything else is a
    declaration-time failure whose audience is whoever wrote the declaration,
    and it carries its own sentence too.

    This used to compose the agent's sentence itself, from facts, because the
    tree could not name the tool that recovers from a wrong ref. Since ADR 014
    it can, and what is left here is the wrapping.
    """

    __slots__ = ()

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        if exc is None or not isinstance(exc, ContextureError):
            return False
        raise ToolError(str(exc)) from exc


from .gateway import Gateway  # noqa: E402
from .prompts import Prompts  # noqa: E402
from .resources import Resources  # noqa: E402

__all__ = ["Gateway", "Prompts", "Resources", "published_name", "translated"]
