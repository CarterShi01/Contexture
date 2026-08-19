"""The unified progressive compiler for role context."""

from __future__ import annotations

from dataclasses import dataclass, field

from .core.context import CompileLevel
from .core.errors import ModelValidationError
from .core.role import Role
from .core.types import CompiledContext


@dataclass(slots=True, frozen=True, kw_only=True)
class CapabilitySelection:
    """Capabilities that should move from route metadata to active details."""

    skill_names: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.skill_names


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

    def to_dict(self) -> CompiledContext:
        return {
            "role": self.role,
            "activated_capabilities": {"skills": list(self.activated_skills)},
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

        return CompiledRoleContext(
            role=role.compile(CompileLevel.ACTIVE),
            activated_skills=tuple(
                role.get_skill(name).compile(CompileLevel.ACTIVE)
                for name in normalized.selection.skill_names
            ),
        )
