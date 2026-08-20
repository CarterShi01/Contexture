"""The commands themselves, and the parser that reaches them.

    contexture new my-context      # write the project
    contexture list                # what would be served
    contexture inspect             # what an agent receives, and what it costs
    contexture serve               # serve it over MCP
    contexture demo                # serve the bundled reference application

Every command that serves builds its graph the same way a business `main()`
does — register, seal, serve — through `_assembled` below. Two doors, one
flow: a project that would rather not write an entry point gets these
commands, and one that writes its own follows the same five steps by hand.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from ..core.errors import ContextureError
from .project import (
    DEMO_PUBLISH,
    DEMO_TARGET,
    Serving,
    _targets_and_project,
    load_channels,
    load_roots,
    load_published,
    resolve_target,
)
from .scaffold import available_templates, new_project

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..server import ContextureOptions

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
    from ..core.model.tree import ContextTree

    serving = _targets_and_project(args.target)
    targets, project = serving.roots, serving.project
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


def _assembled(serving: Serving):
    """Register, seal, and hand back the assembly — `main()`'s three steps.

    The same five objects a project writes by hand, in the same order. What
    differs is only where each one is named: here from a `[tool.contexture]`
    table, there from an import. Two doors, one flow — which is what keeps a
    newcomer learning one path instead of two.

    Imported here, not at module scope: `new` and `list` must work in an
    environment that has no SDK, and only the commands calling this need one.
    """

    from ..core.model.manager import ControllerManager, register_root
    from ..server import Assembly, TypeHintBinding

    project = serving.project
    # `load_roots` is what puts the project on `sys.path`, so it runs before
    # anything else the project declared is resolved.
    roots = load_roots(serving.roots, project=project)
    manager = ControllerManager(
        channels=load_channels(serving.channels, project=project)
    )
    for root in roots:
        register_root(manager, root)

    return Assembly.of(
        manager.sealed(bind=TypeHintBinding),
        published=load_published(serving.publish, project=project),
    )


def command_inspect(args: argparse.Namespace) -> int:
    """Print what an agent would receive, step by step.

    The tree is sealed with the real binding rather than left bare, which is
    the whole point of the command: a tool schema on a card comes from the same
    derivation the server validates calls with, and the instructions come from
    the same builder. What is printed here is what is served there, or this command
    is worth nothing.
    """

    from .. import inspection
    from ..server import instructions as instructions_module

    serving = _targets_and_project(args.target, or_demo=True)
    if serving.project is None and not args.target:
        # stderr, so `--json` stays a clean document on stdout. Announced at
        # all because replaying something other than what the reader meant, in
        # silence, is worse than the refusal this replaced.
        print(
            "No project here, so this is the bundled demo. Run inside a "
            "project, or name one with --target, to read your own.",
            file=sys.stderr,
        )
    assembly = _assembled(serving)

    instructions = instructions_module.build(
        assembly.tree,
        budget=(
            args.roster_budget
            if args.roster_budget is not None
            else instructions_module.ROSTER_BUDGET
        ),
    )
    refs = list(inspection.every_ref(assembly.tree)) if args.all else list(args.refs)

    traced = inspection.trace(
        assembly.tree,
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

    from ..server import ContextureOptions

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

    from ..server import ContextureServer

    assembly = _assembled(
        Serving(roots=(DEMO_TARGET,), name="contexture-demo", publish=(DEMO_PUBLISH,))
    )
    ContextureServer(assembly, name="contexture-demo").start(serve_options(args))
    return 0


def command_serve(args: argparse.Namespace) -> int:
    from ..server import ContextureServer

    serving = _targets_and_project(args.target)
    assembly = _assembled(serving)
    ContextureServer(assembly, name=serving.name or "contexture").start(
        serve_options(args)
    )
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


__all__ = ["build_parser", "main"]
