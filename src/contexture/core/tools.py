"""Tools: the callable half of a catalog, remote and local.

`MCPTool` describes a tool a remote MCP server owns. `Tool` is a tool this
application owns and can execute itself.
"""

from __future__ import annotations

import inspect
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping

from . import declarative
from .coercion import optional_bool, optional_str
from .context import ContextNode
from .errors import ModelValidationError
from .types import CompiledContext, JsonObject


@dataclass(slots=True, frozen=True, kw_only=True)
class ToolAnnotations:
    """Protocol annotations retained as untrusted behavioral hints.

    These values are never used as the host's authorization source of truth.
    Trusted execution policy belongs to MCPBinding and the execution layer.
    """

    title: str | None = None
    read_only_hint: bool | None = None
    destructive_hint: bool | None = None
    idempotent_hint: bool | None = None
    open_world_hint: bool | None = None

    def to_protocol_dict(self) -> JsonObject:
        result: JsonObject = {}
        if self.title is not None:
            result["title"] = self.title
        if self.read_only_hint is not None:
            result["readOnlyHint"] = self.read_only_hint
        if self.destructive_hint is not None:
            result["destructiveHint"] = self.destructive_hint
        if self.idempotent_hint is not None:
            result["idempotentHint"] = self.idempotent_hint
        if self.open_world_hint is not None:
            result["openWorldHint"] = self.open_world_hint
        return result

    @classmethod
    def from_protocol_dict(
        cls,
        payload: Mapping[str, Any] | None,
    ) -> ToolAnnotations | None:
        if payload is None:
            return None
        return cls(
            title=optional_str(payload.get("title")),
            read_only_hint=optional_bool(payload.get("readOnlyHint")),
            destructive_hint=optional_bool(payload.get("destructiveHint")),
            idempotent_hint=optional_bool(payload.get("idempotentHint")),
            open_world_hint=optional_bool(payload.get("openWorldHint")),
        )


@dataclass(slots=True, kw_only=True)
class MCPTool(ContextNode):
    """A protocol-compatible description of a callable MCP tool."""

    input_schema: JsonObject
    title: str | None = None
    output_schema: JsonObject | None = None
    annotations: ToolAnnotations | None = None
    meta: JsonObject = field(default_factory=dict)

    kind: ClassVar[str] = "mcp_tool"

    def __post_init__(self) -> None:
        ContextNode.__post_init__(self)
        if self.input_schema.get("type") != "object":
            raise ModelValidationError(
                f"MCP tool {self.name!r} must have inputSchema.type == 'object'."
            )

    @property
    def display_name(self) -> str:
        if self.title:
            return self.title
        if self.annotations and self.annotations.title:
            return self.annotations.title
        return self.name

    def _compile_active(self) -> CompiledContext:
        compiled: CompiledContext = {
            **self._compile_route(),
            "inputSchema": deepcopy(self.input_schema),
        }
        if self.title is not None:
            compiled["title"] = self.title
        if self.output_schema is not None:
            compiled["outputSchema"] = deepcopy(self.output_schema)
        if self.annotations is not None:
            compiled["annotations"] = self.annotations.to_protocol_dict()
        if self.meta:
            compiled["_meta"] = deepcopy(self.meta)
        return compiled

    def to_protocol_dict(self) -> JsonObject:
        """Return the protocol Tool shape without host-only routing fields."""

        payload: JsonObject = {
            "name": self.name,
            "description": self.description,
            "inputSchema": deepcopy(self.input_schema),
        }
        if self.title is not None:
            payload["title"] = self.title
        if self.output_schema is not None:
            payload["outputSchema"] = deepcopy(self.output_schema)
        if self.annotations is not None:
            payload["annotations"] = self.annotations.to_protocol_dict()
        if self.meta:
            payload["_meta"] = deepcopy(self.meta)
        return payload

    @classmethod
    def from_protocol_dict(cls, payload: Mapping[str, Any]) -> MCPTool:
        name = payload.get("name")
        if not isinstance(name, str) or not name:
            raise ModelValidationError(
                "MCP Tool payload must contain a non-empty name."
            )

        raw_schema = payload.get("inputSchema")
        if not isinstance(raw_schema, dict):
            raise ModelValidationError(
                f"MCP tool {name!r} must contain an object inputSchema."
            )

        raw_output = payload.get("outputSchema")
        if raw_output is not None and not isinstance(raw_output, dict):
            raise ModelValidationError(
                f"MCP tool {name!r} outputSchema must be an object when present."
            )

        raw_annotations = payload.get("annotations")
        if raw_annotations is not None and not isinstance(raw_annotations, dict):
            raise ModelValidationError(
                f"MCP tool {name!r} annotations must be an object when present."
            )

        raw_meta = payload.get("_meta", {})
        if not isinstance(raw_meta, dict):
            raise ModelValidationError(
                f"MCP tool {name!r} _meta must be an object when present."
            )

        description = payload.get("description")
        if not isinstance(description, str) or not description.strip():
            description = f"Invoke the MCP tool named {name}."

        return cls(
            name=name,
            description=description,
            title=optional_str(payload.get("title")),
            input_schema=deepcopy(raw_schema),
            output_schema=deepcopy(raw_output),
            annotations=ToolAnnotations.from_protocol_dict(raw_annotations),
            meta=deepcopy(raw_meta),
        )


@dataclass(slots=True, kw_only=True)
class Tool(ContextNode):
    """A locally implemented capability that Contexture itself can execute.

    `MCPTool` above describes somebody else's tool: it carries a hand-written
    `input_schema` because the catalog belongs to a remote server. `Tool` is the
    other half — a capability this application owns, stated as a typed Python
    method::

        class GetPodLogs(Tool):
            '''Return recent container logs for one Pod.'''

            read_only = True

            async def invoke(self, namespace: str, pod: str) -> str:
                ...

    The parameter schema is never written by hand. It is derived from
    `invoke`'s type hints when the tool is projected onto an MCP surface, which
    is why nothing in this layer needs to know what JSON Schema looks like.

    `read_only` is a trusted host classification, not an agent-supplied
    argument. It is projected onto the protocol's `readOnlyHint` annotation so a
    host can decide whether to ask a human before running the tool, and it must
    never appear in the tool's input schema.
    """

    kind: ClassVar[str] = "tool"

    #: Whether running this tool leaves the world unchanged.
    read_only: ClassVar[bool] = False

    #: The class-body declaration, or None on an imperatively built Tool.
    declaration: ClassVar[declarative.Declaration | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        # A zero-argument super() raises TypeError in this method: dataclass
        # slots=True rebuilds the class object, so the implicit __class__ cell
        # still points at the discarded original. Name the class explicitly.
        super(Tool, cls).__init_subclass__(**kwargs)
        if not declarative.is_declarative(cls, Tool):
            return
        cls.declaration = declarative.collect(cls, member_types=())
        cls.__init__ = _declarative_tool_init  # type: ignore[method-assign]

    async def invoke(self, **arguments: Any) -> Any:
        """Execute the capability. Business subclasses state real parameters."""

        raise NotImplementedError(
            f"Tool {self.name!r} does not implement invoke()."
        )

    def parameters(self) -> tuple[str, ...]:
        """Return the parameter names `invoke` accepts, in declaration order.

        This is the routing-level answer to "what does this tool need?". The
        full JSON Schema lives on the MCP surface, which a connected agent
        already has; repeating it inside a disclosure payload would spend
        context on something the host has handed over anyway.
        """

        signature = inspect.signature(type(self).invoke)
        return tuple(
            name
            for name, parameter in signature.parameters.items()
            if name != "self"
            and parameter.kind
            not in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD)
        )

    def _compile_active(self) -> CompiledContext:
        return {
            **self._compile_route(),
            "parameters": list(self.parameters()),
            "read_only": self.read_only,
        }


def _declarative_tool_init(self: Tool, **overrides: Any) -> None:
    """Build a declared Tool, letting the caller override any stated field."""

    declaration = type(self).declaration
    assert declaration is not None  # set by __init_subclass__ before rebinding
    Tool.__init__(
        self,
        **{
            "name": declaration.name,
            "description": declaration.description,
            **overrides,
        },
    )
