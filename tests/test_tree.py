"""Tests for the navigation model: what is disclosed, when, and what it costs.

The claim these defend is narrow and load-bearing. The role skeleton is cheap
enough to hand over whole; everything else waits until the role holding it is
opened; and nothing an agent can see is something it cannot then open.
"""

from __future__ import annotations

import json
import unittest

from contexture.core.errors import ModelValidationError, NodeNotFoundError
from contexture.core.resources import Resource
from contexture.core.role import Role
from contexture.core.skill import Skill
from contexture.core.tools import Tool
from contexture.tree import ContextTree

PROCEDURE = "Read the status, then the logs, then the events."
RUNBOOK_URI = "contexture://runbooks/crash-loop"


class GetPodLogs(Tool):
    """Return the recent container logs for a Pod."""

    name = "get_pod_logs"
    read_only = True

    async def invoke(self, namespace: str, pod: str) -> str:
        return f"{namespace}/{pod}"


class DeletePod(Tool):
    """Delete a Pod so its controller recreates it."""

    name = "delete_pod"

    async def invoke(self, namespace: str, pod: str) -> str:
        return "deleted"


class CrashLoopRunbook(Resource):
    """How to diagnose a container that keeps restarting."""

    uri = RUNBOOK_URI
    mime_type = "text/markdown"

    async def read(self) -> str:
        return "RUNBOOK-BODY"


class Diagnose(Skill):
    """Find why a Pod restarts repeatedly."""

    name = "diagnose"
    instructions = PROCEDURE


class Troubleshooter(Role):
    """Diagnose unhealthy Pods."""

    instructions = "Inspect before changing anything."

    diagnose = Diagnose
    logs = GetPodLogs
    runbook = CrashLoopRunbook


class Operator(Role):
    """Repair unhealthy Pods."""

    instructions = "Ask before destroying anything."

    remove = DeletePod


def _tree() -> ContextTree:
    team = Role(
        name="team",
        description="An engineering team.",
        instructions="Route to the right specialist.",
        children=[Troubleshooter(), Operator()],
    )
    return ContextTree.of(team, schema_of=lambda tool: {"tool": tool.name})


class SkeletonTests(unittest.TestCase):
    def test_the_skeleton_is_every_role_and_only_roles(self) -> None:
        cards = _tree().skeleton()["roles"]

        self.assertEqual(
            [card["ref"] for card in cards],
            ["team", "team/troubleshooter", "team/operator"],
        )
        self.assertTrue(all(card["kind"] == "role" for card in cards))

    def test_the_skeleton_carries_no_instructions_and_no_schemas(self) -> None:
        """This is what makes handing over the whole skeleton affordable."""

        rendered = json.dumps(_tree().skeleton())

        self.assertNotIn(PROCEDURE, rendered)
        self.assertNotIn("Inspect before changing", rendered)
        self.assertNotIn("input_schema", rendered)
        self.assertNotIn("get_pod_logs", rendered)


class CardTests(unittest.TestCase):
    def test_every_card_anywhere_carries_the_ref_that_opens_it(self) -> None:
        """A card without a ref is a dead end: it can be seen, not reached.

        Both paths are checked. Roles used to render their own members, which
        produced cards with no ref on the open path while the discover path
        looked correct.
        """

        tree = _tree()
        cards = list(tree.skeleton()["roles"])
        for card in list(cards):
            opened = tree.open(card["ref"])
            for group in ("sub_roles", "skills", "tools", "resources"):
                cards.extend(opened[group])

        self.assertGreater(len(cards), 6)
        for card in cards:
            with self.subTest(card=card["name"]):
                self.assertIn("ref", card)
                self.assertEqual(tree.open(card["ref"])["ref"], card["ref"])


class OpenTests(unittest.TestCase):
    def test_opening_a_role_reveals_its_members_with_schemas(self) -> None:
        opened = _tree().open("team/troubleshooter")

        self.assertEqual(opened["instructions"], "Inspect before changing anything.")
        self.assertEqual([s["ref"] for s in opened["skills"]],
                         ["team/troubleshooter/diagnose"])
        tool = opened["tools"][0]
        self.assertEqual(tool["ref"], "team/troubleshooter/get_pod_logs")
        self.assertTrue(tool["read_only"])
        self.assertEqual(tool["input_schema"], {"tool": "get_pod_logs"})
        resource = opened["resources"][0]
        self.assertEqual(resource["uri"], RUNBOOK_URI)
        self.assertEqual(resource["mime_type"], "text/markdown")

    def test_opening_a_role_does_not_recurse_into_sub_roles(self) -> None:
        opened = _tree().open("team")

        self.assertEqual(
            [card["ref"] for card in opened["sub_roles"]],
            ["team/troubleshooter", "team/operator"],
        )
        self.assertNotIn("get_pod_logs", json.dumps(opened))

    def test_only_opening_the_skill_delivers_the_procedure(self) -> None:
        tree = _tree()

        self.assertNotIn(PROCEDURE, json.dumps(tree.skeleton()))
        self.assertNotIn(PROCEDURE, json.dumps(tree.open("team/troubleshooter")))
        self.assertIn(
            PROCEDURE,
            tree.open("team/troubleshooter/diagnose")["instructions"],
        )

    def test_opening_a_resource_yields_a_descriptor_and_not_content(self) -> None:
        opened = _tree().open("team/troubleshooter/crash-loop-runbook")

        self.assertEqual(opened["uri"], RUNBOOK_URI)
        self.assertNotIn("RUNBOOK-BODY", json.dumps(opened))


class ResolutionTests(unittest.TestCase):
    def test_an_unknown_member_names_what_the_role_does_hold(self) -> None:
        with self.assertRaises(NodeNotFoundError) as caught:
            _tree().find("team/troubleshooter/banana")

        message = str(caught.exception)
        self.assertIn("banana", message)
        self.assertIn("get_pod_logs", message)
        self.assertIn("diagnose", message)

    def test_an_unknown_root_names_the_roots_that_exist(self) -> None:
        with self.assertRaises(NodeNotFoundError) as caught:
            _tree().find("nobody")

        self.assertIn("team", str(caught.exception))

    def test_a_reference_may_not_continue_past_a_leaf(self) -> None:
        with self.assertRaises(NodeNotFoundError) as caught:
            _tree().find("team/troubleshooter/diagnose/deeper")

        self.assertIn("skill", str(caught.exception))

    def test_a_resource_resolves_by_reference_or_by_its_own_uri(self) -> None:
        """A procedure names a document the way the document names itself."""

        tree = _tree()

        self.assertIs(
            tree.resource(RUNBOOK_URI),
            tree.resource("team/troubleshooter/crash-loop-runbook"),
        )

    def test_the_typed_accessors_say_what_the_ref_actually_names(self) -> None:
        tree = _tree()

        with self.assertRaises(NodeNotFoundError) as caught:
            tree.tool("team/troubleshooter/diagnose")
        self.assertIn("skill", str(caught.exception))

        with self.assertRaises(NodeNotFoundError) as caught:
            tree.resource("team/troubleshooter/get_pod_logs")
        self.assertIn("tool", str(caught.exception))

    def test_resolution_does_not_depend_on_earlier_calls(self) -> None:
        """The surface is stateless, so traversal has to be too."""

        tree = _tree()
        first = tree.open("team/troubleshooter")
        tree.open("team/operator")

        self.assertEqual(tree.open("team/troubleshooter"), first)


class ConstructionTests(unittest.TestCase):
    def test_one_root_or_many_are_both_accepted(self) -> None:
        single = ContextTree.of(Troubleshooter())
        several = ContextTree.of([Troubleshooter(), Operator()])

        self.assertEqual(len(single.roots), 1)
        self.assertEqual(len(several.roots), 2)

    def test_an_empty_forest_is_rejected(self) -> None:
        with self.assertRaises(ModelValidationError):
            ContextTree.of([])

    def test_two_roots_may_not_share_a_name(self) -> None:
        with self.assertRaises(ModelValidationError):
            ContextTree.of([Troubleshooter(), Troubleshooter()])

    def test_a_cycle_is_rejected_when_the_forest_is_built(self) -> None:
        """A cycle is only visible once the whole forest is in hand."""

        parent = Role(name="parent", description="A role.", instructions="Go.")
        child = Role(
            name="child",
            description="A role.",
            instructions="Go.",
            children=[parent],
        )
        parent.children.append(child)

        with self.assertRaises(ModelValidationError):
            ContextTree.of(parent)


if __name__ == "__main__":
    unittest.main()
