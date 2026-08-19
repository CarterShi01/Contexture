"""Render a role tree into the surface Cursor reads.

Cursor discovers rule files under .cursor/rules. Rules are individually
addressable, so skills survive as separate units, but a rule carries no
nesting: the role tree is flattened into sibling rule files whose names encode
the hierarchy.
"""

from __future__ import annotations

from typing import ClassVar, Iterable

from ..core.role import Role
from .base import Artifact, TargetAdapter, TargetCapabilities, iter_roles
from .markdown import (
    front_matter,
    heading,
    render_capability_table,
    render_role_routes,
)


class CursorAdapter(TargetAdapter):
    """Emit one .mdc rule per role and per skill."""

    name: ClassVar[str] = "cursor"
    display_name: ClassVar[str] = "Cursor"
    capabilities: ClassVar[TargetCapabilities] = TargetCapabilities(
        separate_skill_files=True,
        progressive_disclosure=True,
        nested_roles=False,
    )

    rules_root: ClassVar[str] = ".cursor/rules"

    def _render_artifacts(
        self,
        role: Role,
    ) -> Iterable[Artifact]:
        yield Artifact(
            path=f"{self.rules_root}/{role.name}.mdc",
            content=self._root_rule(role),
        )

        for node in iter_roles(role):
            if node is not role:
                yield Artifact(
                    path=f"{self.rules_root}/{node.name}.mdc",
                    content=self._role_rule(node),
                )
            for skill in node.skills:
                yield Artifact(
                    path=f"{self.rules_root}/skill-{skill.name}.mdc",
                    content=self._skill_rule(skill, node),
                )

    def _root_rule(self, role: Role) -> str:
        body = front_matter(
            {"description": role.description, "alwaysApply": "true"}
        )
        lines = ["", heading(1, role.name), "", role.instructions.strip(), ""]
        if role.children:
            lines += [
                heading(2, "Specialists"),
                "",
                *render_role_routes(role.children),
                "",
                "Each specialist has its own rule file; consult the one that "
                "owns the request.",
                "",
            ]
        table = render_capability_table(role, include_children=False)
        if table:
            lines += table + [""]
        return body + "\n".join(lines).rstrip() + "\n"

    def _role_rule(self, node: Role) -> str:
        body = front_matter(
            {"description": node.description, "alwaysApply": "false"}
        )
        lines = ["", heading(1, node.name), "", node.instructions.strip(), ""]
        if node.skills:
            skill_names = ", ".join(f"`skill-{s.name}`" for s in node.skills)
            lines += [f"Related rules: {skill_names}.", ""]
        table = render_capability_table(node, include_children=False)
        if table:
            lines += table + [""]
        return body + "\n".join(lines).rstrip() + "\n"

    def _skill_rule(self, skill: object, owner: Role) -> str:
        body = front_matter(
            {
                "description": skill.description,  # type: ignore[attr-defined]
                "alwaysApply": "false",
            }
        )
        lines = [
            "",
            heading(1, skill.name),  # type: ignore[attr-defined]
            "",
            skill.instructions.strip(),  # type: ignore[attr-defined]
            "",
            f"Declared by role `{owner.name}`.",
        ]
        return body + "\n".join(lines).rstrip() + "\n"

    def _render_notes(
        self,
        role: Role,
    ) -> Iterable[str]:
        yield (
            "Cursor rules are a flat namespace; the role tree is encoded in "
            "rule file names and prose rather than in structure, so two roles "
            "with the same name under different parents would collide."
        )
