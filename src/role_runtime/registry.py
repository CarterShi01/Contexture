"""Role-tree validation and path resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Sequence

from .errors import ModelValidationError, NodeNotFoundError
from .role import Role


@dataclass(slots=True, kw_only=True)
class RoleRegistry:
    """Resolve roles by explicit object-composition paths."""

    root: Role

    def __post_init__(self) -> None:
        self._validate_no_cycles()

    def resolve(self, path: str | Sequence[str]) -> Role:
        components = self._normalize(path)
        if not components or components[0] != self.root.name:
            raise NodeNotFoundError(
                f"Role path must begin with root role {self.root.name!r}."
            )

        current = self.root
        for component in components[1:]:
            current = current.get_child(component)
        return current

    def iter_roles(self) -> Iterator[tuple[str, Role]]:
        """Yield every reachable role path; shared objects may have many paths."""

        def walk(role: Role, path: tuple[str, ...]) -> Iterator[tuple[str, Role]]:
            yield "/".join(path), role
            for child in role.children:
                yield from walk(child, path + (child.name,))

        yield from walk(self.root, (self.root.name,))

    @staticmethod
    def _normalize(path: str | Sequence[str]) -> tuple[str, ...]:
        if isinstance(path, str):
            components = tuple(part for part in path.split("/") if part)
        else:
            components = tuple(path)
        if any(not component for component in components):
            raise NodeNotFoundError("Role path contains an empty component.")
        return components

    def _validate_no_cycles(self) -> None:
        def walk(role: Role, stack: tuple[int, ...], path: tuple[str, ...]) -> None:
            identity = id(role)
            if identity in stack:
                raise ModelValidationError(
                    "Role composition contains a cycle at path "
                    f"{'/'.join(path)}."
                )
            next_stack = stack + (identity,)
            for child in role.children:
                walk(child, next_stack, path + (child.name,))

        walk(self.root, (), (self.root.name,))
