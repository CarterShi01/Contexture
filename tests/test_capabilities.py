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
    ModelValidationError,
)
from contexture.core.resources import Resource
from contexture.core.role import Role
from contexture.core.tools import Tool


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


class ResourceDeclarationTests(unittest.TestCase):
    def test_a_class_body_supplies_the_uri_and_media_type(self) -> None:
        class Runbook(Resource):
            """How to diagnose a restart loop."""

            uri = "contexture://runbooks/crash-loop"
            mime_type = "text/markdown"

            async def read(self) -> str:
                return "body"

        resource = Runbook()
        self.assertEqual(resource.uri, "contexture://runbooks/crash-loop")
        self.assertEqual(resource.mime_type, "text/markdown")

    def test_a_resource_without_a_uri_cannot_be_addressed(self) -> None:
        class Homeless(Resource):
            """A resource nobody can reach."""

            async def read(self) -> str:
                return ""

        with self.assertRaises(DeclarationError):
            Homeless()

    def test_compiling_a_resource_never_reads_it(self) -> None:
        """The descriptor/content split, checked where it would be violated."""

        reads: list[int] = []

        class Expensive(Resource):
            """A document nobody should load while browsing."""

            uri = "contexture://expensive"

            async def read(self) -> str:
                reads.append(1)
                return "EXPENSIVE-BODY"

        resource = Expensive()
        self.assertNotIn("EXPENSIVE-BODY", str(resource.compile("route")))
        self.assertNotIn("EXPENSIVE-BODY", str(resource.compile("active")))
        self.assertEqual(reads, [])

        self.assertEqual(asyncio.run(resource.read()), "EXPENSIVE-BODY")
        self.assertEqual(reads, [1])


class RoleCompositionTests(unittest.TestCase):
    def _tool(self, tool_name: str) -> Tool:
        return Tool(name=tool_name, description="A tool.")

    def test_a_role_collects_declared_tools_and_resources(self) -> None:
        class Runbook(Resource):
            """A runbook."""

            uri = "contexture://r"

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
        self.assertEqual([tool.name for tool in role.tools], ["logs"])
        self.assertEqual([r.uri for r in role.resources], ["contexture://r"])

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

    def test_an_imperative_role_rejects_duplicate_resource_uris(self) -> None:
        duplicate = [
            Resource(name="a", description="A.", uri="contexture://x"),
            Resource(name="b", description="B.", uri="contexture://x"),
        ]
        with self.assertRaises(DuplicateNameError):
            Role(
                name="r",
                description="A role.",
                instructions="Anything.",
                resources=duplicate,
            )

    def test_lookup_by_name_and_by_uri(self) -> None:
        tool = self._tool("get_logs")
        resource = Resource(name="rb", description="RB.", uri="contexture://rb")
        role = Role(
            name="r",
            description="A role.",
            instructions="Anything.",
            tools=[tool],
            resources=[resource],
        )

        self.assertIs(role.get_tool("get_logs"), tool)
        self.assertIs(role.get_resource("contexture://rb"), resource)

    def test_an_empty_uri_is_refused(self) -> None:
        with self.assertRaises(ModelValidationError):
            Resource(name="r", description="R.", uri="   ")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
