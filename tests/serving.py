"""Register, seal and serve — `main()`'s three steps, for a test.

Not part of the framework. A business `main()` writes these five lines out in
full, because every object in them is one it makes a decision about; a test
makes the same decisions the same way every time, so it says so once here.

    server = serve(Responder)                    # one root, nothing published
    server = serve(Responder, published=(DOC,))  # …and one document

`assembly` and `tree` are reachable from what comes back, which is what the
tests that used to read `app.tree` want.
"""

from __future__ import annotations

from typing import Any, Sequence

from contexture.core.model.manager import ControllerManager, register_root
from contexture.server import Assembly, ContextureServer, Dispatch


def assemble(
    roots: Any,
    *,
    published: Sequence[Any] = (),
    channels: Any = None,
    dispatch: Dispatch | None = None,
) -> Assembly:
    """Seal one graph. `roots` is one root or many, class or instance.

    `dispatch` is passed in only by the tests that hold it afterwards — the
    ones asking what its cache does. Everywhere else it is an implementation
    detail of sealing.
    """

    manager = ControllerManager(channels=channels)
    for root in _each(roots):
        register_root(manager, root)
    dispatch = Dispatch() if dispatch is None else dispatch
    return Assembly.of(
        manager.sealed(schema_of=dispatch.schema),
        execute=dispatch.execute,
        published=published,
    )


def serve(
    roots: Any,
    *,
    published: Sequence[Any] = (),
    channels: Any = None,
    dispatch: Dispatch | None = None,
    name: str = "test",
    **kwargs: Any,
) -> ContextureServer:
    """The same, wrapped in the server that would put it on a wire."""

    return ContextureServer(
        assemble(
            roots, published=published, channels=channels, dispatch=dispatch
        ),
        name=name,
        **kwargs,
    )


def _each(given: Any) -> tuple[Any, ...]:
    """One root or many, told apart without making a caller say which."""

    if isinstance(given, type) or hasattr(given, "kind"):
        return (given,)
    return tuple(given)
