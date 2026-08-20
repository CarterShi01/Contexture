"""Finding a project, reading what it declared, and resolving it to objects.

A business project is *served*, not distributed. It has no build system and is
never installed into the environment, so this module locates it the way Scrapy
locates a crawl project: walk up for the marker — a `pyproject.toml` carrying a
`[tool.contexture]` table — and put that directory on `sys.path`.

Moves when the packaging ecosystem does, which is why it is not in `main`.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ..core.model.role import Role
from .usage import UsageError

#: The table `serve` and `list` read, and the marker they find a project by.
CONFIG_TABLE = "contexture"

#: The reference application this package ships, for `contexture demo` and for
#: `contexture inspect` run with no project in sight.
DEMO_TARGET = "contexture.demo:KubernetesPlatform"

#: What the demo publishes on the resource primitive. Named rather than
#: imported, for the same reason its roots are: this module resolves the demo
#: at run time and does not depend on it.
DEMO_PUBLISH = "contexture.demo.server:PUBLISHED"

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
    publish: tuple[str, ...] = ()

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
        exposed = table.get("publish") or ()
        if isinstance(exposed, str):
            exposed = (exposed,)
        return cls(
            root=root,
            name=str(table.get("name") or root.name),
            roots=tuple(str(target) for target in targets),
            publish=tuple(str(target) for target in exposed),
        )


def resolve_target(
    target: str,
    *,
    project: Path | None = None,
) -> Role | type[Role]:
    """Resolve `package.module:RoleClass` to the root it names.

    The **class**, not an instance of it. A declared root is turned into nodes
    by a `ControllerManager`, at registration, and building one here would put
    a second, never-registered copy in front of the one being served.

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
    if isinstance(declared, Role) or (
        isinstance(declared, type) and issubclass(declared, Role)
    ):
        return declared
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


def load_roots(
    targets: Sequence[str],
    *,
    project: Path | None,
) -> list[Role | type[Role]]:
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


def load_published(
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
                f"Cannot import {module_name!r} ({exc}). Check `publish` in "
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
    *,
    or_demo: bool = False,
) -> tuple[tuple[str, ...], Path | None, str | None, tuple[str, ...]]:
    """Resolve what to serve: an explicit target, or the enclosing project.

    `or_demo` belongs to the one command that has something worth saying with
    no project in sight. `inspect` replays a disclosure, and a reader who has
    just installed this package — or who is standing in the framework's own
    checkout, which has no `[tool.contexture]` project of its own — should get
    the bundled demo rather than a refusal. Serving is not offered the same
    courtesy: starting a server nobody asked for is a different kind of
    surprise from printing one.
    """

    project = find_project()
    if target:
        return (target,), project, None, ()
    if project is None:
        if or_demo:
            return (DEMO_TARGET,), None, "contexture-demo", (DEMO_PUBLISH,)
        raise UsageError(
            "No [tool.contexture] table found in this directory or above it. "
            "Run inside a project, name a root explicitly "
            "(contexture serve pkg.mod:RoleClass), or start one with "
            "`contexture new <name>`."
        )
    config = ProjectConfig.load(project)
    return config.roots, project, config.name, config.publish


__all__ = [
    "CONFIG_TABLE",
    "DEMO_PUBLISH",
    "DEMO_TARGET",
    "ProjectConfig",
    "find_project",
    "load_roots",
    "load_published",
    "resolve_target",
]
