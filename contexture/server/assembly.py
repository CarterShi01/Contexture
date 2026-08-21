"""What a registry becomes when nothing more is coming.

Registration is additive and mutable; disclosure is neither. `Assembly` is the
line between the two phases, given a name and made frozen::

    manager = ControllerManager(channels=channels)
    manager.register_role(KubernetesPlatform)

    tree     = manager.sealed(bind=TypeHintBinding)
    assembly = Assembly.of(tree, published=PUBLISHED)

Past that third line nothing can change, which is what keeps the surface legal
under a protocol that forbids a server to vary its answers as a consequence of
an earlier call.

**Four things, because they are one thing four ways.** The tree is the object
model; the API is the four calls bound to it; the two published tuples are the
entries a person and a host may reach it by. They are held together rather than
passed around because they are derived together and cannot disagree — the
alternative, and what this replaces, was four values threaded by hand through
five signatures in `server`.

**Why this is `server` and not `core`.** It looks like kernel work — the rules
it holds would survive MCP being replaced — and it was drafted for
`core.model` on exactly that argument. The architecture says otherwise, and the
architecture is right: `core.model` and `core.mcp_interface` are **siblings**,
and ADR 009 makes their independence mutual. The object model may not know what
a `Prompt` is, and the protocol plane may not reach into the forest; what
crosses between them is a reference *string* and nothing else, which is why
`SystemAPI.reserved` is a `frozenset[str]` rather than a list of prompts.

Sealing is by definition the *join* of those two siblings: it reads `Prompt`
and `Resource` objects and resolves them against a tree. A join belongs above
both, and the first layer above both is this one. `tests/test_layering.py`
enforces it, and found this module in the wrong place the first time it ran.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from ..core.errors import ModelValidationError, NodeNotFoundError
from ..core.mcp_interface import published as _published
from ..core.mcp_interface.prompt import Prompt
from ..core.mcp_interface.resource import Resource
from ..core.model.system_api import SystemAPI
from ..core.model.disclosure import Disclosure


@dataclass(slots=True, frozen=True)
class Assembly:
    """One sealed graph, and everything a server needs to put it on a wire."""

    #: The object model, frozen.
    tree: Disclosure

    #: The four calls, bound to that tree, with `reserved` already derived.
    api: SystemAPI

    #: What a person may trigger by name, and what a host may take up on its
    #: own. Two named fields rather than one mixed list: the sort happens once,
    #: here, so that nothing downstream has to ask which kind an entry is.
    #: It is also the only shape the Go and TypeScript implementations can
    #: share — two typed slices, where an open kind map is neither.
    prompts: tuple[Prompt, ...] = ()
    resources: tuple[Resource, ...] = ()

    @classmethod
    def of(
        cls,
        tree: Disclosure,
        *,
        published: Sequence[Any] = (),
    ) -> "Assembly":
        """Seal one tree together with what is published against it.

        `published` is stated as classes, like everything else a business
        declares; already-built values are accepted too, and both arrive here
        normalised so that nothing below this line has to ask which came.
        """

        entries = tuple(_published(entry) for entry in published)
        for entry in entries:
            _require_resolvable(tree, entry.opens, entry.kind)

        prompts = tuple(entry for entry in entries if isinstance(entry, Prompt))
        resources = tuple(entry for entry in entries if isinstance(entry, Resource))
        api = SystemAPI(tree=tree, reserved=_reserved(prompts))
        return cls(tree=tree, api=api, prompts=prompts, resources=resources)

    @property
    def published(self) -> tuple[Prompt | Resource, ...]:
        """Every published entry, prompts first. For a caller counting them."""

        return (*self.prompts, *self.resources)


def _reserved(prompts: Iterable[Prompt]) -> frozenset[str]:
    """The refs a person has claimed, and a model may therefore not open.

    Derived rather than stated: a business writes `model_may_open=False` on one
    declaration, and this is the set `SystemAPI.open` consults. ADR 008 put the
    rule in this package; until now the set was assembled in `server` and
    handed in, which left one rule with two homes.
    """

    return frozenset(
        prompt.opens for prompt in prompts if not prompt.model_may_open
    )


def _require_resolvable(tree: Disclosure, ref: str, kind: str) -> None:
    """Refuse a published entry naming a node that does not exist.

    Resolved here, at seal time. A failed lookup here has a different audience
    from one at request time: nobody is waiting on an answer, and the person
    who can fix it is whoever wrote the declaration. So it does not become
    `system_api.unresolved`.
    """

    try:
        tree.find(ref)
    except NodeNotFoundError as failure:
        raise ModelValidationError(
            f"The {kind} for {ref!r} names a node that does not exist "
            f"({failure.reason.value}). A published entry is resolved when the "
            "server is built so that it fails on the way up rather than in "
            "front of whoever reached for it."
        ) from None


__all__ = ["Assembly"]
