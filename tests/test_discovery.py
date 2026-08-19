"""Tests for navigation over the capability graph.

The property under test is not "does discover return something" but the split
that makes progressive disclosure worth having: routing is cheap and repeated,
detail is expensive and requested once. A change that quietly moves a skill's
instructions into a routing card would keep every other test passing.
"""

from __future__ import annotations

import json
import unittest

from contexture.core.errors import ModelValidationError, NodeNotFoundError
from contexture.core.resources import Resource
from contexture.core.role import Role
from contexture.core.skill import Skill
from contexture.core.tools import Tool
from contexture.discovery import (
    CapabilityGraph,
    DisclosureEngine,
    Ref,
    build_graph,
)

PROCEDURE = "SECRET-PROCEDURE-MARKER"


class GetPodLogs(Tool):
    """Return recent container logs for one Pod."""

    name = "get_pod_logs"
    read_only = True

    async def invoke(self, namespace: str, pod: str) -> str:
        return f"logs for {namespace}/{pod}"


class DeletePod(Tool):
    """Delete a Pod so its controller recreates it."""

    name = "delete_pod"

    async def invoke(self, namespace: str, pod: str) -> str:
        return "deleted"


class Runbook(Resource):
    """How to diagnose a restart loop."""

    uri = "contexture://runbooks/crash-loop"
    mime_type = "text/markdown"

    async def read(self) -> str:
        return "# runbook body"


class Diagnose(Skill):
    """Diagnose a Pod that keeps restarting."""

    name = "diagnose"
    instructions = f"1. status 2. logs. {PROCEDURE}"


class Troubleshooter(Role):
    """Diagnose unhealthy Pods without changing the cluster."""

    instructions = "Read-only inspection only."

    diagnose = Diagnose
    logs = GetPodLogs
    runbook = Runbook


class Operator(Role):
    """Perform approved remediation on Kubernetes workloads."""

    instructions = "Inspect before changing anything."

    remove = DeletePod


class Team(Role):
    """Coordinate the Kubernetes specialists."""

    instructions = "Route to the specialist that owns the symptom."

    troubleshooter = Troubleshooter
    operator = Operator


def _engine(*roots: Role) -> DisclosureEngine:
    return DisclosureEngine(graph=build_graph(roots or (Team(),)))


class RefTests(unittest.TestCase):
    def test_a_ref_round_trips_through_its_string_form(self) -> None:
        for raw in (
            "role:team/troubleshooter",
            "skill:team/troubleshooter#diagnose",
            "tool:team/troubleshooter#get_pod_logs",
            "resource:team/troubleshooter#contexture://runbooks/crash-loop",
        ):
            with self.subTest(ref=raw):
                self.assertEqual(str(Ref.parse(raw)), raw)

    def test_a_resource_uri_keeps_its_own_slashes(self) -> None:
        """The reason the leaf separator is `#` and not `/`."""

        parsed = Ref.parse("resource:team#contexture://runbooks/a/b/c")
        self.assertEqual(parsed.role_path, ("team",))
        self.assertEqual(parsed.leaf, "contexture://runbooks/a/b/c")

    def test_a_ref_without_a_kind_is_refused_with_an_example(self) -> None:
        with self.assertRaises(NodeNotFoundError) as caught:
            Ref.parse("team/troubleshooter")
        self.assertIn("role:", str(caught.exception))

    def test_a_capability_ref_must_name_its_leaf(self) -> None:
        with self.assertRaises(NodeNotFoundError):
            Ref.parse("skill:team/troubleshooter")

    def test_a_role_ref_must_not_carry_a_leaf(self) -> None:
        with self.assertRaises(NodeNotFoundError):
            Ref.parse("role:team#diagnose")

    def test_an_unknown_kind_lists_the_known_ones(self) -> None:
        with self.assertRaises(NodeNotFoundError) as caught:
            Ref.parse("runbook:team#x")
        self.assertIn("resource", str(caught.exception))


class DiscoveryTests(unittest.TestCase):
    def test_the_entry_point_lists_every_root(self) -> None:
        engine = _engine(Troubleshooter(), Operator())
        roots = engine.discover()["roots"]

        self.assertEqual(
            [card["name"] for card in roots],
            ["troubleshooter", "operator"],
        )

    def test_every_card_carries_the_ref_that_opens_it(self) -> None:
        """A card without a ref is a dead end: the agent can see it, not reach it."""

        engine = _engine()
        surface = engine.discover("role:team/troubleshooter")

        for group in ("sub_roles", "skills", "tools", "resources"):
            for card in surface[group]:
                with self.subTest(group=group, card=card["name"]):
                    self.assertIn("ref", card)
                    reopened = engine.get_context(card["ref"])
                    self.assertEqual(reopened["ref"], card["ref"])

    def test_discovery_never_carries_a_skill_procedure(self) -> None:
        engine = _engine()

        self.assertNotIn(PROCEDURE, json.dumps(engine.discover()))
        self.assertNotIn(PROCEDURE, json.dumps(engine.discover("role:team")))
        self.assertNotIn(
            PROCEDURE,
            json.dumps(engine.discover("role:team/troubleshooter")),
        )

    def test_opening_the_skill_is_what_delivers_the_procedure(self) -> None:
        engine = _engine()
        opened = engine.get_context("skill:team/troubleshooter#diagnose")

        self.assertIn(PROCEDURE, opened["instructions"])

    def test_an_active_role_still_only_routes_to_its_capabilities(self) -> None:
        """Opening a role must not recursively open everything beneath it."""

        engine = _engine()
        opened = engine.get_context("role:team/troubleshooter")

        self.assertIn("instructions", opened)
        self.assertNotIn(PROCEDURE, json.dumps(opened))

    def test_discover_refuses_a_capability_ref_and_says_what_to_use(self) -> None:
        engine = _engine()
        with self.assertRaises(NodeNotFoundError) as caught:
            engine.discover("skill:team/troubleshooter#diagnose")
        self.assertIn("get_context", str(caught.exception))

    def test_an_unknown_root_names_the_roots_that_do_exist(self) -> None:
        engine = _engine()
        with self.assertRaises(NodeNotFoundError) as caught:
            engine.discover("role:nonesuch")
        self.assertIn("team", str(caught.exception))

    def test_a_resource_discloses_its_descriptor_and_not_its_content(self) -> None:
        engine = _engine()
        opened = engine.get_context(
            "resource:team/troubleshooter#contexture://runbooks/crash-loop"
        )

        self.assertEqual(opened["uri"], "contexture://runbooks/crash-loop")
        self.assertNotIn("runbook body", json.dumps(opened))

    def test_a_tool_discloses_its_parameters_and_its_classification(self) -> None:
        engine = _engine()
        opened = engine.get_context("tool:team/troubleshooter#get_pod_logs")

        self.assertEqual(opened["parameters"], ["namespace", "pod"])
        self.assertTrue(opened["read_only"])


class GraphTests(unittest.TestCase):
    def test_a_forest_needs_at_least_one_root(self) -> None:
        with self.assertRaises(ModelValidationError):
            CapabilityGraph(roots=())

    def test_two_roots_may_not_share_a_name(self) -> None:
        """A root name is the first component of every ref beneath it."""

        with self.assertRaises(ModelValidationError):
            CapabilityGraph(roots=(Troubleshooter(), Troubleshooter()))

    def test_a_single_root_may_be_passed_without_a_sequence(self) -> None:
        self.assertEqual(len(build_graph(Team()).roots), 1)

    def test_a_shared_capability_is_yielded_once(self) -> None:
        """Two roles may grant the same tool object; the surface holds one."""

        shared = GetPodLogs()
        left = Role(
            name="left",
            description="Left.",
            instructions="Left.",
            tools=[shared],
        )
        right = Role(
            name="right",
            description="Right.",
            instructions="Right.",
            tools=[shared],
        )
        parent = Role(
            name="parent",
            description="Parent.",
            instructions="Parent.",
            children=[left, right],
        )

        graph = build_graph(parent)
        self.assertEqual([tool.name for _, _, tool in graph.local_tools()], ["get_pod_logs"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
