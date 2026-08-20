"""The object a business application hands to its host.

A project states its context as roles, skills, tools, and resources, and then
says::

    app = ContextureApp(roots=[KubernetesPlatform()])

    if __name__ == "__main__":
        app.run(transport="stdio")

Nothing above that line mentions JSON-RPC, JSON Schema, stdio framing, or any
particular agent runtime. That is the whole claim the framework makes: declare
once, and Claude Code, Codex, and anything else that speaks MCP connect to the
same server.

`ContextureApp` deliberately does not subclass the SDK's `MCPServer`. The
runtime owns roles and disclosure; the SDK owns the wire. Keeping them as two
objects that compose is what lets the domain model stay testable without a
transport, and what keeps an SDK upgrade from reaching into the object model.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from typing import Iterable, Literal, Sequence

from mcp.server.mcpserver import MCPServer

from ..core.constants import PACKAGE_VERSION
from ..core.mcp_interface.prompt import Prompt
from ..core.mcp_interface.resource import Resource
from ..core.model.role import Role
from ..core.disclosure.tree import ContextTree
from . import instructions as instructions_module
from .binding import Dispatch, project

#: The transports this server offers. HTTP+SSE was the 2024-11-05 two-endpoint
#: transport; it was replaced by Streamable HTTP and is deprecated in the
#: revisions this server speaks, so it is not offered. A host that still needs
#: it can put a proxy in front.
Transport = Literal["stdio", "streamable-http"]


@dataclass(slots=True, kw_only=True)
class ContextureApp:
    """A declared capability graph, ready to be served over MCP."""

    roots: Role | Iterable[Role]

    #: What this server puts on the prompt and resource primitives.
    #: Authored, never derived: adding one is a code change and a restart,
    #: which is what keeps these lists from varying under a live
    #: connection — something the protocol forbids in any case.
    surface: Sequence[Prompt | Resource] = ()

    name: str = "contexture"
    version: str = PACKAGE_VERSION
    instructions: str | None = None

    tree: ContextTree = field(init=False)
    dispatch: Dispatch = field(init=False)

    def __post_init__(self) -> None:
        # One Dispatch derives every schema and validates every call, so a
        # card's schema and the check a call is measured against cannot drift.
        self.dispatch = Dispatch()
        self.tree = ContextTree.of(self.roots, schema_of=self.dispatch.schema)

    def build_server(self) -> MCPServer:
        """Build the MCP server with the gateway registered on it."""

        server = MCPServer(
            name=self.name,
            version=self.version,
            instructions=self.instructions
            or instructions_module.build(self.tree),
        )
        project(
            server,
            tree=self.tree,
            dispatch=self.dispatch,
            surface=self.surface,
        )
        return server

    def run(self, transport: Transport = "stdio", **kwargs: object) -> None:
        """Serve the graph. Blocks until the host disconnects."""

        configure_logging()
        self.build_server().run(transport=transport, **kwargs)


def configure_logging(level: int = logging.INFO) -> None:
    """Send every log record to stderr.

    Under stdio the protocol owns stdout exclusively — the specification says a
    server MUST NOT write anything there that is not a valid MCP message — so a
    single stray print or a default handler that happens to target stdout
    corrupts the stream for the whole session. Configuring this in one place
    means a business application never has to remember it.
    """

    root = logging.getLogger()
    for handler in list(root.handlers):
        stream = getattr(handler, "stream", None)
        if stream is None or stream is sys.stdout:
            root.removeHandler(handler)
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root.addHandler(handler)
    root.setLevel(level)


__all__ = ["ContextureApp", "Transport", "configure_logging"]
