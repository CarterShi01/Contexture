"""Reusable workflow knowledge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from .context import ContextNode
from .errors import ModelValidationError
from .types import CompiledContext


@dataclass(slots=True, kw_only=True)
class Skill(ContextNode):
    """A reusable method that explains how to perform a class of work."""

    instructions: str

    kind: ClassVar[str] = "skill"

    def __post_init__(self) -> None:
        ContextNode.__post_init__(self)
        if not self.instructions.strip():
            raise ModelValidationError(
                f"Skill {self.name!r} must have execution instructions."
            )

    def _compile_active(self) -> CompiledContext:
        return {
            **self._compile_route(),
            "instructions": self.instructions,
        }
