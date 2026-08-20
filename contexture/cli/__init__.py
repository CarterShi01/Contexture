"""The `contexture` command: scaffold a project, then serve it.

A business project written against this framework contains declarations and
nothing else. It has no entry point, no `main()`, and no console script of its
own, because the framework ships the runner:

    contexture new my-context      # write the project
    contexture list                # what would be served
    contexture serve               # serve it over MCP

Three modules, because three clocks. `scaffold` moves when the project
template does, `project` when the packaging ecosystem does, and `main` when the
commands do — the same reason `server` is six modules rather than one file.
`usage` is the shared ground beneath them.

This facade is what a test or an embedder names. It is eager rather than lazy:
unlike `contexture` and `contexture.core`, nothing here is expensive and there
is no SDK behind any of it — `main` defers that import to the two commands
that need one, so `new` and `list` still run in an environment without it.
"""

from __future__ import annotations

from .main import build_parser, main
from .project import (
    CONFIG_TABLE,
    DEMO_PUBLISH,
    DEMO_TARGET,
    ProjectConfig,
    find_project,
    load_roots,
    load_published,
    resolve_target,
)
from .scaffold import TEMPLATES, Names, available_templates, new_project, render_file
from .usage import UsageError

__all__ = [
    "CONFIG_TABLE",
    "DEMO_PUBLISH",
    "DEMO_TARGET",
    "Names",
    "ProjectConfig",
    "TEMPLATES",
    "UsageError",
    "available_templates",
    "build_parser",
    "find_project",
    "load_roots",
    "load_published",
    "main",
    "new_project",
    "render_file",
    "resolve_target",
]
