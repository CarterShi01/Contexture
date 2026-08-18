"""Least-privilege bindings between roles and MCP servers."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..context import CompileLevel
from ..errors import CapabilityDeniedError, DuplicateNameError, ModelValidationError
from ..types import CompiledContext
from .models import MCPServer, MCPTool


@dataclass(slots=True, kw_only=True)
class MCPBinding:
    """A role-specific projection of one server's tool catalog.

    allowed_tools is the authorization allowlist. read_only_tools is a trusted
    host classification used by RoleRuntime to decide whether explicit approval
    is required. Protocol ToolAnnotations are not used for authorization.
    """

    server: MCPServer
    allowed_tools: list[str] = field(default_factory=list)
    read_only_tools: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._validate_unique(self.allowed_tools, "allowed_tools")
        self._validate_unique(self.read_only_tools, "read_only_tools")

        unknown = [
            tool_name
            for tool_name in self.allowed_tools
            if not self.server.has_tool(tool_name)
        ]
        if unknown:
            raise ModelValidationError(
                f"Binding for server {self.server.server_id!r} references "
                f"unknown tools: {unknown}."
            )

        ungranted_read_only = [
            tool_name
            for tool_name in self.read_only_tools
            if tool_name not in self.allowed_tools
        ]
        if ungranted_read_only:
            raise ModelValidationError(
                "read_only_tools must be a subset of allowed_tools; invalid "
                f"entries: {ungranted_read_only}."
            )

    @staticmethod
    def _validate_unique(values: list[str], field_name: str) -> None:
        if len(values) != len(set(values)):
            raise DuplicateNameError(f"{field_name} contains duplicate tool names.")
        if any(not value.strip() for value in values):
            raise ModelValidationError(f"{field_name} contains an empty tool name.")

    def is_tool_allowed(self, tool_name: str) -> bool:
        return tool_name in self.allowed_tools

    def is_tool_read_only(self, tool_name: str) -> bool:
        self.require_tool(tool_name)
        return tool_name in self.read_only_tools

    def require_tool(self, tool_name: str) -> MCPTool:
        if not self.is_tool_allowed(tool_name):
            raise CapabilityDeniedError(
                f"Tool {tool_name!r} is not allowed by the binding for server "
                f"{self.server.server_id!r}."
            )
        return self.server.get_tool(tool_name)

    def require_tool_ref(self, tool_ref: str) -> MCPTool:
        tool_name = self.server.parse_tool_ref(tool_ref)
        return self.require_tool(tool_name)

    def compile_tool_routes(self) -> list[CompiledContext]:
        return [
            self.server.compile_tool(tool_name, CompileLevel.ROUTE)
            for tool_name in self.allowed_tools
        ]

    def compile_tool(
        self,
        tool_name: str,
        level: CompileLevel | str = CompileLevel.ACTIVE,
    ) -> CompiledContext:
        self.require_tool(tool_name)
        compiled = self.server.compile_tool(tool_name, level)
        compiled["host_read_only"] = self.is_tool_read_only(tool_name)
        return compiled

    def compile_tool_ref(
        self,
        tool_ref: str,
        level: CompileLevel | str = CompileLevel.ACTIVE,
    ) -> CompiledContext:
        tool_name = self.server.parse_tool_ref(tool_ref)
        return self.compile_tool(tool_name, level)
