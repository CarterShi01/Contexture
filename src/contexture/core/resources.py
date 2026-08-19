"""Resources: content this application owns and can read on demand."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from . import declarative
from .context import ContextNode
from .errors import DeclarationError, ModelValidationError
from .types import CompiledContext


@dataclass(slots=True, kw_only=True)
class Resource(ContextNode):
    """Content this application produces itself, read only when asked for.

    ::

        class CrashLoopRunbook(Resource):
            '''Runbook for diagnosing CrashLoopBackOff.'''

            uri = "contexture://runbooks/crash-loop-backoff"
            mime_type = "text/markdown"

            async def read(self) -> str:
                ...

    A resource is a descriptor until somebody asks for its bytes. Listing one
    must stay cheap, so `read()` runs only when something actually reads it:
    discovering a hundred runbooks costs a hundred descriptions, not a hundred
    documents.

    What makes something a Resource rather than a read-only Tool is that it is
    already there. A tool computes an answer from the arguments it is handed;
    a resource takes none, and two reads return the same document until the
    document itself changes. The practical consequence is addressing: only a
    resource can be named from outside the tree, which is why a skill's
    procedure can cite one by its own URI and be followed literally.
    """

    #: The resource's own name for itself, independent of where it hangs in
    #: the role tree. `tree.resource()` accepts either this or the tree
    #: reference, so a document can be cited the way its author would write it.
    uri: str
    mime_type: str | None = None

    kind: ClassVar[str] = "resource"

    #: The class-body declaration, or None on an imperatively built Resource.
    declaration: ClassVar[declarative.Declaration | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        # A zero-argument super() raises TypeError in this method: dataclass
        # slots=True rebuilds the class object, so the implicit __class__ cell
        # still points at the discarded original. Name the class explicitly.
        super(Resource, cls).__init_subclass__(**kwargs)
        if not declarative.is_declarative(cls, Resource):
            return
        cls.declaration = declarative.collect(cls, member_types=())
        cls.__init__ = _declarative_resource_init  # type: ignore[method-assign]

    def __post_init__(self) -> None:
        ContextNode.__post_init__(self)
        if not self.uri.strip():
            raise ModelValidationError(
                f"Resource {self.name!r} must have a non-empty URI."
            )

    async def read(self) -> str | bytes:
        """Return the resource content. Business subclasses implement this."""

        raise NotImplementedError(
            f"Resource {self.name!r} does not implement read()."
        )

    def _compile_active(self) -> CompiledContext:
        # `mime_type`, not the protocol's `mimeType`. This payload is not a
        # protocol resource descriptor — it travels inside a tool result, beside
        # `read_only` and `input_schema` — and the card a role hands out for
        # this same resource has always spelled it this way. Reaching one
        # resource two ways and being given two different key names for one
        # field is the same defect the tool payload was fixed for.
        compiled: CompiledContext = {
            **self._compile_route(),
            "uri": self.uri,
        }
        if self.mime_type is not None:
            compiled["mime_type"] = self.mime_type
        return compiled


def _declarative_resource_init(self: Resource, **overrides: Any) -> None:
    """Build a declared Resource, letting the caller override any stated field."""

    declaration = type(self).declaration
    assert declaration is not None  # set by __init_subclass__ before rebinding
    uri = declarative.scalar(type(self), "uri")
    if uri is None and "uri" not in overrides:
        raise DeclarationError(
            f"{declaration.owner} must state a `uri`; a Resource without one "
            "cannot be addressed."
        )
    Resource.__init__(
        self,
        **{
            "name": declaration.name,
            "description": declaration.description,
            "uri": uri,
            "mime_type": declarative.scalar(type(self), "mime_type"),
            **overrides,
        },
    )
