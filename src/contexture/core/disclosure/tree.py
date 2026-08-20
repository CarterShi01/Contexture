"""The multi-headed tree, disclosed lazily.

Below this module sits `ContextNode.compile()`, which every node answers for
itself. Above it sit the five entry points `contexture.server` puts on the
wire. This module is the whole of what joins them, and the whole of the
navigation model.

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
write one: every card carries the reference that opens it, because `_card`
cannot be called without one.

**Nothing here is remembered.** Every method is a pure function of its
argument, which is what keeps traversal legal on a protocol that, since the
2026-07-28 revision, forbids a server to vary its surface per connection or as
a consequence of an earlier call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator

from ..model.node import CompileLevel, ContextNode
from ..errors import LookupFailure, ModelValidationError, NodeNotFoundError
from ..model.role import Role
from ..model.skill import Skill
from ..model.tool import Tool
from ..types import CompiledContext, JsonObject

#: Separates one segment of a reference from the next.
SEPARATOR = "/"


def _no_schema(tool: Tool) -> JsonObject:
    """Stand in when nobody supplied a schema source.

    A tree built without one is a tree nobody is serving — a test, or a caller
    that only wants to navigate. Returning an empty schema is more useful there
    than requiring every such caller to pass a function it does not need.
    """

    return {}


@dataclass(frozen=True, slots=True)
class ContextTree:
    """A forest of roles, and everything a server needs to disclose it.

    Built once from the declared roots::

        tree = ContextTree.of(KubernetesPlatform(), schema_of=...)

    `schema_of` is how a tool's input schema arrives without this module
    knowing what JSON Schema is. The server layer passes one backed by the MCP
    SDK; nothing here imports it.
    """

    roots: tuple[Role, ...]
    schema_of: Callable[[Tool], JsonObject] = field(default=_no_schema)

    @classmethod
    def of(
        cls,
        roots: Role | Iterable[Role],
        *,
        schema_of: Callable[[Tool], JsonObject] = _no_schema,
    ) -> ContextTree:
        """Accept one root or many, and return the tree either way."""

        collected = (roots,) if isinstance(roots, Role) else tuple(roots)
        return cls(roots=collected, schema_of=schema_of)

    def __post_init__(self) -> None:
        if not self.roots:
            raise ModelValidationError("A context tree needs at least one root role.")

        seen: set[str] = set()
        for root in self.roots:
            if root.name in seen:
                raise ModelValidationError(
                    f"Two root roles are both named {root.name!r}; a root name "
                    "is the first segment of every reference beneath it."
                )
            seen.add(root.name)
            _reject_cycles(root)
            _reject_ambiguous_names(root)

        # Runs last, and over the whole forest rather than per root: a `uses`
        # entry may name any branch, so it cannot be checked until every root
        # is known to be walkable. The two checks above are what make that
        # walk safe.
        self._reject_unresolvable_uses()

    # ---- 1. the skeleton -------------------------------------------------

    def skeleton(self) -> CompiledContext:
        """The roots, as cards. One level, like every other call.

        This is the top sibling set and nothing below it: a root's children
        arrive when that root is opened, which an agent must do anyway to get
        its instructions. The cost of entering this server is therefore the
        number of roots, not the size of the forest.
        """

        return {"roles": [_card(root, root.name) for root in self.roots]}

    def roles_with_refs(self) -> Iterator[tuple[str, Role]]:
        """Walk the whole role axis depth-first, yielding each role's reference.

        This is for callers that legitimately want the entire forest at once —
        `contexture list` printing a tree to a terminal, or a test enumerating
        what a server can be asked. It is *not* what an agent is given; see
        `skeleton`.
        """

        def walk(role: Role, ref: str) -> Iterator[tuple[str, Role]]:
            yield ref, role
            for child in role.children:
                yield from walk(child, f"{ref}{SEPARATOR}{child.name}")

        for root in self.roots:
            yield from walk(root, root.name)

    def roles_by_level(self) -> Iterator[tuple[str, Role]]:
        """Walk the role axis breadth-first: every root, then every child.

        Ordering matters wherever the walk is going to be *cut off*. A
        depth-first roster truncated to a budget spends it on one deep spine
        and never mentions the root's siblings, which is the worst possible
        answer for something whose only job is routing.
        """

        queue: list[tuple[str, Role]] = [(root.name, root) for root in self.roots]
        while queue:
            ref, role = queue.pop(0)
            yield ref, role
            queue.extend(
                (f"{ref}{SEPARATOR}{child.name}", child) for child in role.children
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

        def walk(node: ContextNode, ref: str) -> Iterator[tuple[str, ContextNode]]:
            yield ref, node
            if isinstance(node, Role):
                for member in node.members():
                    yield from walk(member, f"{ref}{SEPARATOR}{member.name}")

        for root in self.roots:
            yield from walk(root, root.name)

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
            node = self.find(ancestor)
            levels.append(
                (ancestor, len(node.children) if isinstance(node, Role) else 0)
            )
        return tuple(levels)

    # ---- 2. resolution ---------------------------------------------------

    def find(self, ref: str) -> ContextNode:
        """Resolve a reference to the one node it addresses."""

        segments = [segment for segment in ref.split(SEPARATOR) if segment]
        if not segments:
            raise NodeNotFoundError(reason=LookupFailure.EMPTY_REF, ref=ref)

        # One try around the whole walk. A role knows its own name and what it
        # holds; only this method knows the path being walked, so the failure
        # collects that on its way back up rather than being handed down into
        # every lookup that is about to succeed.
        try:
            node: ContextNode = self._root(segments[0])
            for segment in segments[1:]:
                if not isinstance(node, Role):
                    raise NodeNotFoundError(
                        reason=LookupFailure.NOT_A_CONTAINER,
                        segment=segment,
                        scope=node.name,
                        kind=node.kind,
                    )
                node = node.member(segment)
        except NodeNotFoundError as failure:
            raise failure.within(ref) from None
        return node

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

    # ---- 3. opening one node ---------------------------------------------

    def open(self, ref: str) -> CompiledContext:
        """Return one node's own detail, plus a card for each member it holds.

        This is the only path by which a Skill's instructions reach an agent.
        Opening a role delivers that role's members and does not recurse into
        sub-roles: a sub-role is a card here and a separate call when it is
        actually chosen.

        A tool opened directly answers with the same `input_schema` its card
        carries. Reaching a capability two ways and being told two different
        things about how to call it is worse than either answer alone.
        """

        node = self.find(ref)
        payload = {**node.compile(CompileLevel.ACTIVE), "ref": ref}
        if isinstance(node, Role):
            payload.update(self._members(node, ref))
        elif isinstance(node, Tool):
            payload["input_schema"] = self.schema_of(node)
        elif isinstance(node, Skill) and node.uses:
            payload["uses"] = [self._reference_card(ref) for ref in node.uses]
        return payload

    def _reference_card(self, ref: str) -> CompiledContext:
        """Render one capability a procedure names but does not own.

        A **card**, at ROUTE, and this is the invariant the whole reference
        overlay rests on: a card carries a kind, a sentence and a ref, and
        never the `uses` of the node it describes. So the server renders one
        level and stops, exactly as `open` does for sub-roles, and a reference
        cycle is two cards pointing at each other rather than something to
        traverse. Expanding to ACTIVE here would make `A -> B -> A` unbounded.

        A tool card is the fuller `_tool_card`, because a tool reached this way
        must be callable from what arrives — sending an agent for a second call
        to fetch a schema it was always going to need buys nothing.
        """

        node = self.find(ref)
        if isinstance(node, Tool):
            return self._tool_card(node, ref)
        return _card(node, ref)

    def _members(self, role: Role, ref: str) -> CompiledContext:
        def at(name: str) -> str:
            return f"{ref}{SEPARATOR}{name}"

        return {
            "sub_roles": [_card(child, at(child.name)) for child in role.children],
            "skills": [_card(skill, at(skill.name)) for skill in role.skills],
            "tools": [self._tool_card(tool, at(tool.name)) for tool in role.tools],
        }

    def _tool_card(self, tool: Tool, ref: str) -> CompiledContext:
        # read_only is a host classification, reported so a host can act on it
        # and never accepted as an argument a model could fill in.
        return {
            **_card(tool, ref),
            "read_only": tool.read_only,
            "input_schema": self.schema_of(tool),
        }

    # ---- internals -------------------------------------------------------

    def _reject_unresolvable_uses(self) -> None:
        """Refuse a procedure that names something the forest cannot answer for.

        Checked when the tree is built, beside the cycle and separator checks,
        because the alternative is discovering it when a person presses a key.
        A reference is late-bound by necessity — a skill is constructed before
        it knows where it hangs, and long before the branch it names exists —
        and build time is the earliest moment the binding *can* be checked.

        Reference cycles are deliberately not checked. `diagnose -> remediate
        -> diagnose` is a real workflow shape, and it costs nothing here: cards
        render at ROUTE, so a cycle is two cards naming each other. See ADR 008.
        """

        for ref, node in self.nodes_with_refs():
            if not isinstance(node, Skill):
                continue
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

        for ref, node in self.nodes_with_refs():
            if not isinstance(node, Skill):
                continue
            home = ref.split(SEPARATOR, 1)[0]
            for target in node.uses:
                root = target.split(SEPARATOR, 1)[0]
                if root != home:
                    yield ref, target, root

    def _root(self, name: str) -> Role:
        for root in self.roots:
            if root.name == name:
                return root
        raise NodeNotFoundError(
            reason=LookupFailure.NO_SUCH_ROOT,
            scope=name,
            known=sorted(root.name for root in self.roots),
        )


def _card(node: ContextNode, ref: str) -> CompiledContext:
    """Render one routing card.

    Taking the reference as an argument is the point: a card cannot be built
    without one, so a card that can be seen can always be opened. That was not
    true while roles rendered their own members.
    """

    return {**node.compile(CompileLevel.ROUTE), "ref": ref}


def _reject_ambiguous_names(root: Role) -> None:
    """Refuse a name that would produce a reference nobody can resolve.

    A reference is a path and a node's name is one segment of it, so a name
    containing the separator silently splits into two. The card is still built
    — `_card` takes the ref it is given — and the ref on it addresses nothing.
    That is the exact failure `_card`'s signature exists to prevent, arriving
    from the other side: not a card without a ref, but a ref without a node.

    Checked here rather than in `core` because the separator is this module's
    decision. A node has no way to know what character will be used to join it
    to its neighbours; the tree that does the joining does.

    Runs after `_reject_cycles`, which is what makes walking the forest safe.
    """

    stack = [root]
    while stack:
        role = stack.pop()
        for node in (role, *role.members()):
            if SEPARATOR in node.name:
                raise ModelValidationError(
                    f"{node.kind} name {node.name!r} contains {SEPARATOR!r}, "
                    "which separates one segment of a reference from the next. "
                    "A card for it would carry a ref that resolves to nothing."
                )
        stack.extend(role.children)


def _reject_cycles(root: Role) -> None:
    """Refuse a role that contains itself, however indirectly.

    A cycle is only visible once the whole forest is in hand, which is here and
    not in `core`: a role on its own cannot tell whether something below it
    points back.
    """

    def walk(role: Role, stack: tuple[int, ...], path: tuple[str, ...]) -> None:
        if id(role) in stack:
            raise ModelValidationError(
                f"Role composition contains a cycle at path {SEPARATOR.join(path)}."
            )
        for child in role.children:
            walk(child, stack + (id(role),), path + (child.name,))

    walk(root, (), (root.name,))


__all__ = ["ContextTree", "SEPARATOR"]
