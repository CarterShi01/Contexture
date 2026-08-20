"""Tests for the tools and resources an application implements.

A tool's schema comes from a Python signature rather than a hand-written dict,
and a resource's content is produced only when somebody asks for it.
"""

from __future__ import annotations

import asyncio
import unittest

from contexture.core.errors import (
    DeclarationError,
    DuplicateNameError,
    LookupFailure,
    ModelValidationError,
    NodeNotFoundError,
)
from contexture.core.model.role import Role
from contexture.core.model.skill import Skill
from contexture.core.model.tool import Tool


class ToolDeclarationTests(unittest.TestCase):
    def test_a_class_body_supplies_the_name_and_the_routing_card(self) -> None:
        class GetPodLogs(Tool):
            """Return recent container logs for one Pod."""

            async def invoke(self, namespace: str) -> str:
                return namespace

        tool = GetPodLogs()
        self.assertEqual(tool.name, "get-pod-logs")
        self.assertEqual(
            tool.description, "Return recent container logs for one Pod."
        )

    def test_an_explicit_name_wins_over_the_derived_one(self) -> None:
        """MCP tool names are flat and global, so a project must be able to pick."""

        class GetPodLogs(Tool):
            """Return recent container logs for one Pod."""

            name = "get_pod_logs"

            async def invoke(self) -> str:
                return ""

        self.assertEqual(GetPodLogs().name, "get_pod_logs")

    def test_a_tool_without_a_description_is_refused_at_class_creation(self) -> None:
        with self.assertRaises(DeclarationError):

            class Undocumented(Tool):
                async def invoke(self) -> str:
                    return ""

    def test_read_only_defaults_to_false(self) -> None:
        """The safe default: an unclassified tool is treated as one that writes."""

        class DeletePod(Tool):
            """Delete a Pod."""

            async def invoke(self) -> str:
                return ""

        self.assertFalse(DeletePod().read_only)

    def test_parameters_come_from_the_signature_and_skip_self(self) -> None:
        class Complex(Tool):
            """A tool with several parameters."""

            async def invoke(
                self,
                namespace: str,
                pod: str,
                previous: bool = False,
            ) -> str:
                return ""

        self.assertEqual(
            Complex().parameters(), ("namespace", "pod", "previous")
        )

    def test_the_base_tool_reports_that_it_was_never_implemented(self) -> None:
        class Forgotten(Tool):
            """Somebody declared this and stopped."""

        with self.assertRaises(NotImplementedError):
            asyncio.run(Forgotten().invoke())

    def test_an_imperatively_built_tool_is_still_an_ordinary_tool(self) -> None:
        tool = Tool(name="manual", description="Built at runtime.")
        self.assertEqual(tool.compile("route")["kind"], "tool")


class RoleCompositionTests(unittest.TestCase):
    def _tool(self, tool_name: str) -> Tool:
        return Tool(name=tool_name, description="A tool.")

    def test_a_role_collects_declared_tools(self) -> None:
        class Runbook(Tool):
            """A runbook."""

            read_only = True

            async def invoke(self) -> str:
                return "BODY"

        class Logs(Tool):
            """Read logs."""

            async def invoke(self) -> str:
                return ""

        class Responder(Role):
            """Diagnose workloads."""

            instructions = "Look before touching."

            logs = Logs
            runbook = Runbook

        role = Responder()
        self.assertEqual(
            sorted(tool.name for tool in role.tools), ["logs", "runbook"]
        )

    def test_two_tools_with_one_name_are_refused_at_class_creation(self) -> None:
        class First(Tool):
            """First."""

            name = "same"

        class Second(Tool):
            """Second."""

            name = "same"

        with self.assertRaises(DeclarationError):

            class Clashing(Role):
                """A role that grants two tools with one name."""

                instructions = "Anything."

                a = First
                b = Second

    def test_an_imperative_role_rejects_duplicate_tool_names(self) -> None:
        with self.assertRaises(DuplicateNameError):
            Role(
                name="r",
                description="A role.",
                instructions="Anything.",
                tools=[self._tool("same"), self._tool("same")],
            )

    def test_a_role_finds_its_own_members_by_name(self) -> None:
        """One cross-kind lookup, because the uniqueness invariant is cross-kind."""

        tool = self._tool("get_logs")
        skill = Skill(name="rb", description="RB.", instructions="Read it.")
        role = Role(
            name="r",
            description="A role.",
            instructions="Anything.",
            tools=[tool],
            skills=[skill],
        )

        self.assertIs(role.member("get_logs"), tool)
        self.assertIs(role.member("rb"), skill)
        self.assertEqual([node.name for node in role.members()], ["rb", "get_logs"])

    def test_a_missing_member_reports_what_the_role_holds(self) -> None:
        role = Role(
            name="r",
            description="A role.",
            instructions="Anything.",
            tools=[self._tool("get_logs")],
        )

        with self.assertRaises(NodeNotFoundError) as caught:
            role.member("nope")

        failure = caught.exception
        self.assertIs(failure.reason, LookupFailure.NO_SUCH_MEMBER)
        self.assertEqual(failure.scope, "r")
        self.assertEqual(failure.known, ("get_logs",))
        self.assertIsNone(failure.ref)  # only the tree knows the whole path


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class MemberNameTests(unittest.TestCase):
    """A member's name is the last segment of the reference that opens it.

    So the names inside one role have to be unique across kinds, not merely
    within them. These tests are what stop that constraint from decaying back
    into four independent checks.
    """

    @staticmethod
    def _skill() -> Skill:
        return Skill(name="diagnose", description="A procedure.", instructions="Go.")

    @staticmethod
    def _tool() -> Tool:
        return Tool(name="diagnose", description="A capability.")

    def test_a_skill_and_a_tool_may_not_share_a_name(self) -> None:
        with self.assertRaises(DuplicateNameError) as caught:
            Role(
                name="responder",
                description="A role.",
                instructions="Go.",
                skills=[self._skill()],
                tools=[self._tool()],
            )

        message = str(caught.exception)
        self.assertIn("diagnose", message)
        self.assertIn("skill", message)
        self.assertIn("tool", message)

    def test_a_sub_role_and_a_tool_may_not_share_a_name(self) -> None:
        child = Role(name="runbook", description="A role.", instructions="Go.")
        tool = Tool(name="runbook", description="A document.")

        with self.assertRaises(DuplicateNameError):
            Role(
                name="responder",
                description="A role.",
                instructions="Go.",
                children=[child],
                tools=[tool],
            )

    def test_distinct_names_across_kinds_are_accepted(self) -> None:
        role = Role(
            name="responder",
            description="A role.",
            instructions="Go.",
            skills=[self._skill()],
            tools=[Tool(name="get_pod_logs", description="A capability.")],
        )

        self.assertEqual([skill.name for skill in role.skills], ["diagnose"])
        self.assertEqual([tool.name for tool in role.tools], ["get_pod_logs"])


class RoleSelfDescriptionTests(unittest.TestCase):
    def test_an_opened_role_describes_itself_and_not_its_members(self) -> None:
        """Listing members here would list them without references.

        `core` cannot know what a reference looks like, so a member listed at
        this level could be seen and never opened. `contexture.tree` lists them
        instead, where the reference exists.
        """

        role = Role(
            name="responder",
            description="A role.",
            instructions="Work from evidence.",
            skills=[
                Skill(name="diagnose", description="A procedure.", instructions="Go.")
            ],
            tools=[Tool(name="get_pod_logs", description="A capability.")],
        )

        compiled = role.compile("active")

        self.assertEqual(compiled["instructions"], "Work from evidence.")
        self.assertEqual(
            set(compiled),
            {"kind", "name", "description", "instructions"},
        )
