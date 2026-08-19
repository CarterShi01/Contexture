"""Render a role tree into the surface Codex reads.

Codex reads a single AGENTS.md. It has no per-skill artifact and no
nested-role concept, so this adapter flattens the tree into one document — and
says so, because a flattened surface loses the disclosure the model was built
to provide.
"""

from __future__ import annotations

from typing import ClassVar, Iterable

from ..core.role import Role
from .base import Artifact, TargetAdapter, TargetCapabilities, iter_roles
from .markdown import heading, render_capability_table, render_role_routes


class CodexAdapter(TargetAdapter):
    """Emit AGENTS.md."""

    name: ClassVar[str] = "codex"
    display_name: ClassVar[str] = "Codex"
    capabilities: ClassVar[TargetCapabilities] = TargetCapabilities(
        separate_skill_files=False,
        progressive_disclosure=False,
        nested_roles=False,
    )

    agents_path: ClassVar[str] = "AGENTS.md"

    def _render_artifacts(
        self,
        role: Role,
    ) -> Iterable[Artifact]:
        yield Artifact(path=self.agents_path, content=self._agents(role))

    def _agents(self, role: Role) -> str:
        lines = [
            heading(1, role.name),
            "",
            role.description,
            "",
            role.instructions.strip(),
            "",
        ]

        root_table = render_capability_table(role, include_children=False)
        if root_table:
            lines += root_table + [""]

        if role.children:
            lines += [
                heading(2, "Areas of responsibility"),
                "",
                *render_role_routes(role.children),
                "",
            ]

        for node in iter_roles(role):
            if node is role:
                continue
            lines += [heading(2, node.name), "", node.description, ""]
            lines += [node.instructions.strip(), ""]
            for skill in node.skills:
                lines += [
                    heading(3, f"Skill: {skill.name}"),
                    "",
                    skill.description,
                    "",
                    skill.instructions.strip(),
                    "",
                ]
            table = render_capability_table(node, include_children=False)
            if table:
                lines += table + [""]

        for skill in role.skills:
            lines += [
                heading(2, f"Skill: {skill.name}"),
                "",
                skill.description,
                "",
                skill.instructions.strip(),
                "",
            ]

        return "\n".join(lines).rstrip() + "\n"
