"""Per-agent rendering: one declaration, many consumable surfaces.

A target adapter is a back end. It never decides what a role means, only how a
particular agent runtime is told about it — and it reports whatever that agent
cannot express instead of dropping it quietly.

    from contexture.targets import ClaudeCodeAdapter, render_all

    surfaces = render_all(root_role, [ClaudeCodeAdapter(), CursorAdapter()])
    for note in surfaces["claude-code"].notes:
        print(note)

Nothing here writes to disk; see `contexture.targets.writer` for that.
"""

from .base import (
    Artifact,
    ArtifactSet,
    TargetAdapter,
    TargetCapabilities,
    render_all,
)
from .claude_code import ClaudeCodeAdapter
from .codex import CodexAdapter
from .cursor import CursorAdapter
from .writer import Change, PlannedChange, WritePlan, plan, write, write_all

#: Every adapter shipped with Contexture, in a stable order.
BUILTIN_ADAPTERS: tuple[type[TargetAdapter], ...] = (
    ClaudeCodeAdapter,
    CodexAdapter,
    CursorAdapter,
)


def adapter_for(name: str) -> TargetAdapter:
    """Build a built-in adapter by its stable target name."""

    for adapter in BUILTIN_ADAPTERS:
        if adapter.name == name:
            return adapter()
    known = ", ".join(sorted(adapter.name for adapter in BUILTIN_ADAPTERS))
    raise LookupError(f"Unknown target {name!r}. Known targets: {known}.")


def all_adapters() -> tuple[TargetAdapter, ...]:
    """Instantiate every built-in adapter."""

    return tuple(adapter() for adapter in BUILTIN_ADAPTERS)


__all__ = [
    "Artifact",
    "ArtifactSet",
    "BUILTIN_ADAPTERS",
    "Change",
    "ClaudeCodeAdapter",
    "CodexAdapter",
    "CursorAdapter",
    "PlannedChange",
    "TargetAdapter",
    "TargetCapabilities",
    "WritePlan",
    "adapter_for",
    "all_adapters",
    "plan",
    "render_all",
    "write",
    "write_all",
]
