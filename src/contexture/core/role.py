"""Composite role objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Iterable

from . import declarative
from .binding import MCPBinding
from .context import CompileLevel, ContextNode
from .errors import (
    CapabilityDeniedError,
    DeclarationError,
    DuplicateNameError,
    ModelValidationError,
    NodeNotFoundError,
)
from .resources import Resource
from .skill import Skill
from .tools import Tool
from .types import CompiledContext


@dataclass(slots=True, kw_only=True)
class Role(ContextNode):
    """A responsibility boundary composed from roles, skills, and MCP grants.

    Build one imperatively::

        Role(name="k8s-operator", description="...", instructions="...")

    or declare one as a class, which is how a business project states a role it
    owns::

        class KubernetesOperator(Role):
            '''Operate and diagnose Kubernetes workloads.'''

            instructions = "Inspect before changing the cluster."

            diagnose = DiagnoseDeployment
            cluster = MCPBinding(server=kubernetes, allowed_tools=["get_pods"])

    Subclassing states what one role *is*. It never states containment: a role
    that coordinates other roles holds them in `children`, whether it was
    declared or assembled at runtime.
    """

    instructions: str
    children: list[Role] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)
    tools: list[Tool] = field(default_factory=list)
    resources: list[Resource] = field(default_factory=list)
    mcp_bindings: list[MCPBinding] = field(default_factory=list)

    kind: ClassVar[str] = "role"

    #: The class-body declaration, or None on an imperatively built Role.
    declaration: ClassVar[declarative.Declaration | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        # A zero-argument super() raises TypeError in this method: dataclass
        # slots=True rebuilds the class object, so the implicit __class__ cell
        # still points at the discarded original. Name the class explicitly.
        super(Role, cls).__init_subclass__(**kwargs)
        if not declarative.is_declarative(cls, Role):
            return
        declaration = declarative.collect(
            cls,
            member_types=(Role, Skill, Tool, Resource, MCPBinding),
        )
        _validate_declaration(cls, declaration)
        cls.declaration = declaration
        cls.__init__ = _declarative_init  # type: ignore[method-assign]

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
            (tool.name for tool in self.tools),
            "tool names",
        )
        self._require_unique(
            (resource.uri for resource in self.resources),
            "resource URIs",
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

    def get_tool(self, name: str) -> Tool:
        for tool in self.tools:
            if tool.name == name:
                return tool
        raise NodeNotFoundError(
            f"Tool {name!r} was not found on role {self.name!r}."
        )

    def get_resource(self, uri: str) -> Resource:
        for resource in self.resources:
            if resource.uri == uri:
                return resource
        raise NodeNotFoundError(
            f"Resource {uri!r} was not found on role {self.name!r}."
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
            "available_tools": [
                tool.compile(CompileLevel.ROUTE) for tool in self.tools
            ],
            "available_resources": [
                resource.compile(CompileLevel.ROUTE)
                for resource in self.resources
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


def _validate_declaration(
    cls: type,
    declaration: declarative.Declaration,
) -> None:
    """Reject a contradictory class body while the class is being created.

    These are the collisions a reader cannot see by looking at one attribute,
    so they are worth catching at import rather than at the first instantiation
    somewhere else in the program.
    """

    if declaration.instructions is None:
        raise DeclarationError(
            f"{cls.__name__} must state `instructions`; a Role without them "
            "has nothing to disclose once it becomes the active role."
        )

    declarative.require_unique(
        {
            member.attribute: member.value.name
            for member in declaration.members
            if isinstance(member.value, Skill)
        },
        owner=cls.__name__,
        label="skills",
    )
    declarative.require_unique(
        {
            member.attribute: member.value.name
            for member in declaration.members
            if isinstance(member.value, Role)
        },
        owner=cls.__name__,
        label="child roles",
    )
    declarative.require_unique(
        {
            member.attribute: member.value.name
            for member in declaration.members
            if isinstance(member.value, Tool)
        },
        owner=cls.__name__,
        label="tools",
    )
    declarative.require_unique(
        {
            member.attribute: member.value.uri
            for member in declaration.members
            if isinstance(member.value, Resource)
        },
        owner=cls.__name__,
        label="resources",
    )
    declarative.require_unique(
        {
            member.attribute: member.value.server.server_id
            for member in declaration.members
            if isinstance(member.value, MCPBinding)
        },
        owner=cls.__name__,
        label="MCP server bindings",
    )


def _declarative_init(self: Role, **overrides: Any) -> None:
    """Build a declared Role, letting the caller override any stated field."""

    declaration = type(self).declaration
    assert declaration is not None  # set by __init_subclass__ before rebinding
    Role.__init__(
        self,
        **{
            "name": declaration.name,
            "description": declaration.description,
            "instructions": declaration.instructions,
            "children": list(declaration.of_type(Role)),
            "skills": list(declaration.of_type(Skill)),
            "tools": list(declaration.of_type(Tool)),
            "resources": list(declaration.of_type(Resource)),
            "mcp_bindings": list(declaration.of_type(MCPBinding)),
            **overrides,
        },
    )
