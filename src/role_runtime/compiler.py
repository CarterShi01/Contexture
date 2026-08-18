"""The unified progressive compiler for role context."""

from __future__ import annotations

from dataclasses import dataclass, field

from .context import CompileLevel
from .errors import ModelValidationError
from .role import Role
from .types import CompiledContext


@dataclass(slots=True, frozen=True, kw_only=True)
class CapabilitySelection:
    """Capabilities that should move from route metadata to active details."""

    skill_names: tuple[str, ...] = ()
    tool_refs: tuple[str, ...] = ()
    data_refs: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.skill_names or self.tool_refs or self.data_refs)


@dataclass(slots=True, frozen=True, kw_only=True)
class CompileRequest:
    """A request to compile one role at one disclosure level."""

    level: CompileLevel = CompileLevel.ACTIVE
    selection: CapabilitySelection = field(default_factory=CapabilitySelection)


@dataclass(slots=True, frozen=True, kw_only=True)
class CompiledRoleContext:
    """The terminal intermediate representation passed toward an LLM host."""

    role: CompiledContext
    activated_skills: tuple[CompiledContext, ...] = ()
    activated_mcp_tools: tuple[CompiledContext, ...] = ()
    activated_data_sources: tuple[CompiledContext, ...] = ()

    def to_dict(self) -> CompiledContext:
        return {
            "role": self.role,
            "activated_capabilities": {
                "skills": list(self.activated_skills),
                "mcp_tools": list(self.activated_mcp_tools),
                "data_sources": list(self.activated_data_sources),
            },
        }


@dataclass(slots=True)
class RoleCompiler:
    """Compile roles without recursively expanding the complete object graph."""

    def compile(
        self,
        role: Role,
        request: CompileRequest | None = None,
    ) -> CompiledRoleContext:
        normalized = request or CompileRequest()

        if normalized.level is CompileLevel.ROUTE:
            if not normalized.selection.is_empty:
                raise ModelValidationError(
                    "A route-level compile request cannot activate capabilities."
                )
            return CompiledRoleContext(role=role.compile(CompileLevel.ROUTE))

        activated_skills = tuple(
            role.get_skill(name).compile(CompileLevel.ACTIVE)
            for name in normalized.selection.skill_names
        )

        activated_tools: list[CompiledContext] = []
        for tool_ref in normalized.selection.tool_refs:
            binding = role.get_mcp_binding_for_tool_ref(tool_ref)
            activated_tools.append(
                binding.compile_tool_ref(tool_ref, CompileLevel.ACTIVE)
            )

        activated_data = tuple(
            role.get_data_binding(source_ref).compile_source(CompileLevel.ACTIVE)
            for source_ref in normalized.selection.data_refs
        )

        return CompiledRoleContext(
            role=role.compile(CompileLevel.ACTIVE),
            activated_skills=activated_skills,
            activated_mcp_tools=tuple(activated_tools),
            activated_data_sources=activated_data,
        )
