"""The registry that owns every controller this process serves.

A declaration says what a capability *is*. Nothing in it says which ones this
server offers, where each one hangs, or what it may reach outside the process —
those are three questions about a running application, and until now they were
answered in three different places at three different times.

`ControllerManager` is where they are answered together, once, before anything
is served:

    channels = OCChannels(gateway=connect("http://gateway:8000"))
    manager = ControllerManager(channels=channels)
    manager.register_role(KubernetesPlatform)
    manager.register_tool(Ping)          # a capability that belongs to no role

**Controller**, because that is what these objects are: a caller names one and
it decides what happens. The name is chosen against MVC deliberately — the
model is the declaration, the view is `Disclosure` compiling a node for an
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

**Three methods, one per kind.** What a root *is* decides what may hang beneath
it, and naming the kind at the call site says so where a reader is looking
rather than leaving it to be inferred from an argument's type. It is also the
only shape the other two implementations can share: a typed slice per kind is
what Go has instead of a list of `any`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from ..errors import ModelValidationError
from .channels import provisioned as _provisioned
from .node import ContextNode
from .role import Role
from .skill import Skill
from .tool import Tool


@dataclass(slots=True)
class ControllerManager:
    """Every controller this application serves, and what they may reach."""

    #: The handle the application built before registering anything. Whatever
    #: it is, the framework never inspects it — it only makes sure every
    #: registered controller can reach the same one.
    #:
    #: A plain value is stamped and left alone. A `Channels` subclass is
    #: stamped *and* opened before the first request and closed after the last
    #: — see `provisioned`. Which of the two it is is the only thing this
    #: layer ever asks about it.
    channels: Any = None

    #: What was registered at the top, one list per kind. Three rather than
    #: one, because which kind a root is decides what may hang beneath it, and
    #: naming the kind at the call site says so where a reader is looking.
    #: They share **one namespace** all the same: a root's name is the first
    #: segment of every reference beneath it, so two roots of two kinds cannot
    #: be called the same thing.
    _roles: list[Role] = field(default_factory=list, repr=False)
    _skills: list[Skill] = field(default_factory=list, repr=False)
    _tools: list[Tool] = field(default_factory=list, repr=False)

    #: Where each controller was already seen, `id()` keyed. The only table
    #: registration keeps, and only for the length of registration: it refuses
    #: one object held at two addresses and names both. Everything else that was
    #: once indexed here — find, of_kind, parentage — is a fact *about* the
    #: registered forest, and moved to `Index` when it stopped having a caller
    #: here that was not the tree. A node stays alive as its parent's member, so
    #: an id cannot be reused while it is still a key.
    _seen: dict[int, tuple[str, ...]] = field(default_factory=dict, repr=False)

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

        **Stamped and opened are the same object.** A `Channels` subclass is
        registered before it is opened and keeps its identity through both, so
        nothing is restamped on the way in and nothing is cleared on the way
        out. What a call arriving after shutdown meets is therefore whatever
        that object's own `close` left behind — which is why `Channels.close`
        says to clear its references there.

        The served path opens the handle through `Index`, over the same object
        this would open; this stays for a test driving registration directly,
        and both run the one shared helper so they cannot open it two ways.
        """

        async with _provisioned(self.channels) as opened:
            yield opened

    # ---- registration ----------------------------------------------------

    def register_role(self, controller: Any) -> Role:
        """Take one root role into this manager, and return what was built."""

        return self._register(controller, Role, self._roles)

    def register_skill(self, controller: Any) -> Skill:
        """Take one standalone procedure — one that belongs to no role."""

        return self._register(controller, Skill, self._skills)

    def register_tool(self, controller: Any) -> Tool:
        """Take one standalone capability — one that belongs to no role.

        Worth knowing before reaching for this: a tool's card carries its input
        schema, so a tool registered at the top is a schema every session is
        handed by `contexture_discover`, before anybody has asked for it. That
        is the right trade for a server whose whole surface is three tools, and
        the wrong one for a server with fifty — where the fix is to put them
        under a role, and let a session pay for the branch it enters.
        """

        return self._register(controller, Tool, self._tools)

    def _register(
        self,
        controller: Any,
        kind: type,
        bucket: list[Any],
    ) -> Any:
        """Build one root, refuse a name already taken, then record it."""

        root = self._build(controller, kind)
        taken = next(
            (held for held in self.roots if held.name == root.name), None
        )
        if taken is not None:
            raise ModelValidationError(
                f"Two roots are both named {root.name!r} (a {taken.kind} and a "
                f"{root.kind}); a root name is the first segment of every "
                "address beneath it, so the second one would make its whole "
                "branch unreachable."
            )
        self._absorb(root, (root.name,), ancestors=())
        bucket.append(root)
        return root

    @staticmethod
    def _build(controller: Any, kind: type) -> Any:
        """Turn a zero-argument factory into the node, or take one as it is.

        A **class** is the ordinary door, and a class is a zero-argument
        factory: its `__init__` passes its identity to the base and builds its
        own members. So this is the one line in the package that brings a
        declared graph into existence, and everything about *when* that happens
        follows from it — nothing exists until something is registered.
        """

        built = controller() if isinstance(controller, type) else controller
        if not isinstance(built, kind):
            raise ModelValidationError(
                f"{controller!r} is not a {kind.__name__}. "
                f"`register_{kind.__name__.lower()}` takes a {kind.__name__} "
                "or a class that builds one with no arguments."
            )
        return built

    def _absorb(
        self,
        node: ContextNode,
        path: tuple[str, ...],
        *,
        ancestors: tuple[int, ...],
    ) -> None:
        """Stamp one node and everything it holds, depth-first.

        Registration assigns each node its address and its handle, and refuses
        the two shapes only a walk of the whole forest can catch: one object
        held at two addresses, and one that contains itself. What the addresses
        are *for* — resolving a ref, listing a kind — is `Index`'s question, and
        this keeps none of the tables that would answer it.
        """

        seen_at = self._seen.get(id(node))
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
        self._seen[id(node)] = path

        if isinstance(node, Role):
            below = ancestors + (id(node),)
            for member in node.members():
                self._absorb(member, path + (member.name,), ancestors=below)

    def rebind_channels(self, channels: Any) -> None:
        """Point every registered controller at a different handle.

        For a test that swaps a fake in, and for an application whose handle
        cannot exist until later. It restamps rather than storing a reader,
        because a node holding a stale value is a bug that a second indirection
        only makes harder to see.
        """

        self.channels = channels
        for root in self.roots:
            _restamp(root, channels)

    # ---- what was registered ---------------------------------------------

    @property
    def roles(self) -> tuple[Role, ...]:
        """The root roles, in the order they were registered."""

        return tuple(self._roles)

    @property
    def skills(self) -> tuple[Skill, ...]:
        """The standalone procedures, in the order they were registered."""

        return tuple(self._skills)

    @property
    def tools(self) -> tuple[Tool, ...]:
        """The standalone capabilities, in the order they were registered."""

        return tuple(self._tools)

    @property
    def roots(self) -> tuple[ContextNode, ...]:
        """Everything registered at the top, roles first, then skills, then tools.

        One sequence over the three lists, for the callers that need the whole
        top level rather than one kind of it — the name check above, and the
        tree that discloses it.
        """

        return (*self._roles, *self._skills, *self._tools)

    # ---- sealing ---------------------------------------------------------

    def sealed(self, *, bind: Any = None) -> Any:
        """Compile this registry into the frozen view an agent is disclosed.

        Registration is additive and mutable; disclosure is neither. Sealing is
        the line between the two phases, and it is where the checks that need
        the **whole** forest finally run — a skill in the first root may name a
        capability in the third, so `uses` has no answer until nothing more is
        coming. Those checks now live on `Index`, which is what a sealed view is
        built over; this is the shorthand that reads as one step in `main`.

        Nothing here is frozen. `Index` is frozen, and a manager registered into
        afterwards simply compiles a different one the next time; what must not
        happen is a graph changing under a view already serving, which is
        `Role`'s rule and not this method's to enforce.
        """

        # Imported here rather than at the top because the view imports this
        # module: a registry has to exist before there is anything to seal, so
        # the dependency runs that way round and only the return trip is local.
        from .disclosure import Disclosure

        if bind is None:
            return Disclosure.of(self)
        return Disclosure.of(self, bind=bind)


def _restamp(node: ContextNode, channels: Any) -> None:
    """Point one node and everything it holds at a handle, depth-first."""

    node.channels = channels
    if isinstance(node, Role):
        for member in node.members():
            _restamp(member, channels)


def register_root(registry: ControllerManager, root: Any) -> None:
    """Send one root to the registration method that matches its kind.

    Three explicit methods are the door a declaration goes through, because
    naming the kind at the call site says what may hang beneath it where a
    reader is looking. This is for the one caller that cannot name it: an
    application handing over a list it was given, where what kind each root is
    is only knowable at run time.
    """

    built = root() if isinstance(root, type) else root
    if isinstance(built, Tool):
        registry.register_tool(built)
    elif isinstance(built, Skill):
        registry.register_skill(built)
    else:
        registry.register_role(built)


__all__ = ["ControllerManager", "register_root"]
