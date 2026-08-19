"""Shared markdown rendering helpers for the built-in target adapters.

These exist so three adapters that all emit markdown do not each grow their own
subtly different table and front-matter writers. Anything genuinely specific to
one agent stays in that agent's module.
"""

from __future__ import annotations

from typing import Iterable, Mapping

from ..core.role import Role
from .base import iter_roles


def heading(level: int, text: str) -> str:
    return f"{'#' * level} {text}"


def front_matter(fields: Mapping[str, str]) -> str:
    """Render YAML front matter, quoting only where a bare scalar would break."""

    lines = ["---"]
    for key, value in fields.items():
        lines.append(f"{key}: {_scalar(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _scalar(value: str) -> str:
    collapsed = " ".join(value.split())
    needs_quotes = (
        not collapsed
        or collapsed[0] in "&*!|>%@`{[#-?:,"
        or ": " in collapsed
        or collapsed.endswith(":")
        or collapsed != collapsed.strip()
    )
    if not needs_quotes:
        return collapsed
    return '"' + collapsed.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_role_routes(roles: Iterable[Role]) -> list[str]:
    """Render child roles as a routing list: name plus when to pick it."""

    return [f"- **{role.name}** — {role.description}" for role in roles]


def render_capability_table(
    role: Role,
    *,
    include_children: bool = True,
) -> list[str]:
    """Render granted tools and resources as a table, or [] when nothing is granted.

    The `Access` column carries the host's own read-only classification rather
    than the server's `readOnlyHint`, because that hint is a remote claim and
    never the authorization fact.
    """

    scope = list(iter_roles(role)) if include_children else [role]
    rows: list[tuple[str, str, str, str]] = []

    for node in scope:
        for binding in node.mcp_bindings:
            server = binding.server
            for tool_name in binding.allowed_tools:
                tool = server.get_tool(tool_name)
                access = (
                    "read-only"
                    if binding.is_tool_read_only(tool_name)
                    else "needs approval"
                )
                rows.append(
                    (
                        "tool",
                        server.make_tool_ref(tool_name),
                        access,
                        tool.description,
                    )
                )
            for uri in binding.allowed_resources:
                resource = server.get_resource(uri)
                rows.append(
                    (
                        "resource",
                        server.make_resource_ref(uri),
                        "read-only",
                        resource.description,
                    )
                )

    if not rows:
        return []

    lines = [
        "| Kind | Reference | Access | Purpose |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {kind} | `{ref}` | {access} | {_cell(purpose)} |"
        for kind, ref, access, purpose in rows
    ]
    return lines


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


__all__ = [
    "front_matter",
    "heading",
    "render_capability_table",
    "render_role_routes",
]
