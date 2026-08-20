"""What this server exposes on MCP's **prompt** primitive.

Prompts are the user-controlled primitive. The 2026-07-28 revision says what
that axis is, and it is not about authorship:

    This refers to who decides when the prompt is used, not who authors its
    content. Prompt content is defined by the server.

So this plane answers one question the tool plane cannot: **a person who
already knows the destination has no way in**, because every entrance there is
a decision the model makes.

Two rules keep it from growing into a second tool list.

**The count is authored, not derived.** One entry per declared prompt and no
more, whether the forest holds thirty nodes or three hundred. Adding one is a
code change and a restart — a new server version, not a surface varying under a
live connection, which the protocol forbids anyway.

**Declaring one is worth it only where going wrong is expensive.** A prompt
buys consistent execution, a guardrail, and saved typing; saved typing is the
weakest of the three, and everything it could do can also be had by asking the
agent. Marked everywhere, the menu becomes a second copy of the tool list and
this plane stops meaning anything.

Declaration only. `server` decides how one reaches the wire, and how a host is
told about it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from ..errors import ModelValidationError


@dataclass(slots=True, kw_only=True)
class Prompt:
    """One node in the tree, reachable by name at a person's request.

    ::

        COMPOSE_AND_SHIP = Prompt(
            opens="one-creator/publishing/compose-and-ship",
            description="Assemble the weekly letter and send it.",
            model_may_open=False,
        )

    It is **open**, never invoke. A skill has no executable body: it can be
    opened and cannot be run, and a prompt naming one means *put its procedure
    in context, because a person asked*. Calling that invocation would blur the
    contract the two invoke entry points rest on.

    This is not a `ContextNode` and deliberately does not inherit from one —
    see `resource.py` for the same reason stated in full.
    """

    #: The reference this opens. A **string**, never an object, for the reason
    #: given in `resource.py` and in `Skill.uses`: containment is down and
    #: reference is sideways, and only one of them creates an address.
    opens: str

    #: What a person reads while choosing it.
    description: str

    #: The name a person triggers it by. Defaults to the last segment of
    #: `opens` — a position-independent second name, exactly as a resource's
    #: URI is one.
    name: str | None = None

    #: Whether a model may also reach `opens` by navigating to it.
    #:
    #: False is the guardrail: the node keeps its routing card, so the model
    #: can see the capability exists and tell a person which prompt reaches it,
    #: but opening it is refused. A guardrail that lets the model point is
    #: cooperative where one that merely hides is not.
    #:
    #: Enforced in `server`, which is the only layer that knows which door a
    #: call came through — the same division `wrong_door` rests on.
    model_may_open: bool = True

    kind: ClassVar[str] = "prompt"

    def __post_init__(self) -> None:
        if not self.opens.strip():
            raise ModelValidationError(
                "A prompt must name the node it opens, in `opens`."
            )
        if not self.description.strip():
            raise ModelValidationError(
                f"Prompt {self.opens!r} must have a description; it is what a "
                "person reads while choosing it."
            )


__all__ = ["Prompt"]
