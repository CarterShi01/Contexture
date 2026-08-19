"""Render a role tree into the surface Claude Code reads.

Claude Code is the richest of the three built-in targets: it reads a project
memory file and discovers skills as individual directories. That means a role
tree survives this target with most of its shape intact — nested roles and
per-skill disclosure both land as real, separate units.
"""

from __future__ import annotations

from typing import ClassVar, Iterable

from ..core.registry import RoleRegistry
from ..core.role import Role
from .base import Artifact, TargetAdapter, TargetCapabilities, iter_roles
from .markdown import (
    front_matter,
    heading,
    render_capability_table,
    render_role_routes,
)


class ClaudeCodeAdapter(TargetAdapter):
    """Emit CLAUDE.md and one SKILL.md per skill."""

    name: ClassVar[str] = "claude-code"
    display_name: ClassVar[str] = "Claude Code"
    capabilities: ClassVar[TargetCapabilities] = TargetCapabilities(
        separate_skill_files=True,
        progressive_disclosure=True,
        nested_roles=True,
    )

    memory_path: ClassVar[str] = "CLAUDE.md"
    skills_root: ClassVar[str] = ".claude/skills"

    def _render_artifacts(
        self,
        role: Role,
        registry: RoleRegistry,
    ) -> Iterable[Artifact]:
        yield Artifact(path=self.memory_path, content=self._memory(role))

        for owner in iter_roles(role):
            for skill in owner.skills:
                yield Artifact(
                    path=f"{self.skills_root}/{skill.name}/SKILL.md",
                    content=self._skill(skill, owner),
                )

    def _memory(self, role: Role) -> str:
        lines = [
            heading(1, role.name),
            "",
            role.description,
            "",
            role.instructions.strip(),
            "",
        ]

        # Only the root's own grants belong here. Each child prints its own
        # table in its own section, and repeating them would tell the agent the
        # root may reach capabilities it was never granted.
        capabilities = render_capability_table(role, include_children=False)
        if capabilities:
            lines += [heading(2, "Granted capabilities"), "", *capabilities, ""]

        if role.skills:
            skill_names = ", ".join(f"`{skill.name}`" for skill in role.skills)
            lines += [f"Skills: {skill_names}.", ""]

        if role.children:
            lines += [
                heading(2, "Specialists"),
                "",
                "Route the request to the specialist that owns it, then work "
                "only from that specialist's section.",
                "",
                *render_role_routes(role.children),
                "",
            ]
            for child in role.children:
                lines += self._child_section(child)

        return "\n".join(lines).rstrip() + "\n"

    def _child_section(self, child: Role) -> list[str]:
        lines = [
            heading(3, child.name),
            "",
            child.description,
            "",
            child.instructions.strip(),
            "",
        ]
        if child.skills:
            skill_names = ", ".join(f"`{skill.name}`" for skill in child.skills)
            lines += [f"Skills: {skill_names}.", ""]
        capabilities = render_capability_table(child, include_children=False)
        if capabilities:
            lines += capabilities + [""]
        return lines

    def _skill(self, skill: object, owner: Role) -> str:
        body = front_matter(
            {
                "name": skill.name,  # type: ignore[attr-defined]
                "description": skill.description,  # type: ignore[attr-defined]
            }
        )
        body += "\n"
        body += heading(1, skill.name) + "\n\n"  # type: ignore[attr-defined]
        body += skill.instructions.strip() + "\n"  # type: ignore[attr-defined]
        body += f"\nDeclared by role `{owner.name}`.\n"
        return body
