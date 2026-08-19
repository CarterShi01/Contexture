"""The multi-headed tree, disclosed lazily.

Below this module sits `ContextNode.compile()`, which every node answers for
itself. Above it sit the five entry points `contexture.server` puts on the
wire. This module is the whole of what joins them, and the whole of the
navigation model.

**Disclosure splits by kind, not by depth.** The role skeleton is delivered
whole: a role card carries no instructions and no schema, so the entire
organizational chart is cheap, and choosing between siblings requires seeing
all of them — what cannot be seen together is guessed between rather than
chosen between. Everything a role holds waits until that role is opened.

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
from .core.errors import ModelValidationError, NodeNotFoundError
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

        tree = ContextTree.of(KubernetesIncidentResponder(), schema_of=...)

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

    # ---- 1. the skeleton -------------------------------------------------

    def skeleton(self) -> CompiledContext:
        """Every role in the forest as a card, and nothing else.

        This is the whole of the first phase. It is safe to deliver in full,
        and cheap enough to put in the server's bootstrap text, because a role
        card is three short strings and a path.
        """

        return {"roles": [_card(role, ref) for ref, role in self.roles_with_refs()]}

    def roles_with_refs(self) -> Iterator[tuple[str, Role]]:
        """Walk the role axis depth-first, yielding each role's reference."""

        def walk(role: Role, ref: str) -> Iterator[tuple[str, Role]]:
            yield ref, role
            for child in role.children:
                yield from walk(child, f"{ref}{SEPARATOR}{child.name}")

        for root in self.roots:
            yield from walk(root, root.name)

    # ---- 2. resolution ---------------------------------------------------

    def find(self, ref: str) -> ContextNode:
        """Resolve a reference to the one node it addresses."""

        segments = [segment for segment in ref.split(SEPARATOR) if segment]
        if not segments:
            raise NodeNotFoundError(
                "A reference must name at least a root role."
            )

        node: ContextNode = self._root(segments[0])
        for segment in segments[1:]:
            if not isinstance(node, Role):
                raise NodeNotFoundError(
                    f"Reference {ref!r} continues past {node.name!r}, which is "
                    f"a {node.kind} and holds nothing."
                )
            node = _member(node, segment)
        return node

    def tool(self, ref: str) -> Tool:
        """Resolve a reference that must name a tool."""

        node = self.find(ref)
        if not isinstance(node, Tool):
            raise NodeNotFoundError(
                f"Reference {ref!r} names a {node.kind}, not a tool."
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
                f"Reference {ref!r} names a {node.kind}, not a resource."
            )
        return node

    # ---- 3. opening one node ---------------------------------------------

    def open(self, ref: str) -> CompiledContext:
        """Return one node's own detail, plus a card for each member it holds.

        This is the only path by which a Skill's instructions reach an agent.
        Opening a role delivers that role's members and does not recurse into
        sub-roles: a sub-role is a card here and a separate call when it is
        actually chosen.
        """

        node = self.find(ref)
        payload = {**node.compile(CompileLevel.ACTIVE), "ref": ref}
        if isinstance(node, Role):
            payload.update(self._members(node, ref))
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
        known = ", ".join(sorted(root.name for root in self.roots))
        raise NodeNotFoundError(
            f"No root role named {name!r}. This server serves: {known}."
        )

    def _by_uri(self, uri: str) -> Resource:
        for _, role in self.roles_with_refs():
            for resource in role.resources:
                if resource.uri == uri:
                    return resource
        raise NodeNotFoundError(f"No resource is published at {uri!r}.")


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


def _member(role: Role, name: str) -> ContextNode:
    for group in (role.children, role.skills, role.tools, role.resources):
        for member in group:
            if member.name == name:
                return member

    held = sorted(
        member.name
        for group in (role.children, role.skills, role.tools, role.resources)
        for member in group
    )
    raise NodeNotFoundError(
        f"Role {role.name!r} holds no member named {name!r}. It holds: "
        f"{', '.join(held) if held else 'nothing'}."
    )


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
