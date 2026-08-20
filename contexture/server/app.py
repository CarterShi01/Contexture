"""The object a business application hands to its host.

A project states its context as roles, skills and tools, and then says::

    app = ContextureApp(roots=[KubernetesPlatform])

    if __name__ == "__main__":
        app.run()

Nothing above that line mentions JSON-RPC, JSON Schema, stdio framing, or any
particular agent runtime. That is the whole claim the framework makes: declare
once, and Claude Code, Codex, and anything else that speaks MCP connect to the
same server.

`ContextureApp` deliberately does not subclass the SDK's `MCPServer`. The
runtime owns roles and disclosure; the SDK owns the wire. Keeping them as two
objects that compose is what lets the domain model stay testable without a
transport, and what keeps an SDK upgrade from reaching into the object model.

**Two objects, because they are fixed at two different times.** `ContextureApp`
is identity and topology — what is served, and what it is called — settled
before the process starts and unchanged after. `ContextureOptions` is how to
serve it: which transport, which address, who is allowed to knock. Serving the
same graph on a laptop and in a cluster changes the second and none of the
first.
"""

from __future__ import annotations

import logging
import sys
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Iterable,
    Literal,
    Mapping,
    Sequence,
)

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from ..core.constants import PACKAGE_VERSION
from ..core.errors import ContextureError, ModelValidationError
from ..core.mcp_interface import published
from ..core.mcp_interface.prompt import Prompt
from ..core.mcp_interface.resource import Resource
from ..core.disclosure.tree import register_root as _register
from ..core.model.manager import ControllerManager
from ..core.model.node import ContextNode
from ..core.model.role import Role
from ..core.disclosure.tree import ContextTree
from . import instructions as instructions_module
from .binding import Dispatch, project
from .identity import Auth

#: The transports this server offers. HTTP+SSE was the 2024-11-05 two-endpoint
#: transport; it was replaced by Streamable HTTP and is deprecated in the
#: revisions this server speaks, so it is not offered. A host that still needs
#: it can put a proxy in front.
Transport = Literal["stdio", "streamable-http"]

#: Where an HTTP server listens when nobody says otherwise. Loopback, because
#: a context server's tools are the interesting half of a machine and binding
#: wider should be something a person typed.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_PATH = "/mcp"

#: Addresses that reach this machine and nowhere else. The SDK turns on DNS
#: rebinding protection by itself for exactly these, and leaves it off for
#: everything else — which is the gap `ContextureOptions` closes.
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})

#: Fields that mean nothing under stdio. Naming them is what turns
#: `run(transport="stdio", port=9000)` from a silently discarded argument into
#: a sentence.
_HTTP_ONLY = (
    "host",
    "port",
    "path",
    "auth",
    "allowed_hosts",
    "allowed_origins",
    "allow_anonymous",
    "max_request_body_size",
)

#: SDK keyword arguments this object owns. Setting one through `sdk_overrides`
#: would leave two places deciding the same thing, and the loser would be
#: whichever this code happens to apply second.
_OWNED_BY_OPTIONS = frozenset(
    {
        "host",
        "port",
        "streamable_http_path",
        "transport_security",
        "max_request_body_size",
    }
)


class ServeError(ContextureError):
    """Raised when how-to-serve was stated in a way that cannot be honoured."""


@dataclass(slots=True, frozen=True, kw_only=True)
class ContextureOptions:
    """How to serve a graph. Not what to serve, and not what it is called.

    ::

        app.run()                                     # stdio, the default
        app.run(ContextureOptions(
            transport="streamable-http",
            host="0.0.0.0",
            port=8080,
            auth=Auth(verifier=OktaVerifier(), issuer=..., resource=...),
            allowed_origins=["https://acme.example"],
        ))

    Every field defaults to `None` rather than to its eventual value, so that
    "not stated" and "stated as the default" stay different things. That is
    what lets `transport="stdio", port=8000` be reported as the mistake it is
    instead of being quietly dropped, which is what a `**kwargs` passthrough
    did and could not help doing.
    """

    transport: Transport = "stdio"

    #: Interface to bind. Defaults to loopback; see `LOOPBACK`.
    host: str | None = None

    port: int | None = None

    #: Where the MCP endpoint lives. Defaults to `/mcp`.
    path: str | None = None

    #: How this server checks who is calling. `None` serves everybody as an
    #: unauthenticated caller, and `current_principal()` returns `None`
    #: throughout.
    auth: Auth | None = None

    #: `Host` and `Origin` headers this server will answer. Required once
    #: `host` is not loopback: the SDK enables DNS rebinding protection on its
    #: own for loopback addresses and silently leaves it off for the rest, so
    #: the address where it matters is the one where nothing would say so.
    allowed_hosts: tuple[str, ...] = ()
    allowed_origins: tuple[str, ...] = ()

    #: Serve a non-loopback address with no `auth`. It has to be typed, because
    #: everything the declared tools can reach becomes reachable by anyone who
    #: can route to this port.
    allow_anonymous: bool = False

    log_level: int = logging.INFO

    max_request_body_size: int | None = None

    #: The deliberate escape hatch, deliberately named as one. Anything the SDK
    #: accepts and this object has no opinion about — `json_response`, say —
    #: goes here, and the coupling shows up in the code that takes it rather
    #: than hiding inside `**kwargs`.
    sdk_overrides: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_hosts", tuple(self.allowed_hosts))
        object.__setattr__(self, "allowed_origins", tuple(self.allowed_origins))
        object.__setattr__(self, "sdk_overrides", dict(self.sdk_overrides))
        self._check()

    # ------------------------------------------------------------- validation

    def _check(self) -> None:
        if self.transport == "stdio":
            self._reject_http_fields()
        else:
            self._require_safe_bind()
        self._reject_owned_overrides()

    def _reject_http_fields(self) -> None:
        """Refuse the arguments stdio would throw away.

        The SDK's stdio branch is `anyio.run(self.run_stdio_async)` and takes
        no keyword arguments at all, so a port stated alongside it used to
        vanish without a word. A mistake that produces a working server on the
        wrong assumption is worse than one that produces no server.
        """

        stated = [
            name
            for name in _HTTP_ONLY
            if getattr(self, name) not in (None, (), False)
        ]
        if stated:
            raise ServeError(
                f"transport='stdio' cannot use {', '.join(stated)}: stdio has "
                "no address to bind and no request to authenticate — the host "
                "launched this process, and the operating system already "
                "decided who is running it. Use "
                "transport='streamable-http' if you meant to serve over HTTP."
            )

    def _require_safe_bind(self) -> None:
        """Two things that must be typed before this port faces anyone else."""

        if self.resolved_host in LOOPBACK:
            return
        if not (self.allowed_hosts or self.allowed_origins):
            raise ServeError(
                f"host={self.resolved_host!r} is not loopback, so DNS "
                "rebinding protection does not turn itself on. State "
                "allowed_hosts and/or allowed_origins — without them a page in "
                "somebody's browser can drive this server through their "
                "machine."
            )
        if self.auth is None and not self.allow_anonymous:
            raise ServeError(
                f"host={self.resolved_host!r} is not loopback and no auth was "
                "given, so everything the declared tools can reach becomes "
                "reachable by anyone who can route to port "
                f"{self.resolved_port}. Pass auth=Auth(...), or state "
                "allow_anonymous=True if that is genuinely what you want."
            )

    def _reject_owned_overrides(self) -> None:
        """Keep `sdk_overrides` an escape hatch rather than a second steering wheel."""

        if "stateless_http" in self.sdk_overrides:
            raise ServeError(
                "stateless_http is not a knob this framework offers. The "
                "server keeps no per-connection state and a ref resolves the "
                "same way for everyone, which is what makes progressive "
                "disclosure legal under a protocol that has no session; "
                "serving with sessions would make that documented design false "
                "without making anything fail. It is pinned True."
            )
        if "event_store" in self.sdk_overrides:
            raise ServeError(
                "event_store replays a stream back to a resumed session, and "
                "this server has no sessions to resume — see stateless_http."
            )
        clashing = sorted(_OWNED_BY_OPTIONS & set(self.sdk_overrides))
        if clashing:
            raise ServeError(
                f"sdk_overrides may not set {', '.join(clashing)}: "
                "ContextureOptions owns those, and two places deciding one "
                "value means the answer depends on which is applied last."
            )

    # --------------------------------------------------------------- resolved

    @property
    def resolved_host(self) -> str:
        return self.host if self.host is not None else DEFAULT_HOST

    @property
    def resolved_port(self) -> int:
        return self.port if self.port is not None else DEFAULT_PORT

    @property
    def resolved_path(self) -> str:
        return self.path if self.path is not None else DEFAULT_PATH

    @property
    def url(self) -> str:
        """Where a host should point, once this is serving."""

        return f"http://{self.resolved_host}:{self.resolved_port}{self.resolved_path}"

    def transport_kwargs(self) -> dict[str, Any]:
        """The keyword arguments the SDK's runner is given.

        `stateless_http=True` is here rather than in a field: see
        `_reject_owned_overrides` for why it is not offered as a choice.
        """

        if self.transport == "stdio":
            return {}
        security: TransportSecuritySettings | None = None
        if self.allowed_hosts or self.allowed_origins:
            security = TransportSecuritySettings(
                allowed_hosts=list(self.allowed_hosts),
                allowed_origins=list(self.allowed_origins),
            )
        kwargs: dict[str, Any] = {
            "host": self.resolved_host,
            "port": self.resolved_port,
            "streamable_http_path": self.resolved_path,
            "stateless_http": True,
            "transport_security": security,
        }
        if self.max_request_body_size is not None:
            kwargs["max_request_body_size"] = self.max_request_body_size
        kwargs.update(self.sdk_overrides)
        return kwargs


@dataclass(slots=True, kw_only=True)
class ContextureApp:
    """A declared capability graph, ready to be served over MCP."""

    #: The roots this server offers, or the registry they were registered
    #: into. Passing the registry is the order an application that has
    #: downstream connections wants: build them, register against them, serve.
    #:
    #: A root is ordinarily a **class**, and handing over the class rather than
    #: an instance is what keeps construction inside registration — see
    #: `ControllerManager._build`. An already-built Role is accepted too.
    roots: Any = ()

    #: A shortcut for the same thing when there is no reason to hold the
    #: registry yourself: whatever an application wants its capabilities to
    #: reach outside this process. It is registered before anything is served
    #: and never inspected here.
    channels: Any = None

    #: The same shortcut for a handle that has to be *opened* rather than
    #: constructed. A factory returning an async context manager; it is entered
    #: before the first request and exited after the last.
    provision: Callable[[], AbstractAsyncContextManager[Any]] | None = None

    #: What this server puts on the prompt and resource primitives.
    #: Authored, never derived: adding one is a code change and a restart,
    #: which is what keeps these lists from varying under a live
    #: connection — something the protocol forbids in any case.
    #:
    #: Stated as classes, like everything else a business declares; already
    #: built values are accepted too. Either way they are normalised here, so
    #: nothing below this line has to ask which arrived.
    publish: Sequence[Any] = ()

    name: str = "contexture"
    version: str = PACKAGE_VERSION
    instructions: str | None = None

    tree: ContextTree = field(init=False)
    dispatch: Dispatch = field(init=False)

    def __post_init__(self) -> None:
        # One Dispatch derives every schema and validates every call, so a
        # card's schema and the check a call is measured against cannot drift.
        self.dispatch = Dispatch()
        self.publish = tuple(published(entry) for entry in self.publish)
        self.tree = ContextTree.of(
            self._registry(), schema_of=self.dispatch.schema
        )
        self.roots = self.tree.roots

    def _registry(self) -> ControllerManager:
        """Resolve what was passed into the one registry this app serves.

        A manager arrives already filled — with its handle in place, because
        that is the point of holding one. Anything else is registered here, and
        `channels` is how an application that never wanted to hold a registry
        still gets its capabilities connected to something.
        """

        if isinstance(self.roots, ControllerManager):
            given = self.channels is not None or self.provision is not None
            if given and self.channels is not self.roots.channels:
                raise ModelValidationError(
                    "This app was given both a manager and channels. The "
                    "manager already holds a handle; passing a second one here "
                    "would leave two answers to what a capability reaches."
                )
            return self.roots
        manager = ControllerManager(channels=self.channels, provision=self.provision)
        for root in _each(self.roots):
            _register(manager, root)
        return manager

    @property
    def manager(self) -> ControllerManager:
        """The registry backing this server."""

        return self.tree.registry

    @asynccontextmanager
    async def _lifespan(self, server: MCPServer) -> AsyncIterator[Any]:
        """Open this app's handle for exactly as long as it is serving.

        What this yields reaches the SDK as `request_context.lifespan_context`,
        and nothing here reads it back: a capability finds its handle on itself,
        stamped by the registry, because half the doors into a capability carry
        no request context at all.
        """

        async with self.manager.provisioned() as opened:
            yield opened

    def build_server(self, *, auth: Auth | None = None) -> MCPServer:
        """Build the MCP server with the gateway registered on it.

        **Synchronous, and it stays that way.** Tests build a server and call
        into it directly, with no transport and no session, which is what lets
        the disclosure model be exercised without the wire. So a lifecycle
        wraps *serving* rather than *construction*, which is also what the
        SDK's own `lifespan` hook does — verified entered and exited on both
        the stdio and the streamable-HTTP path.
        """

        server = MCPServer(
            name=self.name,
            version=self.version,
            instructions=self.instructions
            or instructions_module.build(self.tree),
            **({"lifespan": self._lifespan} if self.manager.provision else {}),
            **(
                {
                    "auth": auth.settings(),
                    "token_verifier": auth.sdk_verifier(),
                }
                if auth is not None
                else {}
            ),
        )
        project(
            server,
            tree=self.tree,
            dispatch=self.dispatch,
            publish=self.publish,
        )
        return server

    def run(
        self,
        options: ContextureOptions | None = None,
        *,
        transport: Transport | None = None,
    ) -> None:
        """Serve the graph. Blocks until the host disconnects.

        `transport=` is kept as the shorthand for the one-word case, because
        `app.run(transport="stdio")` is what every project and every example
        already says. Anything beyond a transport name needs the options
        object — there is deliberately no `**kwargs` any more, since the thing
        it did best was accept arguments the SDK would then discard.
        """

        if options is not None and transport is not None:
            raise ServeError(
                "Pass either options or transport=, not both: "
                f"options.transport is {options.transport!r} and transport= is "
                f"{transport!r}, and nothing here can tell which you meant."
            )
        if options is None:
            options = ContextureOptions(
                **({"transport": transport} if transport is not None else {})
            )

        configure_logging(options.log_level)
        server = self.build_server(auth=options.auth)
        if options.transport != "stdio":
            # Printed to the log rather than left to be inferred: the address
            # is assembled from four fields and a wrong one produces a server
            # that starts and answers nobody.
            logging.getLogger(__name__).info("Serving MCP on %s", options.url)
        server.run(options.transport, **options.transport_kwargs())


def _each(given: Any) -> tuple[Any, ...]:
    """One root or many, told apart without making a caller say which."""

    kinds = (ContextNode,)
    if isinstance(given, kinds) or (
        isinstance(given, type) and issubclass(given, kinds)
    ):
        return (given,)
    return tuple(given)


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


__all__ = [
    "ContextureApp",
    "ContextureOptions",
    "DEFAULT_HOST",
    "DEFAULT_PATH",
    "DEFAULT_PORT",
    "LOOPBACK",
    "ServeError",
    "Transport",
    "configure_logging",
]
