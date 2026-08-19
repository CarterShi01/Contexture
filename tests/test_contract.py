"""Tests for everything a connected agent reads.

These run without the MCP SDK installed, and that is the point: what the agent
is told is decided a layer above the object model and a layer below the wire,
and it should be readable, assertable, and reviewable on its own.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from contexture.core.errors import LookupFailure, NodeNotFoundError
from contexture.server import contract

SOURCE_ROOT = Path(__file__).resolve().parent.parent / "src"


class SurfaceVocabularyTests(unittest.TestCase):
    def test_the_gateway_is_five_entry_points_stated_once(self) -> None:
        self.assertEqual(len(contract.GATEWAY), 5)
        self.assertEqual(
            contract.GATEWAY_TOOLS,
            (
                "contexture_discover",
                "contexture_open",
                "contexture_read",
                "contexture_invoke_read_only",
                "contexture_invoke",
            ),
        )

    def test_exactly_one_entry_point_is_not_read_only(self) -> None:
        """The write door is the whole reason invoke is split in two."""

        writing = [entry.name for entry in contract.GATEWAY if not entry.read_only]
        self.assertEqual(writing, ["contexture_invoke"])

    def test_every_entry_point_describes_itself(self) -> None:
        for entry in contract.GATEWAY:
            with self.subTest(tool=entry.name):
                self.assertGreater(len(entry.description), 60)

    def test_only_the_call_that_delivers_schemas_talks_about_them(self) -> None:
        """Five descriptions are one document, and it has to agree with itself.

        `contexture_discover` said cards never carry tool schemas and that
        opening is what delivers them. Both halves misled: the cards *it*
        returns are role cards, which have no schema to carry, while the tool
        cards `contexture_open` returns have carried the schema since the card
        and the tool's own ref were made to agree. An agent that believed it
        spent a call per tool to be handed back the card it already had.
        """

        described = {entry.name: entry.description for entry in contract.GATEWAY}

        self.assertIn("schema", described[contract.OPEN_TOOL])
        self.assertNotIn("schema", described[contract.DISCOVER_TOOL])


class PreambleTests(unittest.TestCase):
    def test_the_opening_fits_the_budget_codex_reads(self) -> None:
        """Codex decides whether to use the server from the first 512 chars."""

        self.assertLessEqual(len(contract.PREAMBLE), 512)

    def test_the_opening_names_the_tools_it_tells_the_agent_to_call(self) -> None:
        for name in (
            contract.OPEN_TOOL,
            contract.INVOKE_TOOL,
            contract.INVOKE_READ_ONLY_TOOL,
        ):
            with self.subTest(tool=name):
                self.assertIn(name, contract.PREAMBLE)


class UnresolvedTests(unittest.TestCase):
    def _failure(self, reason: LookupFailure) -> NodeNotFoundError:
        return NodeNotFoundError(
            reason=reason,
            ref="team/troubleshooter/banana",
            segment="banana",
            scope="troubleshooter",
            kind="skill",
            wanted="tool",
            known=("diagnose", "get_pod_logs"),
        )

    def test_every_lookup_failure_has_a_rendering(self) -> None:
        """A reason with no branch is a failure an agent is told nothing about."""

        for reason in LookupFailure:
            with self.subTest(reason=reason.value):
                rendered = contract.unresolved(self._failure(reason))
                self.assertNotIn("could not be resolved", rendered)
                self.assertGreater(len(rendered), 40)

    def test_every_rendering_names_the_call_that_recovers_from_it(self) -> None:
        """The half a wrong ref most needs is what to do next.

        This is the sentence the tree cannot write: it does not know these
        names, and must not.
        """

        for reason in LookupFailure:
            with self.subTest(reason=reason.value):
                rendered = contract.unresolved(self._failure(reason))
                self.assertTrue(
                    any(name in rendered for name in contract.GATEWAY_TOOLS),
                    f"{reason.value} leaves the agent with no next call",
                )

    def test_a_missing_member_says_what_the_role_does_hold(self) -> None:
        rendered = contract.unresolved(
            self._failure(LookupFailure.NO_SUCH_MEMBER)
        )

        self.assertIn("banana", rendered)
        self.assertIn("diagnose", rendered)
        self.assertIn("get_pod_logs", rendered)

    def test_an_empty_role_is_reported_as_empty_rather_than_as_a_blank_list(
        self,
    ) -> None:
        rendered = contract.unresolved(
            NodeNotFoundError(
                reason=LookupFailure.NO_SUCH_MEMBER,
                ref="team/empty/x",
                segment="x",
                scope="empty",
            )
        )

        self.assertIn("holds nothing", rendered)


class WrongDoorTests(unittest.TestCase):
    def test_each_door_names_the_other_one(self) -> None:
        self.assertIn(
            contract.INVOKE_READ_ONLY_TOOL,
            contract.wrong_door("a/b", is_read_only=True),
        )
        self.assertIn(
            contract.INVOKE_TOOL,
            contract.wrong_door("a/b", is_read_only=False),
        )


class IndependenceTests(unittest.TestCase):
    def test_deciding_what_the_agent_reads_needs_no_wire(self) -> None:
        """Importing the contract must not drag in the SDK.

        The three modules of this layer change at three different rates. This
        one is the slowest, and it stays testable on its own.

        Asked in a subprocess, because `sys.modules` belongs to the process and
        not to this test: run after any module that imports the SDK — which is
        most of this suite — an in-process check reports the whole suite's
        imports and fails on work this module did not do. It passed alone and
        failed in the run, which is the reading that matters.
        """

        script = (
            "import sys; sys.path.insert(0, %r);"
            "import contexture.server.contract;"
            "print(','.join(sorted(m for m in sys.modules "
            "if m == 'mcp' or m.startswith('mcp.'))))" % str(SOURCE_ROOT)
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=True,
        )

        self.assertEqual(result.stdout.strip(), "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
