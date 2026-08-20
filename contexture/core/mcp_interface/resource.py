"""What this server exposes on MCP's **resource** primitive.

Resources are the application-controlled primitive. The host decides how one is
taken up — it may offer it to a person to pick, or attach it on its own; the
specification does not say which, and neither does this module.

A resource here **owns no content**. It names a node in the tree, and the tree
stays the single place a capability lives. That is what keeps this plane from
becoming a second declaration that drifts from the first: reaching one document
two ways and being told two different things is worse than either answer alone.

What it names must be a read-only tool that takes no arguments. Content that is
already there, fetched rather than computed, is exactly the shape a resource
needs — and stating it as an ordinary tool means the model can reach the same
content by navigating, without a second kind of node existing to hold it.

Declaration only. `server` decides how a read reaches the wire.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from ..errors import DeclarationError, ModelValidationError


@dataclass(slots=True, kw_only=True)
class Resource:
    """One node in the tree, published at a URI a host can take up.

    ::

        CRASH_LOOP_RUNBOOK = Resource(
            opens="kubernetes-platform/incident-response/crash_loop_runbook",
            uri="contexture://runbooks/crash-loop-backoff",
            mime_type="text/markdown",
            description="How to diagnose a container that keeps restarting.",
        )

    This is not a `ContextNode` and deliberately does not inherit from one. A
    node is disclosed to a model over a compile lifecycle; this is an address
    a host may fetch. Keeping the two in separate type hierarchies is what
    stops them from being quietly treated as one concept — the mistake that a
    shared name has already caused once here.
    """

    #: The reference of the read-only, argument-less tool that produces this
    #: content. A **string**, never an object: a `str` cannot be walked into,
    #: so nothing on this plane can reach into the forest and nothing in the
    #: forest can reach back. Resolved when the server is built, never here —
    #: this layer does not know what a separator is.
    opens: str

    #: The address a host publishes this at. Unlike a reference, it does not
    #: change when the node it names is moved to another role, which is the
    #: whole reason a document gets a second name.
    uri: str

    #: What a host shows about it.
    description: str

    #: Defaults to the last segment of `opens`.
    name: str | None = None

    mime_type: str | None = None

    kind: ClassVar[str] = "resource"

    def __init_subclass__(cls, **kwargs: object) -> None:
        # Never fires for `Resource` itself. `@dataclass(slots=True)` rebuilds
        # the class object, and the rebuilt one is created with `(object,)` as
        # its bases — so it is `object.__init_subclass__` that runs, not this.
        # The same rebuild is why `Role` and its siblings name their class
        # explicitly in `super()`; see `docs/02-framework-layers.md` §4.5.
        raise DeclarationError(
            f"{cls.__name__} subclasses Resource, which is constructed rather "
            "than subclassed: Resource(opens=..., uri=...). A resource holds "
            "no content — the content is a read-only Tool taking no arguments, "
            "and the resource gives that tool a second address. Subclassing "
            "one produces a class the tree can never hold."
        )

    def __post_init__(self) -> None:
        if not self.opens.strip():
            raise ModelValidationError(
                "A resource must name the node it publishes, in `opens`."
            )
        if not self.uri.strip():
            raise ModelValidationError(
                f"Resource {self.opens!r} must have a non-empty URI; a "
                "resource without one cannot be addressed."
            )
        if not self.description.strip():
            raise ModelValidationError(
                f"Resource {self.opens!r} must have a description."
            )


__all__ = ["Resource"]
