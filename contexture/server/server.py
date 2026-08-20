"""The object a business application hands to its host.

A project builds its graph, seals it, and serves it::

    def main() -> None:
        manager = ControllerManager(channels=channels)
        manager.register_role(KubernetesPlatform)

        tree     = manager.sealed(bind=TypeHintBinding)
        assembly = Assembly.of(tree, published=PUBLISHED)

        server = ContextureServer(assembly, name="oc-goal")
        server.start(ContextureOptions(transport="stdio"))

Nothing above that last line mentions JSON-RPC, JSON Schema, stdio framing, or
any particular agent runtime. That is the whole claim the framework makes:
declare once, and Claude Code, Codex, and anything else that speaks MCP connect
to the same server.

**It takes a sealed assembly and has no way to register anything.** That is the
phase boundary, made structural rather than written down: you register into a
`ControllerManager`, you seal it once, and only then does a server exist. There
is no method here that could add a node to a graph that is already being
served, which is what the protocol forbids and what a run-time flag could only
complain about after the fact.

**It deliberately does not subclass the SDK's `MCPServer`.** The runtime owns
roles and disclosure; the SDK owns the wire. Keeping them as two objects that
compose is what lets the domain model stay testable without a transport, and
what keeps an SDK upgrade from reaching into the object model.

**Two objects, because they are fixed at two different times.**
`ContextureServer` is identity and topology — what is served, and what it is
called — settled before the process starts and unchanged after.
`ContextureOptions` is how to serve it: which transport, which address, who is
allowed to knock. Serving the same graph on a laptop and in a cluster changes
the second and none of the first.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import anyio
from mcp.server.mcpserver import MCPServer

from ..core.constants import PACKAGE_VERSION
from .assembly import Assembly
from ..core.model.channels import Channels
from . import instructions as instructions_module
from .identity import Auth
from .options import ContextureOptions, ServeError, Transport, configure_logging
from .projection import Gateway, Prompts, Resources

LOG = logging.getLogger(__name__)


class ContextureServer:
    """One sealed graph, served over MCP."""

    __slots__ = ("_assembly", "name", "version", "instructions", "_built", "_auth")

    def __init__(
        self,
        assembly: Assembly,
        *,
        name: str = "contexture",
        version: str = PACKAGE_VERSION,
        instructions: str | None = None,
    ) -> None:
        self._assembly = assembly
        self.name = name
        self.version = version
        #: What a host reads before it calls anything. Derived from the tree
        #: when nothing is stated, which is the ordinary case — see
        #: `server.instructions` for how it is fitted to a host's budget.
        self.instructions = instructions
        self._built: MCPServer | None = None
        self._auth: Auth | None = None

    @property
    def assembly(self) -> Assembly:
        """What this server serves. Frozen, and the same object `main` sealed."""

        return self._assembly

    # ---- building --------------------------------------------------------

    def build(self, *, auth: Auth | None = None) -> MCPServer:
        """Build the MCP server with all three planes hung on it.

        **Synchronous, and it stays that way.** Tests build a server and call
        into it directly, with no transport and no session, which is what lets
        the disclosure model be exercised without the wire. So a lifecycle
        wraps *serving* rather than *construction*, which is also what the
        SDK's own `lifespan` hook does — verified entered and exited on both
        the stdio and the streamable-HTTP path.

        **Idempotent.** `start` calls this, and a caller that built a server to
        look at it and then started it would otherwise be serving a second one.
        A different `auth` on a later call is refused rather than ignored,
        because only one of the two answers can be the one on the wire.
        """

        if self._built is not None:
            if auth is not None and auth is not self._auth:
                raise ServeError(
                    "This server was already built with a different auth. One "
                    "process serves one surface; build it once, or build two "
                    "servers if you genuinely mean two."
                )
            return self._built

        # Constructed before anything is written: each plane checks its own
        # declarations here, while the SDK server does not yet exist. A refusal
        # therefore leaves nothing half-registered behind it.
        planes = (
            Gateway(self._assembly),
            Prompts(self._assembly),
            Resources(self._assembly),
        )
        surface = self._surface(auth)
        for plane in planes:
            plane.project(surface)

        self._auth = auth
        self._built = surface
        return surface

    def _surface(self, auth: Auth | None) -> MCPServer:
        """The SDK object, told this server's identity and its lifecycle."""

        return MCPServer(
            name=self.name,
            version=self.version,
            instructions=self.instructions
            or instructions_module.build(self._assembly.tree),
            **({"lifespan": self._lifespan} if self._opens_channels else {}),
            **(
                {"auth": auth.settings(), "token_verifier": auth.sdk_verifier()}
                if auth is not None
                else {}
            ),
        )

    @property
    def _opens_channels(self) -> bool:
        """Whether anything has to be opened before the first request."""

        return isinstance(self._assembly.tree.registry.channels, Channels)

    @asynccontextmanager
    async def _lifespan(self, server: MCPServer) -> AsyncIterator[Any]:
        """Open this graph's handle for exactly as long as it is serving.

        What this yields reaches the SDK as `request_context.lifespan_context`,
        and nothing here reads it back: a capability finds its handle on itself,
        stamped by the registry, because half the doors into a capability carry
        no request context at all.
        """

        async with self._assembly.tree.registry.provisioned() as opened:
            yield opened

    # ---- serving ---------------------------------------------------------

    def start(
        self,
        options: ContextureOptions | None = None,
        *,
        transport: Transport | None = None,
    ) -> None:
        """Serve the graph. Blocks until the host disconnects.

        `transport=` is kept as the shorthand for the one-word case, because
        `server.start(transport="stdio")` is what a reader expects to be able
        to write. Anything beyond a transport name needs the options object —
        there is deliberately no `**kwargs`, since the thing it did best was
        accept arguments the SDK would then discard.
        """

        anyio.run(lambda: self.start_async(options, transport=transport))

    async def start_async(
        self,
        options: ContextureOptions | None = None,
        *,
        transport: Transport | None = None,
    ) -> None:
        """The same, for a process that already has an event loop.

        What this does *not* do is mount into somebody else's ASGI
        application: the HTTP branch runs the SDK's own uvicorn. A host that
        wants this graph inside its own Starlette app should take
        `build().streamable_http_app()` and route to it.
        """

        options = self._resolved(options, transport)
        configure_logging(options.log_level)
        surface = self.build(auth=options.auth)
        if options.transport == "stdio":
            await surface.run_stdio_async()
            return
        # Printed to the log rather than left to be inferred: the address is
        # assembled from four fields and a wrong one produces a server that
        # starts and answers nobody.
        LOG.info("Serving MCP on %s", options.url)
        await surface.run_streamable_http_async(**options.transport_kwargs())

    @staticmethod
    def _resolved(
        options: ContextureOptions | None,
        transport: Transport | None,
    ) -> ContextureOptions:
        if options is not None and transport is not None:
            raise ServeError(
                "Pass either options or transport=, not both: "
                f"options.transport is {options.transport!r} and transport= is "
                f"{transport!r}, and nothing here can tell which you meant."
            )
        if options is not None:
            return options
        return ContextureOptions(
            **({"transport": transport} if transport is not None else {})
        )


__all__ = ["ContextureServer"]
