"""Tests for class-syntax declaration of roles and skills."""

from __future__ import annotations

import unittest

from contexture import DeclarationError, Role, Skill, Tool


class GetPods(Tool):
    """List pods in a namespace."""

    read_only = True

    async def invoke(self, namespace: str) -> str:
        return namespace


class Runbook(Tool):
    """Incident runbook."""

    name = "runbook"
    read_only = True

    async def invoke(self) -> str:
        return "runbook"


class Diagnose(Skill):
    """Diagnose why a deployment is unhealthy."""

    instructions = "1. Inspect rollout status."


class NameDerivationTests(unittest.TestCase):
    def test_class_name_becomes_kebab_case(self) -> None:
        class KubernetesOperator(Role):
            """Operate Kubernetes workloads."""

            instructions = "Inspect first."

        self.assertEqual(KubernetesOperator().name, "kubernetes-operator")

    def test_acronym_runs_stay_together(self) -> None:
        class MCPGatewayRole(Role):
            """Front the MCP gateway."""

            instructions = "Route requests."

        self.assertEqual(MCPGatewayRole().name, "mcp-gateway-role")

    def test_digits_do_not_split_a_word(self) -> None:
        class K8sOperator(Role):
            """Operate the cluster."""

            instructions = "Inspect first."

        self.assertEqual(K8sOperator().name, "k8s-operator")

    def test_an_explicit_name_wins(self) -> None:
        class KubernetesOperator(Role):
            """Operate Kubernetes workloads."""

            name = "k8s-op"
            instructions = "Inspect first."

        self.assertEqual(KubernetesOperator().name, "k8s-op")

    def test_docstring_becomes_the_routing_description(self) -> None:
        class Operator(Role):
            """Operate the cluster.

            This second paragraph is design commentary and must not leak into
            the routing card.
            """

            instructions = "Inspect first."

        self.assertEqual(Operator().description, "Operate the cluster.")


class MemberCollectionTests(unittest.TestCase):
    def test_declared_skill_class_is_instantiated(self) -> None:
        class Troubleshooter(Role):
            """Diagnose failures."""

            instructions = "Read only."
            diagnose = Diagnose

        role = Troubleshooter()
        self.assertEqual([skill.name for skill in role.skills], ["diagnose"])
        self.assertIsInstance(role.skills[0], Skill)

    def test_a_declared_skill_instance_is_used_as_is(self) -> None:
        shared = Skill(
            name="shared", description="Shared knowledge.", instructions="Do it."
        )

        class Troubleshooter(Role):
            """Diagnose failures."""

            instructions = "Read only."
            reuse = shared

        self.assertIs(Troubleshooter().skills[0], shared)

    def test_members_land_in_their_own_lists(self) -> None:
        class Child(Role):
            """A child role."""

            instructions = "Do child work."

        class Parent(Role):
            """A parent role."""

            instructions = "Route work."
            child = Child
            pods = GetPods
            runbook = Runbook

        role = Parent()
        self.assertEqual([c.name for c in role.children], ["child"])
        self.assertEqual(
            sorted(t.name for t in role.tools), ["get-pods", "runbook"]
        )
        self.assertEqual(role.skills, [])

    def test_declaration_order_is_preserved(self) -> None:
        class First(Skill):
            """First skill."""

            instructions = "One."

        class Second(Skill):
            """Second skill."""

            instructions = "Two."

        class Ordered(Role):
            """Ordered role."""

            instructions = "Go."
            alpha = First
            beta = Second

        self.assertEqual([s.name for s in Ordered().skills], ["first", "second"])


class InheritanceTests(unittest.TestCase):
    def test_a_subclass_inherits_declared_members(self) -> None:
        class Base(Role):
            """Base role."""

            instructions = "Base behaviour."
            diagnose = Diagnose

        class Derived(Base):
            """Derived role."""

            instructions = "Derived behaviour."

        derived = Derived()
        self.assertEqual(derived.name, "derived")
        self.assertEqual(derived.instructions, "Derived behaviour.")
        self.assertEqual([s.name for s in derived.skills], ["diagnose"])

    def test_a_subclass_can_replace_an_inherited_member(self) -> None:
        class Replacement(Skill):
            """Replacement knowledge."""

            instructions = "Different."

        class Base(Role):
            """Base role."""

            instructions = "Base."
            diagnose = Diagnose

        class Derived(Base):
            """Derived role."""

            instructions = "Derived."
            diagnose = Replacement

        self.assertEqual([s.name for s in Derived().skills], ["replacement"])

    def test_a_declared_role_is_substitutable_for_role(self) -> None:
        class Declared(Role):
            """Declared role."""

            instructions = "Go."

        self.assertIsInstance(Declared(), Role)


class OverrideTests(unittest.TestCase):
    def test_construction_arguments_override_the_declaration(self) -> None:
        class Operator(Role):
            """Operate the cluster."""

            instructions = "Inspect first."

        role = Operator(name="staging-operator", description="Staging only.")
        self.assertEqual(role.name, "staging-operator")
        self.assertEqual(role.description, "Staging only.")
        self.assertEqual(role.instructions, "Inspect first.")


class FailFastTests(unittest.TestCase):
    def test_a_role_without_instructions_is_rejected_at_class_creation(self) -> None:
        with self.assertRaises(DeclarationError):

            class NoInstructions(Role):
                """A role with nothing to say."""

    def test_a_role_without_a_description_is_rejected(self) -> None:
        with self.assertRaises(DeclarationError):

            class NoDescription(Role):
                instructions = "Go."

    def test_an_inherited_docstring_does_not_count_as_a_description(self) -> None:
        class Base(Role):
            """Base role."""

            instructions = "Go."

        with self.assertRaises(DeclarationError):

            class Derived(Base):
                instructions = "Still go."

    def test_a_skill_without_instructions_is_rejected_at_instantiation(self) -> None:
        class Empty(Skill):
            """A skill with no procedure."""

        with self.assertRaises(Exception):
            Empty()

    def test_colliding_skill_names_are_rejected_at_class_creation(self) -> None:
        first = Skill(name="same", description="First.", instructions="A.")
        second = Skill(name="same", description="Second.", instructions="B.")

        with self.assertRaises(DeclarationError) as caught:

            class Colliding(Role):
                """Two skills, one name."""

                instructions = "Go."
                alpha = first
                beta = second

        message = str(caught.exception)
        self.assertIn("alpha", message)
        self.assertIn("beta", message)

    def test_a_non_string_scalar_is_rejected(self) -> None:
        with self.assertRaises(DeclarationError):

            class BadInstructions(Role):
                """A role whose instructions are not text."""

                instructions = 42


class IntrospectionTests(unittest.TestCase):
    def test_the_declaration_is_readable_without_instantiating(self) -> None:
        class Troubleshooter(Role):
            """Diagnose failures."""

            instructions = "Read only."
            diagnose = Diagnose
            pods = GetPods

        declaration = Troubleshooter.declaration
        assert declaration is not None
        self.assertEqual(declaration.owner, "Troubleshooter")
        self.assertEqual(declaration.name, "troubleshooter")
        self.assertEqual(len(declaration.of_type(Tool)), 1)
        self.assertEqual(
            declaration.attribute_of(declaration.of_type(Tool)[0]), "pods"
        )

    def test_an_imperative_role_has_no_declaration(self) -> None:
        role = Role(name="r", description="A role.", instructions="Go.")
        self.assertIsNone(type(role).declaration)
