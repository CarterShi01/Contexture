"""The target layer: one declaration, many agent-facing surfaces.

A target adapter renders a declaration as files. It takes a role tree that
knows nothing about any particular agent and renders the files one agent
actually reads.

Two rules hold for every adapter:

* **Nothing is written here.** `render` returns an `ArtifactSet` of paths and
  bytes. Deciding where those land, and whether to overwrite anything, belongs
  to a caller — see `contexture.targets.writer`.
* **Losses are reported, not hidden.** Agents differ in what they can express.
  When a target cannot carry something the declaration states, the adapter says
  so in a note instead of silently dropping it, because a generated surface
  that looks authoritative while being quietly lossy is worse than no
  generation at all.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar, Iterable, Iterator

from ..core.errors import TargetRenderError
from ..core.role import Role


@dataclass(slots=True, frozen=True, kw_only=True)
class Artifact:
    """One rendered file, addressed by a path relative to a project root."""

    path: str
    content: str
    media_type: str = "text/markdown"

    def __post_init__(self) -> None:
        if not self.path.strip():
            raise TargetRenderError("An artifact needs a non-empty path.")
        if self.path.startswith("/") or ".." in self.path.split("/"):
            raise TargetRenderError(
                f"Artifact path {self.path!r} must stay inside the project; "
                "absolute paths and parent traversal are refused."
            )

    @property
    def digest(self) -> str:
        """A content digest, so drift against an installed file is detectable."""

        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


@dataclass(slots=True, frozen=True, kw_only=True)
class ArtifactSet:
    """Everything one adapter produced for one role, plus what it could not."""

    target: str
    artifacts: tuple[Artifact, ...] = ()
    notes: tuple[str, ...] = ()

    def __iter__(self) -> Iterator[Artifact]:
        return iter(self.artifacts)

    def __len__(self) -> int:
        return len(self.artifacts)

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(artifact.path for artifact in self.artifacts)

    def get(self, path: str) -> Artifact:
        for artifact in self.artifacts:
            if artifact.path == path:
                return artifact
        raise TargetRenderError(
            f"Target {self.target!r} rendered no artifact at {path!r}."
        )

    @property
    def digest(self) -> str:
        """A digest over every path and body, stable across runs.

        Recompiling and comparing this against the last installed value is how
        a caller detects that a generated surface has gone stale.
        """

        hasher = hashlib.sha256()
        for artifact in sorted(self.artifacts, key=lambda item: item.path):
            hasher.update(artifact.path.encode("utf-8"))
            hasher.update(b"\0")
            hasher.update(artifact.content.encode("utf-8"))
            hasher.update(b"\0")
        return hasher.hexdigest()


@dataclass(slots=True, frozen=True, kw_only=True)
class TargetCapabilities:
    """What one agent surface can express.

    The base adapter turns the gaps between this and a declaration into notes,
    so each adapter states its limits once as data instead of remembering to
    write the same warnings by hand.
    """

    #: Skills can be separate, individually discoverable files.
    separate_skill_files: bool
    #: The surface can hold detail back until something is selected.
    progressive_disclosure: bool
    #: Nested roles can be expressed as their own routable units.
    nested_roles: bool


class TargetAdapter(ABC):
    """Render one role tree into the surface a single agent runtime consumes."""

    #: Stable identifier used in artifact sets, notes, and CLI selection.
    name: ClassVar[str]
    #: Human-readable name of the agent this adapter targets.
    display_name: ClassVar[str]
    capabilities: ClassVar[TargetCapabilities]

    def render(self, role: Role) -> ArtifactSet:
        """Render `role` and report anything this target could not carry."""

        artifacts = tuple(self._render_artifacts(role))
        notes = tuple(self._capability_notes(role)) + tuple(
            self._render_notes(role)
        )
        return ArtifactSet(target=self.name, artifacts=artifacts, notes=notes)

    @abstractmethod
    def _render_artifacts(
        self,
        role: Role,
    ) -> Iterable[Artifact]:
        """Produce this target's files for the role tree rooted at `role`."""

    def _render_notes(
        self,
        role: Role,
    ) -> Iterable[str]:
        """Report target-specific losses beyond the shared capability gaps."""

        return ()

    def _capability_notes(self, role: Role) -> Iterable[str]:
        """Derive the losses implied by this target's declared capabilities."""

        capabilities = self.capabilities
        notes: list[str] = []

        skills = _all_skills(role)
        if skills and not capabilities.separate_skill_files:
            notes.append(
                f"{self.display_name} has no separate skill artifact; "
                f"{len(skills)} skill(s) were inlined into the main context "
                "file, so their instructions are always resident."
            )

        if not capabilities.progressive_disclosure:
            notes.append(
                f"{self.display_name} loads its context in full; the "
                "route/active distinction was flattened and every activated "
                "detail is always visible."
            )

        if role.children and not capabilities.nested_roles:
            notes.append(
                f"{self.display_name} has no nested-role concept; "
                f"{len(role.children)} child role(s) were flattened into the "
                "root surface."
            )

        return notes


def render_all(
    role: Role,
    adapters: Iterable[TargetAdapter],
) -> dict[str, ArtifactSet]:
    """Render one declaration for several targets, keyed by target name."""

    return {adapter.name: adapter.render(role) for adapter in adapters}


def render_json(payload: object) -> str:
    """Serialize configuration deterministically, with a trailing newline."""

    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def iter_roles(role: Role) -> Iterator[Role]:
    """Yield the role and every descendant, parents before children."""

    yield role
    for child in role.children:
        yield from iter_roles(child)


def _all_skills(role: Role) -> list[object]:
    return [skill for node in iter_roles(role) for skill in node.skills]


__all__ = [
    "Artifact",
    "ArtifactSet",
    "TargetAdapter",
    "TargetCapabilities",
    "iter_roles",
    "render_all",
    "render_json",
]
