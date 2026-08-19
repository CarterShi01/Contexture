"""Tests for role path resolution and cycle detection."""

from __future__ import annotations

import unittest

from contexture import ModelValidationError, Role, RoleRegistry


class RegistryTests(unittest.TestCase):
    def test_resolves_explicit_role_path(self) -> None:
        child = Role(
            name="child",
            description="Handle child work.",
            instructions="Perform child work.",
        )
        root = Role(
            name="root",
            description="Coordinate work.",
            instructions="Route work.",
            children=[child],
        )
        registry = RoleRegistry(root=root)
        self.assertIs(registry.resolve("root/child"), child)

    def test_rejects_composition_cycle(self) -> None:
        root = Role(
            name="root",
            description="Coordinate work.",
            instructions="Route work.",
        )
        child = Role(
            name="child",
            description="Handle child work.",
            instructions="Perform child work.",
        )
        root.children.append(child)
        child.children.append(root)

        with self.assertRaises(ModelValidationError):
            RoleRegistry(root=root)
