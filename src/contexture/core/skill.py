"""Reusable workflow knowledge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from . import declarative
from .context import ContextNode
from .errors import ModelValidationError
from .types import CompiledContext


@dataclass(slots=True, kw_only=True)
class Skill(ContextNode):
    """A reusable method that explains how to perform a class of work.

    Build one imperatively::

        Skill(name="inspect-pod-failure", description="...", instructions="...")

    or declare one as a class, which is how a business project usually states
    knowledge it owns::

        class InspectPodFailure(Skill):
            '''Diagnose why a Kubernetes Pod is failing.'''

            instructions = "1. Inspect status. 2. Read logs."

    A Skill and a Role both carry instructions, and the difference is whether
    the node holds anything. A Role's instructions orchestrate its members; a
    Skill holds none, so its instructions are the whole of it and opening one
    is the end of a path rather than a step along it. A method that needs its
    own tools to be kept away from its siblings' tools is a child Role, not a
    Skill.

    Against a Tool the split is who performs the work: a Tool is executed by
    the framework and returns a result, a Skill is executed by the model and
    returns nothing. Work that has to be judged rather than computed can only
    be a Skill — which is also why a Skill is the right home for a procedure
    whose steps are existing tools, with no code of its own to run.
    """

    #: The complete procedure. There is no second, fuller copy anywhere: this
    #: text reaches an agent only when the skill is opened, so anything left
    #: out of it is not disclosed late — it is not disclosed at all.
    instructions: str

    kind: ClassVar[str] = "skill"

    #: The class-body declaration, or None on an imperatively built Skill.
    declaration: ClassVar[declarative.Declaration | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        # A zero-argument super() raises TypeError in this method: dataclass
        # slots=True rebuilds the class object, so the implicit __class__ cell
        # still points at the discarded original. Name the class explicitly.
        super(Skill, cls).__init_subclass__(**kwargs)
        if not declarative.is_declarative(cls, Skill):
            return
        cls.declaration = declarative.collect(cls, member_types=())
        cls.__init__ = _declarative_init  # type: ignore[method-assign]

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


def _declarative_init(self: Skill, **overrides: Any) -> None:
    """Build a declared Skill, letting the caller override any stated field."""

    declaration = type(self).declaration
    assert declaration is not None  # set by __init_subclass__ before rebinding
    if declaration.instructions is None and "instructions" not in overrides:
        raise ModelValidationError(
            f"{declaration.owner} must state `instructions`; a Skill without "
            "them has nothing to disclose when it is activated."
        )
    Skill.__init__(
        self,
        **{
            "name": declaration.name,
            "description": declaration.description,
            "instructions": declaration.instructions,
            **overrides,
        },
    )
