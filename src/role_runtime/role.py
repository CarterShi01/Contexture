"""Composite role objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Iterable

from .context import CompileLevel, ContextNode
from .errors import (
    CapabilityDeniedError,
    DuplicateNameError,
    ModelValidationError,
    NodeNotFoundError,
)
from .mcp.binding import MCPBinding
from .skill import Skill
from .types import CompiledContext


@dataclass(slots=True, kw_only=True)
class Role(ContextNode):
    """A responsibility boundary composed from roles, skills, and MCP grants."""

    instructions: str
    children: list[Role] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)
    mcp_bindings: list[MCPBinding] = field(default_factory=list)

    kind: ClassVar[str] = "role"

    def __post_init__(self) -> None:
        ContextNode.__post_init__(self)
        if not self.instructions.strip():
            raise ModelValidationError(
                f"Role {self.name!r} must have active instructions."
            )
        self._require_unique(
            (child.name for child in self.children),
            "child role names",
        )
        self._require_unique(
            (skill.name for skill in self.skills),
            "skill names",
        )
        self._require_unique(
            (binding.server.server_id for binding in self.mcp_bindings),
            "MCP server bindings",
        )

    @staticmethod
    def _require_unique(values: Iterable[str], label: str) -> None:
        materialized = list(values)
        if len(materialized) != len(set(materialized)):
            raise DuplicateNameError(f"A role contains duplicate {label}.")

    def get_child(self, name: str) -> Role:
        for child in self.children:
            if child.name == name:
                return child
        raise NodeNotFoundError(
            f"Child role {name!r} was not found under role {self.name!r}."
        )

    def get_skill(self, name: str) -> Skill:
        for skill in self.skills:
            if skill.name == name:
                return skill
        raise NodeNotFoundError(
            f"Skill {name!r} was not found on role {self.name!r}."
        )

    def get_mcp_binding(self, server_id: str) -> MCPBinding:
        for binding in self.mcp_bindings:
            if binding.server.server_id == server_id:
                return binding
        raise NodeNotFoundError(
            f"MCP server binding {server_id!r} was not found on role {self.name!r}."
        )

    def get_mcp_binding_for_tool_ref(self, tool_ref: str) -> MCPBinding:
        binding = self._binding_from_ref(tool_ref, "Tool", "<server_id>/<tool_name>")
        binding.require_tool_ref(tool_ref)
        return binding

    def get_mcp_binding_for_resource_ref(self, resource_ref: str) -> MCPBinding:
        binding = self._binding_from_ref(
            resource_ref,
            "Resource",
            "<server_id>/<uri>",
        )
        binding.require_resource_ref(resource_ref)
        return binding

    def _binding_from_ref(self, ref: str, label: str, shape: str) -> MCPBinding:
        """Resolve the binding behind a host reference on an authorization path.

        A role with no binding to the named server is denied rather than
        reported as a lookup miss, so every refusal reaching a host through
        get_mcp_binding_for_* is a single exception type.
        """

        server_id, separator, remainder = ref.partition("/")
        if not separator or not server_id or not remainder:
            raise NodeNotFoundError(
                f"{label} reference {ref!r} must use {shape!r}."
            )
        try:
            return self.get_mcp_binding(server_id)
        except NodeNotFoundError as exc:
            raise CapabilityDeniedError(
                f"Role {self.name!r} has no binding for server {server_id!r}, so "
                f"{label.lower()} {ref!r} is not granted."
            ) from exc

    def _compile_active(self) -> CompiledContext:
        return {
            **self._compile_route(),
            "instructions": self.instructions,
            "available_sub_roles": [
                child.compile(CompileLevel.ROUTE) for child in self.children
            ],
            "available_skills": [
                skill.compile(CompileLevel.ROUTE) for skill in self.skills
            ],
            "available_mcp_tools": [
                tool_route
                for binding in self.mcp_bindings
                for tool_route in binding.compile_tool_routes()
            ],
            "available_mcp_resources": [
                resource_route
                for binding in self.mcp_bindings
                for resource_route in binding.compile_resource_routes()
            ],
        }
