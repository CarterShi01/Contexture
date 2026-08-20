"""The multi-headed tree, disclosed lazily.

Below this module sits `ContextNode.compile()`, which every node answers for
itself. Above it sit the four system entry points `core.model.system_api`
puts in front of an agent. This module is the whole of what joins them, and the
whole of the navigation model.

**One call shows one level of siblings.** Choosing between siblings requires
seeing all of them — what cannot be seen together is guessed between rather
than chosen between — so a level always arrives whole. It does not follow that
every level should arrive at once, and until v0.2.0 this module drew that
conclusion: `skeleton()` walked the entire forest, which is affordable at the
six roles the argument was traced against and is 440,000 tokens at eleven
thousand. `discover` now answers with the roots, and each `open` answers with
one more level of sub-roles alongside everything else that role holds. The
role axis is as lazy as every other axis; see ADR 007.

**A reference is a path.**::

    kubernetes-incident-responder
    kubernetes-incident-responder/diagnose-crash-loop-backoff

No kind prefix, no second separator. The members of one role are uniquely
named, so resolution can simply look rather than be told where to look, and the
address reads like something a person could have written. An agent never has to
write one: every card carries the reference that opens it, because `card`
cannot be called without a view to take one from.

**This is a view, not a second registry.** `ControllerManager` owns what
exists; this owns what one call answers with. The two are one object's worth of
state split across two phases of time — registration is additive and mutable,
disclosure is sealed and frozen — and the split is why a skill in the first
registered root may name a capability in the second. See ADR 014.

**Nothing here is remembered.** Every method is a pure function of its
argument, which is what keeps traversal legal on a protocol that, since the
2026-07-28 revision, forbids a server to vary its surface per connection or as
a consequence of an earlier call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from ..constants import SEPARATOR
from ..errors import LookupFailure, ModelValidationError, NodeNotFoundError
from ..types import CompiledContext, JsonObject
from .binding import Binding, PlainBinding
from .manager import ControllerManager, register_root
from .node import ContextNode, CompileLevel, group_cards
from .role import Role
from .skill import Skill
from .tool import Tool

__all__ = ["ContextTree", "SEPARATOR", "register_root"]


@dataclass(frozen=True, slots=True)
class ContextTree:
    """A sealed view of one registry, and everything needed to disclose it.

    Built from the declared roots::

        tree = ContextTree.of(KubernetesPlatform(), schema_of=...)

    or, where the application had channels to hand out before anything was
    served, from the manager that already holds them::

        tree = manager.sealed(schema_of=...)

    `bind` is how a tool's schema and the way to run it arrive without this
    module knowing what JSON Schema is. The server layer passes one backed by
    the MCP SDK; nothing here imports it. One binding is derived per tool when
    the view is sealed, and stored against the address that opens it.

    It satisfies `Disclosure`, which is how a node reaches the two things it
    cannot work out for itself: the address that opens it, and the schema an
    agent needs in order to call it.
    """

    #: The registry this view is sealed over. There is no second copy of the
    #: roots here: two answers to "what is being served" is one answer too
    #: many, and the one that can be registered into is the manager's.
    manager: ControllerManager

    #: How one tool becomes the two facts a server needs about it. Named apart
    #: from `binding_of` so that the thing producing bindings and the question
    #: asked of this view do not collide.
    bind: Callable[[Tool], Binding] = field(default=PlainBinding)

    #: One binding per tool, keyed by the address that opens it. Derived once,
    #: here, rather than on every card: an address is stable and unique, which
    #: is exactly what a cache keyed by object identity was not.
    _bindings: dict[str, Binding] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    @classmethod
    def of(
        cls,
        roots: Any,
        *,
        bind: Callable[[Tool], Binding] = PlainBinding,
    ) -> ContextTree:
        """Accept a manager, one root, or many, and return the sealed view.

        A root arrives as a **class** in the ordinary case, and a class is only
        ever turned into a node by a `ControllerManager` — so one is built here
        and the view is sealed over what it registered. That keeps a single
        answer to "when does a node come into existence" whether a caller went
        through `main()`, through a test, or through `contexture list`.
        """

        if isinstance(roots, ControllerManager):
            return roots.sealed(bind=bind)
        given = (roots,) if _is_one_root(roots) else tuple(roots)
        registry = ControllerManager()
        for root in given:
            register_root(registry, root)
        return registry.sealed(bind=bind)

    def __post_init__(self) -> None:
        if not self.roots:
            raise ModelValidationError("A context tree needs at least one root role.")

        # Registration is the walk: it assigns every address, refuses a cycle,
        # refuses one object held at two of them, and refuses two roots with
        # the same name. None of that is repeated here.
        #
        # Two checks are left, and both are here rather than in registration
        # because both need the **whole** forest in hand. Registration is
        # additive, so a skill in the first root may legitimately name a
        # capability in a root that has not been registered yet; sealing is the
        # earliest moment either question has an answer.
        self._reject_ambiguous_names()
        self._reject_unresolvable_uses()
        self._derive_bindings()

    @property
    def roots(self) -> tuple[ContextNode, ...]:
        """Everything registered at the top, in registration order."""

        return self.manager.roots

    @property
    def registry(self) -> ControllerManager:
        """The manager this view is sealed over."""

        return self.manager

    # ---- 1. answering as a view ------------------------------------------

    def ref_of(self, node: ContextNode) -> str:
        """The address that opens `node`, spelled.

        The manager holds the segments and this joins them, which is the whole
        of the division: a node carries its position and never its spelling, so
        that changing the separator is one edit here rather than one per node.
        """

        address = self.manager.address_of(node)
        if address is None:
            raise ModelValidationError(
                f"{node.name!r} is not registered in this tree, so nothing can "
                "say where it hangs. A card without a working address is worse "
                "than no card: it can be seen and not opened."
            )
        return SEPARATOR.join(address)

    def card_of(self, node: ContextNode) -> CompiledContext:
        return node.card(self)

    def card_for(self, ref: str) -> CompiledContext:
        """Render one capability a procedure names but does not own.

        A **card**, at ROUTE, and this is the invariant the whole reference
        overlay rests on: a card carries a kind, a sentence and a ref, and
        never the `uses` of the node it describes. So one level is rendered and
        that is the end of it, exactly as opening a role stops at its members,
        and a reference cycle is two cards pointing at each other rather than
        something to traverse.
        """

        return self.find(ref).card(self)

    def schema_of(self, tool: ContextNode) -> JsonObject:
        return self.binding_of(self.ref_of(tool)).schema

    def binding_of(self, ref: str) -> Binding:
        """How the tool at `ref` is described and run.

        Present for every registered tool, because every one of them was bound
        when this view was sealed. A ref naming anything else is a caller bug
        rather than a lookup failure — `tool()` is what turns a wrong ref into
        a sentence an agent can act on, and it runs first on every path here.
        """

        return self._bindings[ref]

    def _derive_bindings(self) -> None:
        """Bind every tool in the forest, once, while sealing.

        Frozen, so this writes through `object.__setattr__` — the dictionary is
        filled here and never again, which is what "sealed" means for it too.
        """

        for node in self.manager.of_kind(Tool.kind):
            assert isinstance(node, Tool)  # `of_kind` is keyed by `Tool.kind`
            self._bindings[self.ref_of(node)] = self.bind(node)

    # ---- 2. the skeleton -------------------------------------------------

    def skeleton(self) -> CompiledContext:
        """The roots, as cards. One level, like every other call.

        This is the top sibling set and nothing below it: a root's children
        arrive when that root is opened, which an agent must do anyway to get
        its instructions. The cost of entering this server is therefore the
        number of roots, not the size of the forest.
        """

        return group_cards(self.roots, self)

    def roles_with_refs(self) -> Iterator[tuple[str, Role]]:
        """Walk the whole role axis depth-first, yielding each role's reference.

        This is for callers that legitimately want the entire forest at once —
        `contexture list` printing a tree to a terminal, or a test enumerating
        what a server can be asked. It is *not* what an agent is given; see
        `skeleton`.
        """

        for ref, node in self.nodes_with_refs():
            if isinstance(node, Role):
                yield ref, node

    def roles_by_level(self) -> Iterator[tuple[str, Role]]:
        """Walk the role axis breadth-first: every root, then every child.

        Ordering matters wherever the walk is going to be *cut off*. A
        depth-first roster truncated to a budget spends it on one deep spine
        and never mentions the root's siblings, which is the worst possible
        answer for something whose only job is routing.
        """

        queue: list[tuple[str, Role]] = [
            (root.name, root) for root in self.roots if isinstance(root, Role)
        ]
        while queue:
            ref, role = queue.pop(0)
            yield ref, role
            queue.extend(
                (f"{ref}{SEPARATOR}{child.name}", child) for child in role.branches()
            )

    def nodes_with_refs(self) -> Iterator[tuple[str, ContextNode]]:
        """Walk every node of every kind depth-first, yielding its reference.

        The role-axis walkers above answer "what roles are there"; this answers
        "what is addressable", which is what `uses` validation checks against
        and what argument completion offers a person.

        **This follows containment and never `uses`.** That is not an
        oversight to be improved on later: the reference overlay may legally
        contain cycles (ADR 008), and this walk is on the startup path, so an
        enumerator that followed references would hang the server before it
        ever served anything. Containment is a forest by construction and
        cannot.
        """

        for path, node in self.manager.walk():
            yield SEPARATOR.join(path), node

    def matching_refs(self, value: str, *, limit: int) -> tuple[tuple[str, ...], int]:
        """Rank addressable refs against what a person has typed so far.

        Returns `(matches, total)` — the first `limit` in relevance order, and
        how many matched altogether.

        **This cuts by relevance, where the roster cuts in whole sibling
        groups, and the difference is deliberate.** The roster's rule exists
        because a model shown three of a role's eight sub-roles takes three for
        the whole choice. This is read by a person watching a menu narrow as
        they type, who will simply keep typing. Same protocol, different
        consumer, so the same cut would be the wrong one.
        """

        wanted = value.strip().lower()
        scored: list[tuple[int, int, str]] = []
        for ref, _ in self.nodes_with_refs():
            lowered = ref.lower()
            if not wanted:
                rank = 0
            elif lowered.startswith(wanted):
                rank = 0
            elif lowered.rsplit(SEPARATOR, 1)[-1].startswith(wanted):
                rank = 1
            elif any(part.startswith(wanted) for part in lowered.split(SEPARATOR)):
                rank = 2
            elif wanted in lowered:
                rank = 3
            else:
                continue
            scored.append((rank, len(ref), ref))
        scored.sort()
        return tuple(ref for _, _, ref in scored[:limit]), len(scored)

    def signpost(self, ref: str) -> tuple[tuple[str, int], ...]:
        """Name the path above a node, with how many sub-roles each level holds.

        `(ancestor_ref, sub_role_count)` per level, nearest root first.

        Reaching a node directly skips the calls that would have shown what sat
        beside it on the way down, and ADR 004's rule is that a choice made
        among a subset of the alternatives is a guess rather than a choice.
        This is what keeps that rule true at an entrance that has no way down:
        it reports **that** there are siblings and how many, and never their
        names — the same shape as the roster's truncation line, which names the
        call that restores what was cut instead of spending the budget on it.

        Costed before it was written. Replaying `open` at each level runs to
        +206% of the payload it decorates on the demo and +724% on a synthetic
        forest, which re-buys every level the direct hit just saved. This runs
        to +13%, and grows with **depth** rather than breadth: eight siblings
        and three siblings render the same line.
        """

        segments = [segment for segment in ref.split(SEPARATOR) if segment]
        levels: list[tuple[str, int]] = []
        for depth in range(1, len(segments)):
            ancestor = SEPARATOR.join(segments[:depth])
            levels.append((ancestor, len(self.find(ancestor).branches())))
        return tuple(levels)

    # ---- 3. resolution ---------------------------------------------------

    def find(self, ref: str) -> ContextNode:
        """Resolve a reference to the one node it addresses."""

        segments = [segment for segment in ref.split(SEPARATOR) if segment]

        # Splitting the string is this module's half of the job; which node
        # sits at those segments is the registry's, and it answers from an
        # index rather than by walking. The whole reference is attached here
        # because only this side ever had it.
        try:
            return self.manager.find(segments)
        except NodeNotFoundError as failure:
            raise failure.within(ref) from None

    def tool(self, ref: str) -> Tool:
        """Resolve a reference that must name a tool."""

        node = self.find(ref)
        if not isinstance(node, Tool):
            raise NodeNotFoundError(
                reason=LookupFailure.WRONG_KIND,
                ref=ref,
                kind=node.kind,
                wanted=Tool.kind,
            )
        return node

    # ---- 4. opening one node ---------------------------------------------

    def open(self, ref: str) -> CompiledContext:
        """Return one node's own detail, plus a card for each member it holds.

        One line, and every kind-specific decision that used to live here now
        lives on the kind: opening a role delivers its members, opening a skill
        delivers its procedure and the cards of what it references, opening a
        tool delivers the same card the tool would have shown anywhere else.
        Adding a fourth kind would not touch this method — see ADR 014.
        """

        return self.find(ref).compile(CompileLevel.ACTIVE, view=self)

    # ---- internals -------------------------------------------------------

    def _skills(self) -> Iterator[tuple[str, Skill]]:
        """Every registered procedure, with the reference that opens it.

        From the registry's flat index rather than a walk of the forest: it is
        already kept, and asking a question about one kind should not cost a
        traversal of every other.
        """

        for node in self.manager.of_kind(Skill.kind):
            assert isinstance(node, Skill)  # `of_kind` is keyed by `Skill.kind`
            yield self.ref_of(node), node

    def _reject_unresolvable_uses(self) -> None:
        """Refuse a procedure that names something the forest cannot answer for.

        Checked when the tree is sealed, beside the separator check, because
        the alternative is discovering it when a person presses a key. A
        reference is late-bound by necessity — a skill is constructed before it
        knows where it hangs, and long before the branch it names exists — and
        sealing is the earliest moment the binding *can* be checked.

        Reference cycles are deliberately not checked. `diagnose -> remediate
        -> diagnose` is a real workflow shape, and it costs nothing here: cards
        render at ROUTE, so a cycle is two cards naming each other. See ADR 008.
        """

        for ref, node in self._skills():
            for target in node.uses:
                if target == ref:
                    raise ModelValidationError(
                        f"Skill {ref!r} names itself in `uses`. A procedure "
                        "does not need a card for the procedure it is."
                    )
                try:
                    named = self.find(target)
                except NodeNotFoundError as failure:
                    raise ModelValidationError(
                        f"Skill {ref!r} names {target!r} in `uses`, which "
                        f"resolves to nothing ({failure.reason.value}). A "
                        "procedure whose steps do not exist is a broken "
                        "procedure, and the reference is checked here so that "
                        "it fails on the way up rather than in front of a user."
                    ) from None
                if isinstance(named, Role):
                    # This also happens to reject every ancestor of `ref`,
                    # because only a Role holds members and so every ancestor
                    # is one. If Role references are ever allowed, an explicit
                    # ancestor check has to be added back: a skill naming the
                    # role it already lives inside is a modelling mistake that
                    # nothing else here would catch.
                    raise ModelValidationError(
                        f"Skill {ref!r} names the role {target!r} in `uses`. "
                        "A reference may name a skill, a tool or a resource, "
                        "never a role: routing to a role is what its own card "
                        "and `contexture_open` are for, and a procedure that "
                        "must choose a role at run time should read a resource "
                        "that lists them."
                    )

    def crossings(self) -> Iterator[tuple[str, str, str]]:
        """Yield every reference that leaves the root branch it was made from.

        `(skill_ref, target_ref, target_root)`. Nothing refuses these — a
        person composing two branches is an authorised act, and ADR 004's rule
        is about a model guessing. But a responsibility boundary that gets
        crossed silently is one nobody reviews, and the reason orchestration is
        a declared object here rather than prose in a host-side template is
        precisely that a crossing can be listed, tested and linted.
        """

        for ref, node in self._skills():
            home = ref.split(SEPARATOR, 1)[0]
            for target in node.uses:
                root = target.split(SEPARATOR, 1)[0]
                if root != home:
                    yield ref, target, root

    def _reject_ambiguous_names(self) -> None:
        """Refuse a name that would produce a reference nobody can resolve.

        A reference is a path and a node's name is one segment of it, so a name
        containing the separator silently splits into two. The card is still
        built — `card` takes the address the view gives it — and the ref on it
        addresses nothing. That is the exact failure the view's signature
        exists to prevent, arriving from the other side: not a card without a
        ref, but a ref without a node.

        Checked here rather than in registration because the separator is this
        module's decision. A node has no way to know what character will be
        used to join it to its neighbours; the view that does the joining does.

        It rides the registry's walk rather than doing its own. Registration
        has already refused a cycle, which is what makes any walk here safe.
        """

        for _, node in self.manager.walk():
            if SEPARATOR in node.name:
                raise ModelValidationError(
                    f"{node.kind} name {node.name!r} contains {SEPARATOR!r}, "
                    "which separates one segment of a reference from the next. "
                    "A card for it would carry a ref that resolves to nothing."
                )


def _is_one_root(given: Any) -> bool:
    """Whether this is a single root rather than a collection of them."""

    kinds = (Role, Skill, Tool)
    return isinstance(given, kinds) or (
        isinstance(given, type) and issubclass(given, kinds)
    )
