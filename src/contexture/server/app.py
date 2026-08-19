"""The object a business application hands to its host.

A project states its context as roles, skills, tools, and resources, and then
says::

    app = ContextureApp(roots=[KubernetesIncidentResponder()])

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
from typing import Iterable, Literal

from mcp.server.mcpserver import MCPServer

from ..core.constants import PACKAGE_VERSION
from ..core.role import Role
from ..discovery import CapabilityGraph, DisclosureEngine, build_graph
from . import instructions as instructions_module
from .projection import Projection, project

Transport = Literal["stdio", "streamable-http", "sse"]


@dataclass(slots=True, kw_only=True)
class ContextureApp:
    """A declared capability graph, ready to be served over MCP."""

    roots: Role | Iterable[Role]
    name: str = "contexture"
    version: str = PACKAGE_VERSION
    instructions: str | None = None

    graph: CapabilityGraph = field(init=False)
    engine: DisclosureEngine = field(init=False)

    def __post_init__(self) -> None:
        self.graph = build_graph(self.roots)
        self.engine = DisclosureEngine(graph=self.graph)

    def build_server(self) -> tuple[MCPServer, Projection]:
        """Build the MCP server and report what was projected onto it."""

        server = MCPServer(
            name=self.name,
            version=self.version,
            instructions=self.instructions
            or instructions_module.build(self.graph.roots),
        )
        projection = project(server, graph=self.graph, engine=self.engine)
        return server, projection

    def run(self, transport: Transport = "stdio", **kwargs: object) -> None:
        """Serve the graph. Blocks until the host disconnects."""

        configure_logging()
        server, _ = self.build_server()
        server.run(transport=transport, **kwargs)


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
