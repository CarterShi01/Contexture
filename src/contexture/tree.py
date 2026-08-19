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

from .core.context import CompileLevel, ContextNode
from .core.errors import LookupFailure, ModelValidationError, NodeNotFoundError
from .core.resources import Resource
from .core.role import Role
from .core.tools import Tool
from .core.types import CompiledContext, JsonObject

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

    def resource(self, ref: str) -> Resource:
        """Resolve a resource, by reference or by its own URI.

        Both spellings are accepted on purpose. A skill's instructions are
        written by whoever owns the domain, and they name a document the way
        the document names itself — `contexture://runbooks/crash-loop-backoff`,
        not a path through the role tree. Refusing that spelling would make
        this framework's addressing scheme the author's problem to remember.
        """

        node = self._by_uri(ref) if "://" in ref else self.find(ref)
        if not isinstance(node, Resource):
            raise NodeNotFoundError(
                reason=LookupFailure.WRONG_KIND,
                ref=ref,
                kind=node.kind,
                wanted=Resource.kind,
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
        return payload

    def _members(self, role: Role, ref: str) -> CompiledContext:
        def at(name: str) -> str:
            return f"{ref}{SEPARATOR}{name}"

        return {
            "sub_roles": [_card(child, at(child.name)) for child in role.children],
            "skills": [_card(skill, at(skill.name)) for skill in role.skills],
            "tools": [self._tool_card(tool, at(tool.name)) for tool in role.tools],
            "resources": [
                _resource_card(resource, at(resource.name))
                for resource in role.resources
            ],
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

    def _root(self, name: str) -> Role:
        for root in self.roots:
            if root.name == name:
                return root
        raise NodeNotFoundError(
            reason=LookupFailure.NO_SUCH_ROOT,
            scope=name,
            known=sorted(root.name for root in self.roots),
        )

    def _by_uri(self, uri: str) -> Resource:
        for _, role in self.roles_with_refs():
            for resource in role.resources:
                if resource.uri == uri:
                    return resource
        raise NodeNotFoundError(reason=LookupFailure.NO_SUCH_URI, ref=uri)


def _card(node: ContextNode, ref: str) -> CompiledContext:
    """Render one routing card.

    Taking the reference as an argument is the point: a card cannot be built
    without one, so a card that can be seen can always be opened. That was not
    true while roles rendered their own members.
    """

    return {**node.compile(CompileLevel.ROUTE), "ref": ref}


def _resource_card(resource: Resource, ref: str) -> CompiledContext:
    card = {**_card(resource, ref), "uri": resource.uri}
    if resource.mime_type is not None:
        card["mime_type"] = resource.mime_type
    return card


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
