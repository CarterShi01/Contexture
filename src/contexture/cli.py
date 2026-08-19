"""The `contexture` command: scaffold a project, then serve it.

A business project written against this framework contains declarations and
nothing else. It has no entry point, no `main()`, and no console script of its
own, because the framework ships the runner:

    contexture new my-context      # write the project
    contexture list                # what would be served
    contexture serve               # serve it over MCP

The project is *served*, not distributed. It has no build system and is never
installed into the environment, so `serve` and `list` locate it the way Scrapy
locates a crawl project: walk up for the marker — here, a `pyproject.toml` with
a `[tool.contexture]` table — and put that directory on `sys.path`.

`ContextureApp` remains the escape hatch for embedding a graph in a process
this command does not own.
"""

from __future__ import annotations

import argparse
import importlib
import re
import shutil
import string
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .core.errors import ContextureError
from .core.role import Role

#: Templates ship as package data beside this module.
TEMPLATES = Path(__file__).parent / "templates"

#: The directory a project template carries as a stand-in for its own package.
PLACEHOLDER_PACKAGE = "module"

#: The table `serve` and `list` read, and the marker they find a project by.
CONFIG_TABLE = "contexture"

#: The reference application this package ships, for `contexture demo`.
DEMO_TARGET = "contexture.examples.incident:KubernetesIncidentResponder"


class UsageError(ContextureError):
    """Raised for a mistake in how the command was invoked."""


# ---------------------------------------------------------------- scaffolding


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

    @classmethod
    def derive(cls, raw: str) -> Names:
        slug = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-")
        if not slug:
            raise UsageError(
                f"{raw!r} contains no letters or digits to build a name from."
            )
        package = slug.replace("-", "_")
        if package[0].isdigit():
            raise UsageError(
                f"{raw!r} starts with a digit, so it cannot become a Python "
                "package name. Try a leading letter."
            )
        words = [part for part in slug.split("-") if part]
        return cls(
            project_name=slug,
            package_name=package,
            role_class="".join(word.capitalize() for word in words) + "Assistant",
            role_description=(
                f"Answer requests about {slug.replace('-', ' ')}."
            ),
            resource_scheme=slug,
        )

    def as_variables(self) -> dict[str, str]:
        return {
            "project_name": self.project_name,
            "package_name": self.package_name,
            "role_class": self.role_class,
            "role_description": self.role_description,
            "resource_scheme": self.resource_scheme,
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

    placeholder = root / PLACEHOLDER_PACKAGE
    if placeholder.is_dir():
        placeholder.rename(root / names.package_name)

    variables = names.as_variables()
    for path in sorted(root.rglob("*.tmpl")):
        render_file(path, variables)

    return root


# -------------------------------------------------------------- project state


def find_project(start: Path | None = None) -> Path | None:
    """Walk up for the nearest `pyproject.toml` carrying our table."""

    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        candidate = directory / "pyproject.toml"
        if candidate.is_file() and CONFIG_TABLE in _read_toml(candidate).get(
            "tool", {}
        ):
            return directory
    return None


def _read_toml(path: Path) -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ModuleNotFoundError:
            raise UsageError(
                "Reading pyproject.toml on Python 3.10 needs `tomli`. Install "
                "it, or pass the root explicitly: contexture serve pkg.mod:Role"
            ) from None
    with path.open("rb") as handle:
        return tomllib.load(handle)


@dataclass(slots=True, frozen=True, kw_only=True)
class ProjectConfig:
    """What `[tool.contexture]` said, plus where it was found."""

    root: Path
    name: str
    roots: tuple[str, ...]

    @classmethod
    def load(cls, root: Path) -> ProjectConfig:
        table = _read_toml(root / "pyproject.toml").get("tool", {}).get(
            CONFIG_TABLE, {}
        )
        targets = table.get("roots") or ()
        if isinstance(targets, str):
            targets = (targets,)
        if not targets:
            raise UsageError(
                f"{root / 'pyproject.toml'} has a [tool.contexture] table but no "
                "`roots`. List at least one, as \"package.module:RoleClass\"."
            )
        return cls(
            root=root,
            name=str(table.get("name") or root.name),
            roots=tuple(str(target) for target in targets),
        )


def resolve_target(target: str) -> Role:
    """Turn `package.module:RoleClass` into a built Role.

    Naming the class is required rather than inferred. A module that declares a
    dozen roles has no obvious root, and guessing wrong would swap what the
    server offers without failing.
    """

    module_name, separator, attribute = target.partition(":")
    if not separator or not module_name or not attribute:
        raise UsageError(
            f"{target!r} must be written as \"package.module:RoleClass\"."
        )
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise UsageError(
            f"Cannot import {module_name!r} ({exc}). Run this from inside the "
            "project, or check `roots` in pyproject.toml."
        ) from exc
    try:
        declared = getattr(module, attribute)
    except AttributeError:
        raise UsageError(
            f"{module_name!r} has no attribute {attribute!r}."
        ) from None
    if isinstance(declared, Role):
        return declared
    if isinstance(declared, type) and issubclass(declared, Role):
        return declared()
    raise UsageError(
        f"{target} is a {type(declared).__name__}, not a Role subclass."
    )


def load_roots(targets: Sequence[str], *, project: Path | None) -> list[Role]:
    if project is not None and str(project) not in sys.path:
        sys.path.insert(0, str(project))
    return [resolve_target(target) for target in targets]


def _targets_and_project(
    target: str | None,
) -> tuple[tuple[str, ...], Path | None, str | None]:
    """Resolve what to serve: an explicit target, or the enclosing project."""

    project = find_project()
    if target:
        return (target,), project, None
    if project is None:
        raise UsageError(
            "No [tool.contexture] table found in this directory or above it. "
            "Run inside a project, name a root explicitly "
            "(contexture serve pkg.mod:RoleClass), or start one with "
            "`contexture new <name>`."
        )
    config = ProjectConfig.load(project)
    return config.roots, project, config.name


# -------------------------------------------------------------------- commands


def command_new(args: argparse.Namespace) -> int:
    root = new_project(args.name, destination=args.into, template=args.template)
    relative = _display_path(root)
    print(f"Wrote {relative}")
    print()
    print("Next:")
    print(f"  cd {relative}")
    print("  uv sync")
    print("  uv run contexture list      # what it would serve")
    print("  uv run contexture serve     # serve it over stdio")
    return 0


def command_list(args: argparse.Namespace) -> int:
    from .discovery import build_graph

    targets, project, _ = _targets_and_project(args.target)
    graph = build_graph(load_roots(targets, project=project))

    for path, role in graph.iter_roles():
        indent = "  " * (path.count("/"))
        print(f"{indent}{role.name}  — {role.description}")
        for skill in role.skills:
            print(f"{indent}  skill     {skill.name}")
        for tool in role.tools:
            access = "read-only" if tool.read_only else "needs approval"
            print(f"{indent}  tool      {tool.name}  ({access})")
        for resource in role.resources:
            print(f"{indent}  resource  {resource.uri}")
    return 0


def command_demo(args: argparse.Namespace) -> int:
    """Serve the bundled reference application, to prove an install works."""

    from .server import ContextureApp

    app = ContextureApp(
        roots=resolve_target(DEMO_TARGET), name="contexture-demo"
    )
    app.run(transport=args.transport)
    return 0


def command_serve(args: argparse.Namespace) -> int:
    # Imported here, not at module scope: `new` and `list` must work in an
    # environment that has no SDK, and only this command needs one.
    from .server import ContextureApp

    targets, project, name = _targets_and_project(args.target)
    roots = load_roots(targets, project=project)
    app = ContextureApp(roots=roots, name=name or "contexture")
    app.run(transport=args.transport)
    return 0


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="contexture",
        description="Declare roles, skills, tools, and resources; serve them over MCP.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    new = subcommands.add_parser(
        "new", help="write a runnable project you can edit into your own"
    )
    new.add_argument("name", help="project name, e.g. my-context")
    new.add_argument(
        "--into",
        type=Path,
        default=None,
        metavar="DIR",
        help="parent directory to write into (default: here)",
    )
    new.add_argument(
        "--template",
        default="project",
        help=f"template to use (available: {', '.join(available_templates()) or 'none'})",
    )
    new.set_defaults(func=command_new)

    listing = subcommands.add_parser(
        "list", help="print the roles, skills, tools, and resources that would be served"
    )
    listing.add_argument("target", nargs="?", help="package.module:RoleClass")
    listing.set_defaults(func=command_list)

    serve = subcommands.add_parser("serve", help="serve the project over MCP")
    serve.add_argument("target", nargs="?", help="package.module:RoleClass")
    serve.add_argument(
        "--transport",
        default="stdio",
        choices=("stdio", "streamable-http", "sse"),
        help="transport to serve on (default: stdio)",
    )
    serve.set_defaults(func=command_serve)

    demo = subcommands.add_parser(
        "demo", help="serve the bundled reference application"
    )
    demo.add_argument(
        "--transport",
        default="stdio",
        choices=("stdio", "streamable-http", "sse"),
        help="transport to serve on (default: stdio)",
    )
    demo.set_defaults(func=command_demo)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.func(args))
    except ContextureError as exc:
        # stderr, always: under stdio the protocol owns stdout exclusively.
        print(f"contexture: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
