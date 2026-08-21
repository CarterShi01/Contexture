"""What a capability reaches outside its own process, and when it is opened.

A declaration says what a capability *is*. It never says where the cluster
lives, which database holds the rows, or whose gateway answers — those are
facts about a deployment, and they arrive from the application through
`ControllerManager`::

    channels = ClusterChannels(kubeconfig=Path(os.environ["KUBECONFIG"]))
    manager = ControllerManager(channels=channels)
    manager.register_role(KubernetesPlatform)

**The framework never inspects what a handle holds.** It only needs to know
one thing, and it is a thing no plain value can express: whether this handle
has to be *opened* before the first request and closed after the last. That is
what this class is for. A handle that is simply constructed stays a plain
object and is passed as `channels=` unchanged; a handle with a lifecycle
subclasses `Channels`, and the two methods below are the whole contract.

    class ClusterChannels(Channels):
        def __init__(self, kubeconfig: Path) -> None:
            self.kubeconfig = kubeconfig          # no super().__init__() needed

        async def open(self) -> None:
            self.api = await self.enter(kube_session(self.kubeconfig))
            self.db = await self.enter(create_pool(DSN))

**`enter` is the reason there is a base class rather than a protocol.**
Composing several handles used to be the application's own job in a factory
returning an async context manager, where `async with a, b` unwound them in
the right order and closed the first if the second failed to open. Asking an
application to write `open`/`close` by hand would take that back and hand it a
new class of bug: a half-opened handle nobody closes. So the base holds an
`AsyncExitStack` for the duration of `lifespan`, `enter` puts a context manager
on it, and unwinding — in reverse, on the way out *and* on a failure part way
in — is the framework's.

**Opened as many times as it is served.** The stack is created inside
`lifespan` rather than in a constructor, so a server that is run twice opens
twice and closes twice. The rule this replaces — "pass a factory, never a
context manager, because one is consumed by being entered" — could only be
stated as a run-time refusal, because no type could express it. This one is
expressed by the type.
"""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, AsyncIterator


class Channels:
    """A handle with a lifecycle. Subclass it, and write `open` and `close`."""

    #: Held only while `lifespan` is active. A class attribute rather than a
    #: field, so that a subclass writing its own `__init__` — which every one
    #: of them does — is never obliged to call `super().__init__()`.
    _stack: AsyncExitStack | None = None

    async def open(self) -> None:
        """Called once, before the first request. Nothing by default.

        A handle that cannot be opened fails here, on the way up, in front of
        whoever started the server rather than in front of the first caller
        who needed it.
        """

    async def close(self) -> None:
        """Called once, after the last request. Nothing by default.

        Anything put on the stack by `enter` is unwound after this returns, so
        this is for what the stack cannot do. Clearing this object's own
        references is worth doing here: a call that somehow arrives after
        shutdown then meets `None`, which fails legibly, rather than a closed
        session, which fails somewhere deep inside somebody else's client.
        """

    async def enter(self, manager: Any) -> Any:
        """Open one async context manager and hand back what it yields.

        Valid only inside `open`. What is entered here is closed on the way
        out, in reverse order, whether the way out is an ordinary shutdown or
        an exception raised by the next `enter` in the same `open`.
        """

        if self._stack is None:
            raise RuntimeError(
                "Channels.enter() was called outside open(). The exit stack "
                "exists only while this handle is being served, so anything "
                "entered outside it would never be closed."
            )
        return await self._stack.enter_async_context(manager)

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator["Channels"]:
        """Hold this handle open. **The framework calls this, not you.**

        `provisioned` is the only caller. It is a method rather than a free
        function so that a subclass with an unusual lifecycle can override it,
        and so that the stack it manages is this object's own.
        """

        async with AsyncExitStack() as stack:
            self._stack = stack
            try:
                # `close` is paired with a *successful* `open`, the way
                # `__exit__` is paired with `__enter__`. An `open` that failed
                # part way leaves whatever it did enter to the stack below,
                # which unwinds it in reverse — so `close` never has to be
                # written to tolerate a half-opened object.
                await self.open()
                try:
                    yield self
                finally:
                    # Ordered deliberately: `close` runs while everything
                    # `enter` put on the stack is still open, because a session
                    # being closed is exactly what a `close` is most likely to
                    # need.
                    await self.close()
            finally:
                self._stack = None


@asynccontextmanager
async def provisioned(handle: Any) -> AsyncIterator[Any]:
    """Hold a deployment handle open for as long as it is being served.

    The one thing the framework asks about a handle: whether it has a lifecycle
    to run. A `Channels` subclass is opened before the first request and closed
    after the last; a plain value has nothing to open, so it is yielded as it
    is and a caller is spared having to ask which kind it is holding.

    Two callers, for two audiences. `ControllerManager` runs it for a test
    driving registration directly; `Index` runs it on the served path, over the
    same handle it captured when it was compiled. Both are the same six lines,
    which is why they are these six lines and not two copies.
    """

    if not isinstance(handle, Channels):
        yield handle
        return
    async with handle.lifespan() as opened:
        yield opened


__all__ = ["Channels", "provisioned"]
