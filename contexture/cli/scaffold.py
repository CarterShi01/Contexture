"""Writing a project: what `contexture new` puts on disk.

Moves when the template does, which is a different clock from the one
`project` runs on (the packaging ecosystem) or the one `main` runs on (the
commands themselves). That is the whole reason these are three modules.
"""

from __future__ import annotations

import re
import shutil
import string
from dataclasses import dataclass
from pathlib import Path

from .usage import UsageError

#: Templates ship as package data beside this module.
TEMPLATES = Path(__file__).parent / "templates"

@dataclass(slots=True, frozen=True, kw_only=True)
class Names:
    """Every name derived from the one argument `new` takes.

    Derived rather than asked for: a scaffold that interrogates the user is a
    scaffold they stop using.
    """

    project_name: str
    package_name: str
    role_class: str
    role_description: str
    resource_scheme: str
    role_ref: str

    @classmethod
    def derive(cls, raw: str) -> Names:
        slug = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-")
        if not slug:
            raise UsageError(
                f"{raw!r} contains no letters or digits to build a name from."
            )
        if slug[0].isdigit():
            # The project directory is never imported, so its name is free.
            # The role *class* built from it is not: `9lives` would derive
            # `9livesAssistant`, which is not an identifier and fails at the
            # `class` statement rather than here.
            raise UsageError(
                f"{raw!r} starts with a digit, so the role class derived from "
                "it would not be a Python identifier. Try a leading letter."
            )
        words = [part for part in slug.split("-") if part]
        return cls(
            project_name=slug,
            package_name=slug.replace("-", "_"),
            role_class="".join(word.capitalize() for word in words) + "Assistant",
            role_description=(
                f"Answer requests about {slug.replace('-', ' ')}."
            ),
            resource_scheme=slug,
            # The reference an agent is handed: a role's node name is
            # its class name in kebab case, and this role is a root.
            role_ref=f"{slug}-assistant",
        )

    def as_variables(self) -> dict[str, str]:
        return {
            "project_name": self.project_name,
            "package_name": self.package_name,
            "role_class": self.role_class,
            "role_description": self.role_description,
            "resource_scheme": self.resource_scheme,
            "role_ref": self.role_ref,
        }


def available_templates() -> tuple[str, ...]:
    if not TEMPLATES.is_dir():
        return ()
    return tuple(sorted(p.name for p in TEMPLATES.iterdir() if p.is_dir()))


def render_file(path: Path, variables: dict[str, str]) -> Path:
    """Substitute into one file, dropping a `.tmpl` suffix if it has one.

    A template body is not importable Python while it carries `.tmpl`, which is
    what keeps linters and test collection away from it.
    """

    raw = path.read_text("utf-8")
    try:
        rendered = string.Template(raw).substitute(**variables)
    except KeyError as exc:
        raise UsageError(
            f"{path.name} refers to an unknown template variable {exc.args[0]!r}. "
            f"Known variables: {', '.join(sorted(variables))}."
        ) from exc
    target = path.with_suffix("") if path.suffix == ".tmpl" else path
    if target != path:
        path.unlink()
    target.write_text(rendered, "utf-8")
    return target


def new_project(
    name: str,
    *,
    destination: Path | None = None,
    template: str = "project",
) -> Path:
    """Write a runnable project and return its directory."""

    source = TEMPLATES / template
    if not source.is_dir():
        known = ", ".join(available_templates()) or "none found"
        raise UsageError(f"Unknown template {template!r}. Available: {known}.")

    names = Names.derive(name)
    root = (destination or Path.cwd()) / names.project_name
    if root.exists():
        raise UsageError(f"{root} already exists; refusing to write into it.")

    shutil.copytree(source, root, ignore=shutil.ignore_patterns("__pycache__"))

    (root / "assistant").rename(root / names.package_name)

    variables = names.as_variables()
    for path in sorted(root.rglob("*.tmpl")):
        render_file(path, variables)

    return root


__all__ = [
    "TEMPLATES",
    "Names",
    "available_templates",
    "new_project",
    "render_file",
]
