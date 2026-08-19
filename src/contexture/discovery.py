"""Progressive disclosure as navigation over the declared capability graph.

The compiler below this layer answers "how much of one node becomes visible?".
This layer answers the question a connected agent actually asks: "where am I,
what is next to me, and how do I get to the thing I need?"

Two operations carry the whole vocabulary::

    discover(ref)      what is here, as routing cards — cheap, no instructions
    get_context(ref)   the detail for one node the agent has now chosen

The tree is deliberately not part of the MCP surface. MCP's tool and resource
lists are flat and, since the 2026-07-28 revision, explicitly stateless: a
server may not vary them per connection or as a side effect of earlier calls.
So the graph lives inside the *payload* of these two tools instead, and an
agent's position in it is not server state — it is the `ref` the agent carries
into the next request. That is what makes traversal legal here: `get_context`
is a pure function of its ref, never of what was asked before it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Iterator, Sequence

from .compiler import CompileRequest, RoleCompiler
from .core.context import CompileLevel
from .core.errors import ModelValidationError, NodeNotFoundError
from .core.registry import RoleRegistry
from .core.role import Role
from .core.types import CompiledContext

#: Separates a role path from the capability named inside that role.
LEAF_SEPARATOR = "#"

#: Ref kinds this layer can address.
ROLE = "role"
SKILL = "skill"
TOOL = "tool"
RESOURCE = "resource"

_KINDS = frozenset({ROLE, SKILL, TOOL, RESOURCE})


@dataclass(slots=True, frozen=True, kw_only=True)
class Ref:
    """A stable address for one node in the capability graph.

    A ref is the agent's coordinate, and it travels in the agent's own context
    rather than in the server's::

        role:engineering-team/k8s-troubleshooter
        skill:engineering-team/k8s-troubleshooter#inspect-pod-failure
        tool:engineering-team/k8s-troubleshooter#get-pod-logs
        resource:engineering-team/k8s-troubleshooter#contexture://runbooks/x

    The leaf is separated by `#` rather than `/` because resource URIs contain
    slashes of their own, and an address a reader cannot split by eye is an
    address that will eventually be split wrong.
    """

    kind: str
    role_path: tuple[str, ...]
    leaf: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise NodeNotFoundError(
                f"Unknown reference kind {self.kind!r}; expected one of "
                f"{sorted(_KINDS)}."
            )
        if not self.role_path:
            raise NodeNotFoundError("A reference must name at least a root role.")
        if self.kind == ROLE and self.leaf is not None:
            raise NodeNotFoundError("A role reference must not carry a leaf name.")
        if self.kind != ROLE and not self.leaf:
            raise NodeNotFoundError(
                f"A {self.kind} reference must name the capability after "
                f"{LEAF_SEPARATOR!r}."
            )

    @classmethod
    def parse(cls, raw: str) -> Ref:
        if not isinstance(raw, str) or not raw.strip():
            raise NodeNotFoundError("A reference must be a non-empty string.")

        kind, separator, remainder = raw.strip().partition(":")
        if not separator:
            raise NodeNotFoundError(
                f"Reference {raw!r} must start with a kind, for example "
                f"'role:{raw}'."
            )

        path_part, leaf_separator, leaf = remainder.partition(LEAF_SEPARATOR)
        components = tuple(part for part in path_part.split("/") if part)
        return cls(
            kind=kind,
            role_path=components,
            leaf=leaf if leaf_separator else None,
        )

    @property
    def role_path_str(self) -> str:
        return "/".join(self.role_path)

    def __str__(self) -> str:
        base = f"{self.kind}:{self.role_path_str}"
        if self.leaf is None:
            return base
        return f"{base}{LEAF_SEPARATOR}{self.leaf}"


@dataclass(slots=True, kw_only=True)
class CapabilityGraph:
    """Every declared root and the roles reachable beneath them.

    A server exposes a forest rather than a single root on purpose. Fixing one
    root at launch would force one process per role, and a role tree is a
    navigation structure, not a deployment unit.
    """

    roots: tuple[Role, ...]
    _registries: dict[str, RoleRegistry] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.roots:
            raise ModelValidationError(
                "A capability graph needs at least one root role."
            )
        registries: dict[str, RoleRegistry] = {}
        for root in self.roots:
            if root.name in registries:
                raise ModelValidationError(
                    f"Two root roles are both named {root.name!r}; a root name "
                    "is the first component of every reference below it."
                )
            registries[root.name] = RoleRegistry(root=root)
        self._registries = registries

    def resolve_role(self, path: Sequence[str] | str) -> Role:
        components = (
            tuple(part for part in path.split("/") if part)
            if isinstance(path, str)
            else tuple(path)
        )
        if not components:
            raise NodeNotFoundError("A role path must name at least a root role.")
        registry = self._registries.get(components[0])
        if registry is None:
            raise NodeNotFoundError(
                f"No root role named {components[0]!r}. Known roots: "
                f"{sorted(self._registries)}."
            )
        return registry.resolve(components)

    def iter_roles(self) -> Iterator[tuple[str, Role]]:
        for registry in self._registries.values():
            yield from registry.iter_roles()

    def local_tools(self) -> Iterator[tuple[str, Role, object]]:
        """Yield every locally implemented tool reachable in the graph."""

        seen: set[int] = set()
        for path, role in self.iter_roles():
            for tool in role.tools:
                if id(tool) in seen:
                    continue
                seen.add(id(tool))
                yield path, role, tool

    def local_resources(self) -> Iterator[tuple[str, Role, object]]:
        """Yield every locally implemented resource reachable in the graph."""

        seen: set[int] = set()
        for path, role in self.iter_roles():
            for resource in role.resources:
                if id(resource) in seen:
                    continue
                seen.add(id(resource))
                yield path, role, resource


@dataclass(slots=True, kw_only=True)
class DisclosureEngine:
    """Turn refs into the smallest context that answers the current question."""

    graph: CapabilityGraph
    compiler: RoleCompiler = field(default_factory=RoleCompiler)

    def discover(self, ref: str | None = None) -> CompiledContext:
        """Return routing cards only — never instructions, never content.

        With no ref this is the entry point to the forest: every root, one card
        each. With a ref it is one step of traversal: what sits directly under
        the named role, each card carrying the ref needed to go deeper.
        """

        if ref is None or not str(ref).strip():
            return {
                "roots": [
                    self._card(root, Ref(kind=ROLE, role_path=(root.name,)))
                    for root in self.graph.roots
                ]
            }

        parsed = Ref.parse(ref)
        if parsed.kind != ROLE:
            raise NodeNotFoundError(
                f"discover expects a role reference; {ref!r} names a "
                f"{parsed.kind}. Use get_context for a specific capability."
            )

        role = self.graph.resolve_role(parsed.role_path)
        path = parsed.role_path
        return {
            "ref": str(parsed),
            "role": self._card(role, parsed),
            "sub_roles": [
                self._card(child, Ref(kind=ROLE, role_path=path + (child.name,)))
                for child in role.children
            ],
            "skills": [
                self._card(skill, Ref(kind=SKILL, role_path=path, leaf=skill.name))
                for skill in role.skills
            ],
            "tools": [
                self._card(tool, Ref(kind=TOOL, role_path=path, leaf=tool.name))
                for tool in role.tools
            ],
            "resources": [
                self._card(
                    resource,
                    Ref(kind=RESOURCE, role_path=path, leaf=resource.uri),
                )
                for resource in role.resources
            ],
        }

    def get_context(self, ref: str) -> CompiledContext:
        """Return the active detail for exactly one node.

        This is the only path by which a Skill's instructions enter an agent's
        context. Discovery above never carries them, which is the whole point:
        a hundred reachable skills cost a hundred one-line cards, and only the
        chosen one costs its full procedure.
        """

        parsed = Ref.parse(ref)
        role = self.graph.resolve_role(parsed.role_path)

        if parsed.kind == ROLE:
            compiled = self.compiler.compile(
                role,
                CompileRequest(level=CompileLevel.ACTIVE),
            )
            return {"ref": str(parsed), **compiled.role}

        if parsed.kind == SKILL:
            skill = role.get_skill(parsed.leaf or "")
            return {"ref": str(parsed), **skill.compile(CompileLevel.ACTIVE)}

        if parsed.kind == TOOL:
            tool = role.get_tool(parsed.leaf or "")
            return {"ref": str(parsed), **tool.compile(CompileLevel.ACTIVE)}

        resource = role.get_resource(parsed.leaf or "")
        # Descriptor only. Content is read over resources/read, never here, so
        # that discovering a document and paying for it stay separate acts.
        return {"ref": str(parsed), **resource.compile(CompileLevel.ACTIVE)}

    @staticmethod
    def _card(node: object, ref: Ref) -> CompiledContext:
        route = node.compile(CompileLevel.ROUTE)  # type: ignore[attr-defined]
        return {**route, "ref": str(ref)}


def build_graph(roots: Role | Iterable[Role]) -> CapabilityGraph:
    """Accept one root or many, and return the graph either way."""

    if isinstance(roots, Role):
        return CapabilityGraph(roots=(roots,))
    return CapabilityGraph(roots=tuple(roots))


__all__ = [
    "CapabilityGraph",
    "DisclosureEngine",
    "LEAF_SEPARATOR",
    "RESOURCE",
    "ROLE",
    "Ref",
    "SKILL",
    "TOOL",
    "build_graph",
]
