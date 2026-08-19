"""Tests for the translation from a declared graph onto an MCP surface.

The end-to-end suite proves the server works when launched. These tests are the
cheap, granular half: they pin the shape of the projection itself, so a
regression names the rule it broke instead of failing a whole session.
"""

from __future__ import annotations

import asyncio
import unittest

from contexture.core.errors import DuplicateNameError
from contexture.core.resources import Resource
from contexture.core.role import Role
from contexture.core.skill import Skill
from contexture.core.tools import Tool
from contexture.server import DISCOVER_TOOL, GET_CONTEXT_TOOL, ContextureApp
from contexture.server import instructions as instructions_module
from contexture.server.registration import (
    Launch,
    claude_code_config,
    cli_commands,
    codex_config,
)


class GetPodLogs(Tool):
    """Return recent container logs for one Pod."""

    name = "get_pod_logs"
    read_only = True

    async def invoke(self, namespace: str, pod: str, previous: bool = False) -> str:
        return f"logs {namespace}/{pod} previous={previous}"


class DeletePod(Tool):
    """Delete a Pod so its controller recreates it."""

    name = "delete_pod"

    async def invoke(self, namespace: str, pod: str) -> str:
        return f"deleted {namespace}/{pod}"


class Runbook(Resource):
    """How to diagnose a restart loop."""

    uri = "contexture://runbooks/crash-loop"
    mime_type = "text/markdown"

    async def read(self) -> str:
        return "# Runbook body"


class Diagnose(Skill):
    """Diagnose a Pod that keeps restarting."""

    instructions = "1. status 2. logs 3. events"


class Responder(Role):
    """Diagnose and remediate unhealthy Kubernetes workloads."""

    instructions = "Inspect before changing anything."

    diagnose = Diagnose
    logs = GetPodLogs
    remove = DeletePod
    runbook = Runbook


def _server():
    return ContextureApp(roots=Responder(), name="test").build_server()


def _tools_by_name(server):
    return {tool.name: tool for tool in asyncio.run(server.list_tools())}


class SurfaceTests(unittest.TestCase):
    def test_framework_and_business_tools_share_one_flat_surface(self) -> None:
        server, projection = _server()

        self.assertEqual(
            projection.framework_tools, (DISCOVER_TOOL, GET_CONTEXT_TOOL)
        )
        self.assertEqual(projection.business_tools, ("get_pod_logs", "delete_pod"))
        self.assertEqual(
            set(_tools_by_name(server)),
            {DISCOVER_TOOL, GET_CONTEXT_TOOL, "get_pod_logs", "delete_pod"},
        )

    def test_the_schema_is_derived_from_the_invoke_signature(self) -> None:
        """The framework claim: a business project writes no JSON Schema."""

        schema = _tools_by_name(_server()[0])["get_pod_logs"].input_schema

        self.assertEqual(
            set(schema["properties"]), {"namespace", "pod", "previous"}
        )
        self.assertEqual(sorted(schema["required"]), ["namespace", "pod"])
        self.assertEqual(schema["properties"]["previous"]["type"], "boolean")

    def test_read_only_is_projected_as_a_hint_never_as_a_parameter(self) -> None:
        """Host classification must not be something the model can supply."""

        tools = _tools_by_name(_server()[0])

        self.assertTrue(tools["get_pod_logs"].annotations.read_only_hint)
        self.assertFalse(tools["delete_pod"].annotations.read_only_hint)
        for name, tool in tools.items():
            with self.subTest(tool=name):
                self.assertNotIn(
                    "read_only", tool.input_schema.get("properties", {})
                )
                self.assertNotIn(
                    "approved", tool.input_schema.get("properties", {})
                )

    def test_resources_are_registered_with_their_media_type(self) -> None:
        server, projection = _server()
        resources = asyncio.run(server.list_resources())

        self.assertEqual(projection.resources, ("contexture://runbooks/crash-loop",))
        self.assertEqual(
            [(str(r.uri), r.mime_type) for r in resources],
            [("contexture://runbooks/crash-loop", "text/markdown")],
        )

    def test_two_tools_that_claim_one_name_are_refused(self) -> None:
        """MCP names are global, so a collision must fail loudly at build time."""

        class Left(Tool):
            """Left."""

            name = "clash"

            async def invoke(self) -> str:
                return ""

        class Right(Tool):
            """Right."""

            name = "clash"

            async def invoke(self) -> str:
                return ""

        parent = Role(
            name="parent",
            description="Parent.",
            instructions="Parent.",
            children=[
                Role(
                    name="a",
                    description="A.",
                    instructions="A.",
                    tools=[Left()],
                ),
                Role(
                    name="b",
                    description="B.",
                    instructions="B.",
                    tools=[Right()],
                ),
            ],
        )

        with self.assertRaises(DuplicateNameError) as caught:
            ContextureApp(roots=parent).build_server()
        self.assertIn("clash", str(caught.exception))


class ExecutionTests(unittest.TestCase):
    def test_a_business_tool_runs_through_the_surface(self) -> None:
        server, _ = _server()
        result = asyncio.run(
            server.call_tool(
                "get_pod_logs", {"namespace": "prod", "pod": "api"}
            )
        )

        self.assertIn("logs prod/api", result.content[0].text)

    def test_a_resource_is_read_only_when_asked_for(self) -> None:
        server, _ = _server()
        contents = asyncio.run(
            server.read_resource("contexture://runbooks/crash-loop")
        )

        self.assertIn("Runbook body", list(contents)[0].content)

    def test_a_bad_ref_returns_a_message_the_agent_can_act_on(self) -> None:
        """A wrong ref is recoverable, so it must read as a sentence."""

        from mcp.server.mcpserver.exceptions import ToolError

        server, _ = _server()
        with self.assertRaises(ToolError) as caught:
            asyncio.run(server.call_tool(GET_CONTEXT_TOOL, {"ref": "banana"}))

        message = str(caught.exception)
        self.assertIn("must start with a kind", message)
        # KeyError reprs its argument; a leaked repr would wrap this in quotes.
        self.assertNotIn("\"Reference", message)


class InstructionsTests(unittest.TestCase):
    def test_the_bootstrap_fits_both_hosts_limits(self) -> None:
        server, _ = _server()
        text = server.instructions or ""

        # Codex reads the first 512 characters while deciding how to use the
        # server; Claude Code truncates the whole field at 2KB.
        self.assertIn(DISCOVER_TOOL, text[:512])
        self.assertLess(len(text.encode("utf-8")), 2048)

    def test_the_bootstrap_names_every_root(self) -> None:
        text = instructions_module.build(
            (
                Role(name="alpha", description="Alpha.", instructions="A."),
                Role(name="beta", description="Beta.", instructions="B."),
            )
        )

        self.assertIn("alpha: Alpha.", text)
        self.assertIn("beta: Beta.", text)

    def test_the_bootstrap_carries_no_skill_procedure(self) -> None:
        server, _ = _server()
        self.assertNotIn("1. status 2. logs", server.instructions or "")


class RegistrationTests(unittest.TestCase):
    """Host config now points at the server instead of replacing it."""

    LAUNCH = Launch(
        name="contexture-demo",
        command="uv",
        args=("run", "contexture-incident-demo"),
    )

    def test_claude_code_config_is_a_launch_command_not_a_context_file(self) -> None:
        import json

        config = json.loads(claude_code_config(self.LAUNCH))
        entry = config["mcpServers"]["contexture-demo"]

        self.assertEqual(entry["type"], "stdio")
        self.assertEqual(entry["command"], "uv")
        self.assertEqual(entry["args"], ["run", "contexture-incident-demo"])

    def test_codex_config_stanza_quotes_its_command(self) -> None:
        stanza = codex_config(self.LAUNCH)

        self.assertIn("[mcp_servers.contexture-demo]", stanza)
        self.assertIn('command = "uv"', stanza)
        self.assertIn('args = ["run", "contexture-incident-demo"]', stanza)

    def test_both_hosts_are_given_the_same_launch_command(self) -> None:
        """The claim under test: one server, two hosts, one command."""

        commands = cli_commands(self.LAUNCH)
        suffix = "-- uv run contexture-incident-demo"

        self.assertTrue(commands["claude-code"].endswith(suffix))
        self.assertTrue(commands["codex"].endswith(suffix))
        # Claude Code defaults to local scope; a shared file needs it named.
        self.assertIn("--scope project", commands["claude-code"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
