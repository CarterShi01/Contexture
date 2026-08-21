"""Reusable workflow knowledge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from .node import ContextNode, View
from ..errors import ModelValidationError
from ..types import CompiledContext


@dataclass(slots=True, kw_only=True)
class Skill(ContextNode):
    """A reusable method that explains how to perform a class of work.

    ::

        class InspectPodFailure(Skill):
            def __init__(self) -> None:
                super().__init__(
                    name="inspect-pod-failure",
                    description="Diagnose why a Kubernetes Pod is failing.",
                    instructions="1. Inspect status. 2. Read logs.",
                )

    Same shape as a `Tool` minus the behaviour: a Skill has no executable body,
    so its constructor is the whole class. See `Tool` for why everything is
    stated and why nothing is built at import.

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

    A procedure whose steps live outside its own parent names them in `uses`::

        class ComposeAndShip(Skill):
            def __init__(self) -> None:
                super().__init__(
                    name="compose-and-ship",
                    description="Assemble the weekly letter and send it.",
                    instructions="1. Generate the cover. 2. Apply ...",
                    uses=(
                        "one-creator/assets/image-gen/generate_cover",
                        "one-creator/publishing/layout/apply_template",
                    ),
                )
    """

    #: The complete procedure. There is no second, fuller copy anywhere: this
    #: text reaches an agent only when the skill is opened, so anything left
    #: out of it is not disclosed late — it is not disclosed at all.
    instructions: str

    #: References to capabilities this procedure names but does not own.
    #:
    #: Containment is **down** and reference is **sideways**. Holding a member
    #: gives it its address — a ref *is* the path to it — which is why exactly
    #: one role may hold a node. Naming one here consumes an address that
    #: already exists and creates nothing, which is why any number of skills
    #: may name the same tool and why a skill stays a leaf: `uses` produces no
    #: depth, no children, and no new ref.
    #:
    #: These are **ref strings and never object references**, and the type is
    #: the whole guarantee rather than a convention. The walkers that enforce
    #: the forest — `_reject_cycles` and every enumerator above this module —
    #: traverse object fields, and a `tuple[str, ...]` cannot be traversed
    #: into. Holding the objects instead would make the forest a graph and
    #: `_reject_cycles` meaningless, and nothing in a code review would show it.
    #:
    #: A ref cannot be resolved from here: a skill does not know where it hangs
    #: and `core` does not know what a separator is. `Index` checks every
    #: entry when the tree is built, so a procedure naming something that does
    #: not exist fails at startup rather than when somebody reaches for it.
    uses: tuple[str, ...] = ()

    kind: ClassVar[str] = "skill"
    group: ClassVar[str] = "skills"

    def __post_init__(self) -> None:
        ContextNode.__post_init__(self)
        if not self.instructions.strip():
            raise ModelValidationError(
                f"Skill {self.name!r} must have execution instructions."
            )
        # Accept a list, store a tuple: the imperative door is a convenience,
        # and a member list that can be appended to after the tree is built is
        # exactly what `Role` forbids for the same reason.
        self.uses = tuple(self.uses)
        for ref in self.uses:
            if not isinstance(ref, str) or not ref.strip():
                raise ModelValidationError(
                    f"Skill {self.name!r} names an empty reference in `uses`."
                )
        if len(set(self.uses)) != len(self.uses):
            raise ModelValidationError(
                f"Skill {self.name!r} names the same reference twice in "
                "`uses`; a second card for one capability says there are two."
            )

    def _compile_active(self, view: View) -> CompiledContext:
        """The whole procedure, plus a card for each capability it names.

        The cards are at ROUTE, and that is what makes a reference cycle safe
        to declare (ADR 008): `diagnose -> remediate -> diagnose` renders as two
        cards naming each other rather than as a walk that does not terminate.
        Rendering a referenced skill at ACTIVE here is the one change that
        would make this unbounded.
        """

        payload = {
            **self.card(view),
            "instructions": self.instructions,
        }
        if self.uses:
            payload["uses"] = [view.card_for(ref) for ref in self.uses]
        return payload
