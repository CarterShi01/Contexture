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
from .core.model.role import Role

#: Templates ship as package data beside this module.
TEMPLATES = Path(__file__).parent / "templates"

#: The table `serve` and `list` read, and the marker they find a project by.
CONFIG_TABLE = "contexture"

#: The reference application this package ships, for `contexture demo`.
DEMO_TARGET = "contexture.examples.incident:KubernetesPlatform"

#: What the demo publishes on the resource primitive. Named rather than
#: imported, for the same reason its roots are: `cli` resolves the example
#: at run time and does not depend on it.
DEMO_SURFACE = "contexture.examples.incident.server:SURFACE"


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

    #: What the project puts on the prompt and resource primitives, as
    #: `package.module:NAME` targets. Optional: a declaration reaches an agent
    #: through the gateway whether or not anybody named a way in for a person.
    surface: tuple[str, ...] = ()

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
        exposed = table.get("surface") or ()
        if isinstance(exposed, str):
            exposed = (exposed,)
        return cls(
            root=root,
            name=str(table.get("name") or root.name),
            roots=tuple(str(target) for target in targets),
            surface=tuple(str(target) for target in exposed),
        )


def resolve_target(target: str, *, project: Path | None = None) -> Role:
    """Turn `package.module:RoleClass` into a built Role.

    Naming the class is required rather than inferred. A module that declares a
    dozen roles has no obvious root, and guessing wrong would swap what the
    server offers without failing.

    `project` is where the declaration is expected to live. Passing it turns a
    name the project shares with something already installed into a sentence
    rather than a server quietly built from somebody else's module — see
    `_require_declared_here`.
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
    _require_declared_here(module, module_name, project)
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


def _require_declared_here(
    module: object,
    module_name: str,
    project: Path | None,
) -> None:
    """Refuse a module that resolved to something outside the project.

    A project directory goes on the end of `sys.path`, so a top-level name it
    shares with an installed distribution resolves to the *installed* one. That
    is the safe half of appending — nothing of Python's own is shadowed — but
    the failure it leaves is the quiet kind: a server built from somebody
    else's module, with no error anywhere. Naming it is one comparison.
    """

    if project is None:
        return
    origin = getattr(module, "__file__", None)
    if origin is None:
        return
    resolved = Path(origin).resolve()
    if resolved.is_relative_to(project.resolve()):
        return
    raise UsageError(
        f"{module_name!r} resolved to {resolved}, which is outside this "
        f"project ({project}). Something already installed answers to that "
        "name, so the project's own module is unreachable. Rename it, or name "
        "a module this project does not share with a dependency."
    )


def load_roots(targets: Sequence[str], *, project: Path | None) -> list[Role]:
    # Appended, never inserted at the front. A project directory holds whatever
    # its author put there, and a file called `types.py` or `logging.py` beside
    # `pyproject.toml` would shadow the standard library for the whole process
    # — the SDK included — if this directory outranked it. Appending gives the
    # standard library and every installed distribution priority, and
    # `_require_declared_here` turns the one failure that trade introduces into
    # a sentence.
    if project is not None and str(project) not in sys.path:
        sys.path.append(str(project))
    return [resolve_target(target, project=project) for target in targets]


def load_surface(
    targets: Sequence[str],
    *,
    project: Path | None = None,
) -> list[object]:
    """Resolve each `package.module:NAME` naming a prompt or a resource.

    A target may name one entry or a sequence of them, because a project that
    declares eight commands should not have to list eight lines here as well.
    `sys.path` is already set by `load_roots`, which runs first.

    `project` is checked the same way `resolve_target` checks it, and is left
    out for a target that is deliberately not in a project — the bundled demo
    lives inside this package.
    """

    entries: list[object] = []
    for target in targets:
        module_name, separator, attribute = target.partition(":")
        if not separator or not module_name or not attribute:
            raise UsageError(
                f"{target!r} must be written as \"package.module:NAME\"."
            )
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            raise UsageError(
                f"Cannot import {module_name!r} ({exc}). Check `surface` in "
                "pyproject.toml."
            ) from exc
        _require_declared_here(module, module_name, project)
        try:
            declared = getattr(module, attribute)
        except AttributeError:
            raise UsageError(
                f"{module_name!r} has no attribute {attribute!r}."
            ) from None
        if isinstance(declared, (list, tuple)):
            entries.extend(declared)
        else:
            entries.append(declared)
    return entries


def _targets_and_project(
    target: str | None,
) -> tuple[tuple[str, ...], Path | None, str | None, tuple[str, ...]]:
    """Resolve what to serve: an explicit target, or the enclosing project."""

    project = find_project()
    if target:
        return (target,), project, None, ()
    if project is None:
        raise UsageError(
            "No [tool.contexture] table found in this directory or above it. "
            "Run inside a project, name a root explicitly "
            "(contexture serve pkg.mod:RoleClass), or start one with "
            "`contexture new <name>`."
        )
    config = ProjectConfig.load(project)
    return config.roots, project, config.name, config.surface


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
    from .core.disclosure.tree import ContextTree

    targets, project, _, _ = _targets_and_project(args.target)
    tree = ContextTree.of(load_roots(targets, project=project))

    # Printed with the reference an agent would actually be handed, so what a
    # developer reads here is what the model reads there.
    for ref, role in tree.roles_with_refs():
        indent = "  " * ref.count("/")
        print(f"{indent}{role.name}  — {role.description}")
        for skill in role.skills:
            print(f"{indent}  skill     {ref}/{skill.name}")
        for tool in role.tools:
            access = "read-only" if tool.read_only else "needs approval"
            print(f"{indent}  tool      {ref}/{tool.name}  ({access})")
    return 0


def command_inspect(args: argparse.Namespace) -> int:
    """Print what an agent would receive, step by step.

    The tree is built through `ContextureApp` rather than `ContextTree.of`,
    which is the whole point of the command: a tool schema on a card comes from
    the same `Dispatch` the server validates calls with, and the instructions
    come from the same builder. What is printed here is what is served there,
    or this command is worth nothing.
    """

    from . import inspection
    from .server import ContextureApp
    from .server import instructions as instructions_module

    targets, project, name, exposed = _targets_and_project(args.target)
    roots = load_roots(targets, project=project)
    app = ContextureApp(
        roots=roots,
        surface=load_surface(exposed, project=project),
        name=name or "contexture",
    )

    instructions = instructions_module.build(
        app.tree,
        budget=(
            args.roster_budget
            if args.roster_budget is not None
            else instructions_module.ROSTER_BUDGET
        ),
    )
    refs = list(inspection.every_ref(app.tree)) if args.all else list(args.refs)

    traced = inspection.trace(
        app.tree,
        refs,
        instructions=instructions,
        discover=not args.no_discover,
        read=args.read,
    )

    if args.json:
        print(inspection.as_json(traced))
    else:
        print(inspection.render(traced, payloads=not args.summary))
    # A refused ref or an unmet host limit is a finding, not a crash: the text
    # is still printed, and the exit status is what a script can act on.
    return 1 if traced.failures else 0


def serve_options(args: argparse.Namespace) -> "ContextureOptions":
    """Turn the transport flags into the object that validates them.

    Every check lives on `ContextureOptions` rather than here, so that a
    project embedding a graph in its own process is held to the same rules as
    one served from this command. A command line that validated separately
    would be a second opinion, and the two would drift.

    Authentication is deliberately not a flag. A verifier is an object with a
    method, not a string: a deployment that needs one writes a few lines that
    build `ContextureOptions(auth=Auth(...))` and calls `app.run(options)`.
    """

    from .server import ContextureOptions

    return ContextureOptions(
        transport=args.transport,
        host=args.host,
        port=args.port,
        path=args.path,
        allowed_hosts=tuple(args.allow_host),
        allowed_origins=tuple(args.allow_origin),
        allow_anonymous=args.allow_anonymous,
    )


def command_demo(args: argparse.Namespace) -> int:
    """Serve the bundled reference application, to prove an install works."""

    from .server import ContextureApp

    app = ContextureApp(
        roots=resolve_target(DEMO_TARGET),
        surface=load_surface([DEMO_SURFACE]),
        name="contexture-demo",
    )
    app.run(serve_options(args))
    return 0


def command_serve(args: argparse.Namespace) -> int:
    # Imported here, not at module scope: `new` and `list` must work in an
    # environment that has no SDK, and only this command needs one.
    from .server import ContextureApp

    targets, project, name, exposed = _targets_and_project(args.target)
    roots = load_roots(targets, project=project)
    app = ContextureApp(
        roots=roots,
        surface=load_surface(exposed, project=project),
        name=name or "contexture",
    )
    app.run(serve_options(args))
    return 0


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def add_transport_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the flags every serving command shares.

    Defined once and added twice rather than written twice, so `serve` and
    `demo` cannot end up offering different ways to reach the same server.

    Each defaults to `None`, never to the value it eventually takes, which is
    what lets `--transport stdio --port 9000` be reported as a contradiction
    rather than accepted and ignored. The defaults themselves live on
    `ContextureOptions`.
    """

    parser.add_argument(
        "--transport",
        default="stdio",
        choices=("stdio", "streamable-http"),
        help="transport to serve on (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="interface to bind (default: 127.0.0.1, this machine only)",
    )
    parser.add_argument(
        "--port", type=int, default=None, help="port to bind (default: 8000)"
    )
    parser.add_argument(
        "--path", default=None, help="path the MCP endpoint lives at (default: /mcp)"
    )
    parser.add_argument(
        "--allow-host",
        action="append",
        default=[],
        metavar="HOST",
        help=(
            "a Host header this server answers, repeatable. Required once "
            "--host is not loopback"
        ),
    )
    parser.add_argument(
        "--allow-origin",
        action="append",
        default=[],
        metavar="ORIGIN",
        help="an Origin header this server answers, repeatable",
    )
    parser.add_argument(
        "--allow-anonymous",
        action="store_true",
        help=(
            "serve a non-loopback address with no authentication — everything "
            "the tools can reach becomes reachable by anyone who can route here"
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="contexture",
        description="Declare roles, skills and tools; serve them over MCP.",
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
        "list", help="print the roles, skills and tools that would be served"
    )
    listing.add_argument("target", nargs="?", help="package.module:RoleClass")
    listing.set_defaults(func=command_list)

    inspect = subcommands.add_parser(
        "inspect",
        help="print what an agent receives at each step, and what it costs",
        description=(
            "Replay a session without an agent: the instructions a host loads "
            "at connect, the roots contexture_discover answers with, then one "
            "contexture_open per ref you name. What is printed is what is "
            "served — the same builder, the same tree, the same schemas. Only "
            "the wire is missing. A wrong ref prints the sentence the agent "
            "would read rather than failing."
        ),
    )
    inspect.add_argument(
        "refs",
        nargs="*",
        help="refs to open, in order, e.g. my-role my-role/my-skill",
    )
    inspect.add_argument(
        "--target", default=None, help="package.module:RoleClass"
    )
    inspect.add_argument(
        "--all",
        action="store_true",
        help="open every node in the tree, so you can read all of your own text",
    )
    inspect.add_argument(
        "--read",
        action="store_true",
        help="also read each resource named, running its read() and costing it",
    )
    inspect.add_argument(
        "--summary",
        action="store_true",
        help="costs and host limits only, without the payloads",
    )
    inspect.add_argument(
        "--json", action="store_true", help="emit the trace as JSON, for diffing"
    )
    inspect.add_argument(
        "--no-discover",
        action="store_true",
        help="skip the contexture_discover step",
    )
    inspect.add_argument(
        "--roster-budget",
        type=int,
        default=None,
        metavar="CHARS",
        help=(
            "render the bootstrap roster against a different budget, to see "
            "where it gets cut (default: the one hosts actually get)"
        ),
    )
    inspect.set_defaults(func=command_inspect)

    serve = subcommands.add_parser("serve", help="serve the project over MCP")
    serve.add_argument("target", nargs="?", help="package.module:RoleClass")
    add_transport_arguments(serve)
    serve.set_defaults(func=command_serve)

    demo = subcommands.add_parser(
        "demo", help="serve the bundled reference application"
    )
    add_transport_arguments(demo)
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
