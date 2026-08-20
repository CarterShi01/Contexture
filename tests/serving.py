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

from dataclasses import dataclass
from typing import Any, Sequence

from contexture.core.model.manager import ControllerManager, register_root
from contexture.server import Assembly, ContextureServer, TypeHintBinding


@dataclass(frozen=True, slots=True)
class Marked:
    """A binding whose schema says which tool it was derived for.

    For the tests asking whether a schema travelled from the binding to the
    card, rather than what a real derivation produces — those live in
    `test_binding.py` and use the SDK-backed one.
    """

    tool: Any

    @property
    def schema(self) -> dict[str, Any]:
        return {"tool": self.tool.name}

    async def call(self, arguments: Any, context: Any = None) -> Any:
        return await self.tool.invoke(**(arguments or {}))


def assemble(
    roots: Any,
    *,
    published: Sequence[Any] = (),
    channels: Any = None,
    bind: Any = TypeHintBinding,
) -> Assembly:
    """Seal one graph. `roots` is one root or many, class or instance.

    `bind` is named only by the tests asking what a binding does. Everywhere
    else it is an implementation detail of sealing.
    """

    manager = ControllerManager(channels=channels)
    for root in _each(roots):
        register_root(manager, root)
    return Assembly.of(manager.sealed(bind=bind), published=published)


def serve(
    roots: Any,
    *,
    published: Sequence[Any] = (),
    channels: Any = None,
    bind: Any = TypeHintBinding,
    name: str = "test",
    **kwargs: Any,
) -> ContextureServer:
    """The same, wrapped in the server that would put it on a wire."""

    return ContextureServer(
        assemble(roots, published=published, channels=channels, bind=bind),
        name=name,
        **kwargs,
    )


def _each(given: Any) -> tuple[Any, ...]:
    """One root or many, told apart without making a caller say which."""

    if isinstance(given, type) or hasattr(given, "kind"):
        return (given,)
    return tuple(given)
