"""The registry that owns every controller this process serves.

A declaration says what a capability *is*. Nothing in it says which ones this
server offers, where each one hangs, or what it may reach outside the process —
those are three questions about a running application, and until now they were
answered in three different places at three different times.

`ControllerManager` is where they are answered together, once, before anything
is served:

    channels = OCChannels(gateway=connect("http://gateway:8000"))
    manager = ControllerManager(channels=channels)
    manager.register(KubernetesPlatform)

**Controller**, because that is what these objects are: a caller names one and
it decides what happens. The name is chosen against MVC deliberately — the
model is the declaration, the view is `disclosure` compiling a node for an
agent, and this layer is the C that both of those have been quietly doing
without a home. Nothing here renders anything, and nothing here touches a wire.

Three properties this object exists to hold, none of which any single node can:

**One node has exactly one address.** A ref *is* a path, so the same object
appearing under two parents would give one capability two doors, and "the model
has not opened X" would stop meaning anything. `Role._require_unique_members`
enforces this inside one role; only something that has seen the whole graph can
enforce it across roles, and registration is where the whole graph is walked.

**A node is told where it hangs.** It cannot work it out — one Tool instance
knows nothing about its parent — and every caller that needed a node's address
has so far had to recompute it by walking. Registration stamps it once.

**A handle arrives before the first call, not during it.** The application
builds its channels first, hands them here, and every registered controller can
reach them. This is `main()`'s order, and it is the order a caller assumes.

Registration is additive and takes classes as readily as instances, so what a
server offers is a list of calls an application makes rather than whatever
happens to have been imported.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Iterator, Sequence

from ..errors import LookupFailure, ModelValidationError, NodeNotFoundError
from .node import ContextNode
from .role import Role


@dataclass(slots=True)
class ControllerManager:
    """Every controller this application serves, and what they may reach."""

    #: The handle the application built before registering anything. Whatever
    #: it is, the framework never inspects it — it only makes sure every
    #: registered controller can reach the same one.
    channels: Any = None

    #: How to open that handle, for anything that cannot simply be
    #: constructed: a pool that must be awaited into existence, a session that
    #: shakes hands, a client that has to be closed again afterwards.
    #:
    #: A **factory** returning an async context manager, never a context
    #: manager itself. One is consumed by being entered, so a server run twice
    #: would meet an `AttributeError` raised from inside `contextlib` — a long
    #: way from the mistake that caused it.
    #:
    #: The framework enters exactly one. Composing several is the
    #: application's own job, in its own factory, where `async with a, b`
    #: already unwinds them in the right order::
    #:
    #:     @asynccontextmanager
    #:     async def open_channels():
    #:         async with gateway_session(URL) as gw, create_pool(DSN) as db:
    #:             yield Channels(gateway=gw, db=db)
    provision: Callable[[], AbstractAsyncContextManager[Any]] | None = None

    _roots: list[Role] = field(default_factory=list, repr=False)
    _by_path: dict[tuple[str, ...], ContextNode] = field(
        default_factory=dict, repr=False
    )
    #: `id()` keyed, and the node is held in `_by_path`, so an id cannot be
    #: reused while it is still a key here.
    _address_of: dict[int, tuple[str, ...]] = field(default_factory=dict, repr=False)
    _parent_of: dict[int, ContextNode | None] = field(default_factory=dict, repr=False)
    _by_kind: dict[str, list[ContextNode]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.channels is not None and self.provision is not None:
            raise ModelValidationError(
                "This manager was given both channels and a way to open them. "
                "Keep the one that matches the handle: `channels` for a value "
                "that is simply constructed, `provision` for one that has to "
                "be opened and closed again."
            )
        if self.provision is None:
            return
        # Refused here rather than at startup, because the two mistakes look
        # identical in a source file and only one of them is survivable: a
        # context manager is spent by being entered, so a server run a second
        # time would fail from inside `contextlib` with nothing pointing back
        # to this line.
        if hasattr(self.provision, "__aenter__"):
            raise ModelValidationError(
                "`provision` was given a context manager, not a factory. Pass "
                "the function itself — `provision=open_channels`, not "
                "`provision=open_channels()` — because a context manager is "
                "consumed by being entered and a server may be run twice."
            )
        if not callable(self.provision):
            raise ModelValidationError(
                f"`provision` must be callable; {self.provision!r} is not."
            )

    # ---- lifecycle -------------------------------------------------------

    @asynccontextmanager
    async def provisioned(self) -> AsyncIterator[Any]:
        """Hold this registry's handle open, and put it in reach of everything.

        Entered before the first request and exited after the last, so a
        connection that cannot be opened fails on the way up — in front of
        whoever started the server — rather than in front of the first caller
        who needed it.

        What it opens is stamped onto every registered controller, which is
        what keeps a dependency reachable **without a live session**: the SDK
        enters no lifespan for an in-process call, so a handle that lived only
        inside a request would be out of reach of a test, of `inspection`, and
        of a resource read.

        On the way out the handle is cleared rather than left behind. A call
        arriving after shutdown then sees `None`, which fails legibly, instead
        of a closed session, which fails somewhere deep inside somebody else's
        client library.
        """

        if self.provision is None:
            # Nothing to open. Yielding what is already there saves a caller
            # from having to ask which kind of manager it is holding.
            yield self.channels
            return

        opener = self.provision()
        if not hasattr(opener, "__aenter__"):
            raise ModelValidationError(
                f"`provision` returned {opener!r}, which is not an async "
                "context manager. It has to be a factory returning one: a "
                "function decorated with `@asynccontextmanager`, or a class "
                "with `__aenter__` and `__aexit__`."
            )
        async with opener as opened:
            self.rebind_channels(opened)
            try:
                yield opened
            finally:
                self.rebind_channels(None)

    # ---- registration ----------------------------------------------------

    def register(self, controller: Role | type[Role]) -> Role:
        """Take one root into this manager, and return what was registered.

        A class is built here rather than by the caller. That is not a
        convenience: it is what makes registration the moment a controller
        comes into existence with everything it needs, which is the whole point
        of taking the channels first.
        """

        root = self._build(controller)
        if any(existing.name == root.name for existing in self._roots):
            raise ModelValidationError(
                f"Two roots are both named {root.name!r}; a root name is the "
                "first segment of every address beneath it, so the second one "
                "would make its whole branch unreachable."
            )
        self._absorb(root, (root.name,), parent=None, ancestors=())
        self._roots.append(root)
        return root

    def register_all(self, controllers: Sequence[Role | type[Role]]) -> tuple[Role, ...]:
        """Register several roots in order, returning what each became."""

        return tuple(self.register(controller) for controller in controllers)

    @staticmethod
    def _build(controller: Role | type[Role]) -> Role:
        if isinstance(controller, Role):
            return controller
        if isinstance(controller, type) and issubclass(controller, Role):
            return controller()
        raise ModelValidationError(
            f"{controller!r} is not a Role or a Role subclass. A manager "
            "registers roots; a skill or a tool reaches this graph by being "
            "declared inside one."
        )

    def _absorb(
        self,
        node: ContextNode,
        path: tuple[str, ...],
        *,
        parent: ContextNode | None,
        ancestors: tuple[int, ...],
    ) -> None:
        """Record one node and everything it holds, depth-first."""

        seen_at = self._address_of.get(id(node))
        if seen_at is not None:
            if id(node) in ancestors:
                raise ModelValidationError(
                    f"{node.name!r} contains itself: {'/'.join(seen_at)} is on "
                    f"the path to {'/'.join(path)}. Containment is a forest, "
                    "and a procedure that needs to name something above it "
                    "references it instead."
                )
            raise ModelValidationError(
                f"{node.name!r} is held twice, at {'/'.join(seen_at)} and at "
                f"{'/'.join(path)}. One capability gets one address, because "
                "an address is how anything says which capability it means — "
                "declare it once and reference it from the other place."
            )

        node.path = path
        if self.channels is not None:
            # A manager with no handle provides nothing, so it leaves whatever
            # is already there alone. Two managers over one graph is the
            # ordinary case while the server still builds its own — and the one
            # that was given channels must win over the one that was not.
            node.channels = self.channels
        self._address_of[id(node)] = path
        self._by_path[path] = node
        self._parent_of[id(node)] = parent
        self._by_kind.setdefault(node.kind, []).append(node)

        if isinstance(node, Role):
            below = ancestors + (id(node),)
            for member in node.members():
                self._absorb(member, path + (member.name,), parent=node, ancestors=below)

    def rebind_channels(self, channels: Any) -> None:
        """Point every registered controller at a different handle.

        For a test that swaps a fake in, and for an application whose handle
        cannot exist until later. It restamps rather than storing a reader,
        because a node holding a stale value is a bug that a second indirection
        only makes harder to see.
        """

        self.channels = channels
        for node in self._by_path.values():
            node.channels = channels

    # ---- queries ---------------------------------------------------------

    @property
    def roots(self) -> tuple[Role, ...]:
        """The registered roots, in the order they were registered."""

        return tuple(self._roots)

    def find(self, path: Sequence[str]) -> ContextNode:
        """Return the one controller at `path`.

        One dictionary lookup rather than a walk, and the walk that remains is
        only to say *where* a miss happened: a caller that reached for
        `a/b/c` is owed the segment that failed, not the whole address back.
        """

        segments = tuple(path)
        if not segments:
            raise NodeNotFoundError(reason=LookupFailure.EMPTY_REF)
        found = self._by_path.get(segments)
        if found is not None:
            return found

        # A miss costs one more pass, and it buys the facts the failure has to
        # carry: which segment failed, what was holding it, and what that thing
        # does hold. An agent reads this and tries something else, so an
        # accurate list is the difference between a retry and a guess.
        if segments[:1] not in self._by_path:
            raise NodeNotFoundError(
                reason=LookupFailure.NO_SUCH_ROOT,
                segment=segments[0],
                scope=segments[0],
                known=sorted(root.name for root in self._roots),
            )
        for depth in range(2, len(segments) + 1):
            if segments[:depth] in self._by_path:
                continue
            held = self._by_path[segments[: depth - 1]]
            if not isinstance(held, Role):
                raise NodeNotFoundError(
                    reason=LookupFailure.NOT_A_CONTAINER,
                    segment=segments[depth - 1],
                    scope=held.name,
                    kind=held.kind,
                )
            raise NodeNotFoundError(
                reason=LookupFailure.NO_SUCH_MEMBER,
                segment=segments[depth - 1],
                scope=held.name,
                kind=held.kind,
                known=sorted(member.name for member in held.members()),
            )
        raise NodeNotFoundError(  # pragma: no cover - the loop above is total
            reason=LookupFailure.NO_SUCH_MEMBER, segment=segments[-1]
        )

    def address_of(self, node: ContextNode) -> tuple[str, ...] | None:
        """Where a registered node hangs, or None if this manager never saw it."""

        return self._address_of.get(id(node))

    def parent_of(self, node: ContextNode) -> ContextNode | None:
        """The controller holding `node`, or None for a root."""

        return self._parent_of.get(id(node))

    def children_of(self, node: ContextNode) -> tuple[ContextNode, ...]:
        """Everything `node` holds, one level down and in declared order."""

        if not isinstance(node, Role):
            return ()
        return tuple(node.members())

    def of_kind(self, kind: str) -> tuple[ContextNode, ...]:
        """Every registered controller of one kind, in registration order.

        The flat view of the graph: all the tools, wherever they hang. It is
        what an audit, a metric, or a startup check wants, and none of those
        should have to walk a forest to ask a question about a kind.
        """

        return tuple(self._by_kind.get(kind, ()))

    def walk(self) -> Iterator[tuple[tuple[str, ...], ContextNode]]:
        """Yield every `(path, controller)` pair, depth-first, in order."""

        yield from self._by_path.items()

    def __len__(self) -> int:
        return len(self._by_path)

    def __contains__(self, path: object) -> bool:
        return isinstance(path, tuple) and path in self._by_path


__all__ = ["ControllerManager"]
