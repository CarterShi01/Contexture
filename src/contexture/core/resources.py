"""Resources: the readable half of a catalog, remote and local.

`MCPResource` describes a resource a remote MCP server owns. `Resource` is
content this application owns and can read itself.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping

from . import declarative
from .coercion import optional_str
from .context import ContextNode
from .errors import DeclarationError, ModelValidationError
from .types import CompiledContext, JsonObject


@dataclass(slots=True, kw_only=True)
class MCPResource(ContextNode):
    """A protocol-compatible description of one readable MCP resource.

    A resource is a descriptor, never the content itself. Compiling a resource
    at any level yields metadata only; the bytes are fetched through
    resources/read after the execution layer authorizes the access.
    """

    uri: str
    title: str | None = None
    mime_type: str | None = None
    size: int | None = None
    meta: JsonObject = field(default_factory=dict)

    kind: ClassVar[str] = "mcp_resource"

    def __post_init__(self) -> None:
        ContextNode.__post_init__(self)
        if not self.uri.strip():
            raise ModelValidationError(
                f"MCP resource {self.name!r} must have a non-empty URI."
            )
        if self.size is not None and (
            isinstance(self.size, bool) or self.size < 0
        ):
            raise ModelValidationError(
                f"MCP resource {self.name!r} size must be a non-negative integer."
            )

    @property
    def display_name(self) -> str:
        return self.title or self.name

    def _compile_active(self) -> CompiledContext:
        compiled: CompiledContext = {
            **self._compile_route(),
            "uri": self.uri,
        }
        if self.title is not None:
            compiled["title"] = self.title
        if self.mime_type is not None:
            compiled["mimeType"] = self.mime_type
        if self.size is not None:
            compiled["size"] = self.size
        if self.meta:
            compiled["_meta"] = deepcopy(self.meta)
        return compiled

    def to_protocol_dict(self) -> JsonObject:
        """Return the protocol Resource shape without host-only routing fields."""

        payload: JsonObject = {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
        }
        if self.title is not None:
            payload["title"] = self.title
        if self.mime_type is not None:
            payload["mimeType"] = self.mime_type
        if self.size is not None:
            payload["size"] = self.size
        if self.meta:
            payload["_meta"] = deepcopy(self.meta)
        return payload

    @classmethod
    def from_protocol_dict(cls, payload: Mapping[str, Any]) -> MCPResource:
        uri = payload.get("uri")
        if not isinstance(uri, str) or not uri:
            raise ModelValidationError(
                "MCP Resource payload must contain a non-empty uri."
            )

        name = payload.get("name")
        if not isinstance(name, str) or not name:
            raise ModelValidationError(
                f"MCP resource {uri!r} must contain a non-empty name."
            )

        raw_size = payload.get("size")
        if raw_size is not None and (
            isinstance(raw_size, bool) or not isinstance(raw_size, int)
        ):
            raise ModelValidationError(
                f"MCP resource {uri!r} size must be an integer when present."
            )

        raw_meta = payload.get("_meta", {})
        if not isinstance(raw_meta, dict):
            raise ModelValidationError(
                f"MCP resource {uri!r} _meta must be an object when present."
            )

        description = payload.get("description")
        if not isinstance(description, str) or not description.strip():
            description = f"Read the MCP resource addressed by {uri}."

        return cls(
            name=name,
            description=description,
            uri=uri,
            title=optional_str(payload.get("title")),
            mime_type=optional_str(payload.get("mimeType")),
            size=raw_size,
            meta=deepcopy(raw_meta),
        )


@dataclass(slots=True, kw_only=True)
class Resource(ContextNode):
    """A locally implemented resource this application can read on demand.

    `MCPResource` above describes a resource a remote server owns. `Resource` is
    the other half — content this application produces itself::

        class CrashLoopRunbook(Resource):
            '''Runbook for diagnosing CrashLoopBackOff.'''

            uri = "contexture://runbooks/crash-loop-backoff"
            mime_type = "text/markdown"

            async def read(self) -> str:
                ...

    The descriptor/content split that `MCPResource` documents holds here too,
    and for the same reason: listing a resource must stay cheap. `read()` runs
    only when something actually asks for the bytes, so discovering a hundred
    runbooks costs a hundred descriptions, not a hundred documents.
    """

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
        compiled: CompiledContext = {
            **self._compile_route(),
            "uri": self.uri,
        }
        if self.mime_type is not None:
            compiled["mimeType"] = self.mime_type
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
