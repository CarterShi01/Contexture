"""The one place in Contexture that touches a filesystem.

Everything else produces or transforms values. Installing a rendered surface is
kept here, behind an explicit call, so the model and the adapters stay testable
without a temporary directory and so a caller can preview a change before it
happens.

The default is to preview: `plan` reports what would change and writes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable

from .base import Artifact, ArtifactSet


class Change(str, Enum):
    """What installing one artifact would do to the filesystem."""

    CREATE = "create"
    UPDATE = "update"
    UNCHANGED = "unchanged"


@dataclass(slots=True, frozen=True, kw_only=True)
class PlannedChange:
    """One artifact compared against what is already on disk."""

    artifact: Artifact
    path: Path
    change: Change

    @property
    def is_write(self) -> bool:
        return self.change is not Change.UNCHANGED


@dataclass(slots=True, frozen=True, kw_only=True)
class WritePlan:
    """The full comparison between a rendered surface and a project tree."""

    root: Path
    target: str
    changes: tuple[PlannedChange, ...]

    def __iter__(self):
        return iter(self.changes)

    @property
    def writes(self) -> tuple[PlannedChange, ...]:
        return tuple(change for change in self.changes if change.is_write)

    @property
    def is_current(self) -> bool:
        """True when the installed surface already matches the declaration."""

        return not self.writes

    def summary(self) -> str:
        counts = {change: 0 for change in Change}
        for planned in self.changes:
            counts[planned.change] += 1
        parts = [
            f"{counts[Change.CREATE]} to create",
            f"{counts[Change.UPDATE]} to update",
            f"{counts[Change.UNCHANGED]} unchanged",
        ]
        return f"{self.target}: " + ", ".join(parts)


def plan(artifacts: ArtifactSet, root: Path | str) -> WritePlan:
    """Compare a rendered surface against `root` without writing anything."""

    base = Path(root)
    changes = []
    for artifact in artifacts:
        destination = base / artifact.path
        if not destination.exists():
            change = Change.CREATE
        elif destination.read_text(encoding="utf-8") == artifact.content:
            change = Change.UNCHANGED
        else:
            change = Change.UPDATE
        changes.append(
            PlannedChange(artifact=artifact, path=destination, change=change)
        )
    return WritePlan(root=base, target=artifacts.target, changes=tuple(changes))


def write(
    artifacts: ArtifactSet,
    root: Path | str,
    *,
    dry_run: bool = False,
) -> WritePlan:
    """Install a rendered surface under `root`, returning what changed.

    Unchanged files are left alone rather than rewritten, so timestamps and
    file watchers only fire for content that actually moved.
    """

    computed = plan(artifacts, root)
    if dry_run:
        return computed

    for planned in computed.writes:
        planned.path.parent.mkdir(parents=True, exist_ok=True)
        planned.path.write_text(planned.artifact.content, encoding="utf-8")
    return computed


def write_all(
    artifact_sets: Iterable[ArtifactSet],
    root: Path | str,
    *,
    dry_run: bool = False,
) -> dict[str, WritePlan]:
    """Install several targets under one root, keyed by target name."""

    return {
        artifacts.target: write(artifacts, root, dry_run=dry_run)
        for artifacts in artifact_sets
    }


__all__ = [
    "Change",
    "PlannedChange",
    "WritePlan",
    "plan",
    "write",
    "write_all",
]
