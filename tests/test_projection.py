"""Tests for the gateway surface.

The surface is five tools whatever the declaration holds, business
capabilities never appear on it, and the read-only classification survives as
which entry point was used rather than as an argument a model could fill in.
"""

from __future__ import annotations

import asyncio
import json
import unittest

from mcp.server.mcpserver.exceptions import ToolError

from contexture.core.resources import Resource
from contexture.core.role import Role
from contexture.core.skill import Skill
from contexture.core.tools import Tool
from contexture.server import (
    DISCOVER_TOOL,
    Launch,
    GATEWAY_TOOLS,
    INVOKE_READ_ONLY_TOOL,
    INVOKE_TOOL,
    OPEN_TOOL,
    READ_TOOL,
    ContextureApp,
    claude_code_config,
    cli_commands,
    codex_config,
)

PROCEDURE = "Read the status, then the logs."


class GetPodLogs(Tool):
    """Return the recent container logs for a Pod."""

    name = "get_pod_logs"
    read_only = True

    async def invoke(self, namespace: str, pod: str, previous: bool = False) -> str:
        return f"{namespace}/{pod} previous={previous}"


class DeletePod(Tool):
    """Delete a Pod so its controller recreates it."""

    name = "delete_pod"

    async def invoke(self, namespace: str, pod: str) -> str:
        return f"deleted {namespace}/{pod}"


class Runbook(Resource):
    """How to diagnose a container that keeps restarting."""

    uri = "contexture://runbooks/crash-loop"
    mime_type = "text/markdown"

    async def read(self) -> str:
        return "RUNBOOK-BODY"


class Diagnose(Skill):
    """Find why a Pod restarts repeatedly."""

    name = "diagnose"
    instructions = PROCEDURE


class Responder(Role):
    """Diagnose and repair unhealthy Pods."""

    instructions = "Inspect before changing anything."

    diagnose = Diagnose
    logs = GetPodLogs
    remove = DeletePod
    runbook = Runbook


def _server():
    return ContextureApp(roots=Responder(), name="test").build_server()


def _call(server, name, arguments=None):
    return asyncio.run(server.call_tool(name, arguments or {}))


def _text(result):
    return result.content[0].text


class SurfaceTests(unittest.TestCase):
    def test_the_surface_is_the_five_gateway_tools_and_nothing_else(self) -> None:
        server = _server()

        listed = tuple(tool.name for tool in asyncio.run(server.list_tools()))
        self.assertEqual(listed, GATEWAY_TOOLS)

    def test_no_business_capability_reaches_the_surface(self) -> None:
        """A registered capability is one every session pays for, forever."""

        server = _server()

        rendered = json.dumps(
            [tool.model_dump(mode="json") for tool in asyncio.run(server.list_tools())]
        )
        self.assertNotIn("get_pod_logs", rendered)
        self.assertNotIn("delete_pod", rendered)
        self.assertNotIn(PROCEDURE, rendered)

        resources = asyncio.run(server.list_resources())
        self.assertEqual(resources, [])

    def test_only_the_writing_door_is_free_of_the_read_only_hint(self) -> None:
        server = _server()
        hints = {
            tool.name: tool.annotations and tool.annotations.read_only_hint
            for tool in asyncio.run(server.list_tools())
        }

        self.assertEqual(hints[INVOKE_TOOL], False)
        for name in (DISCOVER_TOOL, OPEN_TOOL, READ_TOOL, INVOKE_READ_ONLY_TOOL):
            with self.subTest(tool=name):
                self.assertTrue(hints[name])

    def test_read_only_is_never_an_argument(self) -> None:
        """A model that could pass its own approval flag would be approving
        its own writes."""

        server = _server()
        for tool in asyncio.run(server.list_tools()):
            with self.subTest(tool=tool.name):
                self.assertNotIn(
                    "read_only", tool.input_schema.get("properties", {})
                )

    def test_the_instructions_carry_the_role_roster(self) -> None:
        """A gateway whose five tool names all begin `contexture_` gives a host
        nothing to go on until the roster tells it what this server is for."""

        server = _server()

        self.assertIn("responder", server.instructions)
        self.assertIn("Diagnose and repair unhealthy Pods.", server.instructions)
        self.assertNotIn(PROCEDURE, server.instructions)


class NavigationTests(unittest.TestCase):
    def test_discover_returns_the_skeleton(self) -> None:
        server = _server()

        payload = json.loads(_text(_call(server, DISCOVER_TOOL)))
        self.assertEqual([card["ref"] for card in payload["roles"]], ["responder"])

    def test_opening_a_role_delivers_the_schemas_the_surface_no_longer_has(
        self,
    ) -> None:
        server = _server()

        opened = json.loads(_text(_call(server, OPEN_TOOL, {"ref": "responder"})))
        schemas = {tool["name"]: tool["input_schema"] for tool in opened["tools"]}
        self.assertEqual(
            sorted(schemas["get_pod_logs"]["properties"]),
            ["namespace", "pod", "previous"],
        )
        self.assertEqual(schemas["get_pod_logs"]["required"], ["namespace", "pod"])

    def test_a_wrong_ref_is_a_sentence_and_not_a_traceback(self) -> None:
        server = _server()

        with self.assertRaises(ToolError) as caught:
            _call(server, OPEN_TOOL, {"ref": "responder/banana"})

        message = str(caught.exception)
        self.assertIn("banana", message)
        self.assertIn("get_pod_logs", message)


class InvocationTests(unittest.TestCase):
    def test_a_read_only_tool_runs_through_the_read_only_door(self) -> None:
        server = _server()

        result = _call(
            server,
            INVOKE_READ_ONLY_TOOL,
            {"ref": "responder/get_pod_logs",
             "arguments": {"namespace": "prod", "pod": "api"}},
        )
        self.assertIn("prod/api", _text(result))

    def test_a_writing_tool_runs_through_the_writing_door(self) -> None:
        server = _server()

        result = _call(
            server,
            INVOKE_TOOL,
            {"ref": "responder/delete_pod",
             "arguments": {"namespace": "prod", "pod": "api"}},
        )
        self.assertIn("deleted prod/api", _text(result))

    def test_a_write_sent_through_the_read_only_door_is_refused(self) -> None:
        """The host decided whether to involve a human from the door's hint.

        Honouring a mismatch would run a write under a read-only approval.
        """

        server = _server()

        with self.assertRaises(ToolError) as caught:
            _call(
                server,
                INVOKE_READ_ONLY_TOOL,
                {"ref": "responder/delete_pod",
                 "arguments": {"namespace": "prod", "pod": "api"}},
            )

        message = str(caught.exception)
        self.assertIn("not read-only", message)
        self.assertIn(INVOKE_TOOL, message)

    def test_a_read_sent_through_the_writing_door_is_refused(self) -> None:
        server = _server()

        with self.assertRaises(ToolError) as caught:
            _call(
                server,
                INVOKE_TOOL,
                {"ref": "responder/get_pod_logs",
                 "arguments": {"namespace": "prod", "pod": "api"}},
            )

        self.assertIn(INVOKE_READ_ONLY_TOOL, str(caught.exception))

    def test_arguments_are_validated_against_the_derived_schema(self) -> None:
        """Validation left the wire with the tool; it did not stop happening."""

        server = _server()

        with self.assertRaises(ToolError) as caught:
            _call(
                server,
                INVOKE_READ_ONLY_TOOL,
                {"ref": "responder/get_pod_logs", "arguments": {"namespace": "prod"}},
            )

        self.assertIn("pod", str(caught.exception))

    def test_a_ref_that_names_a_skill_is_refused_by_invoke(self) -> None:
        server = _server()

        with self.assertRaises(ToolError) as caught:
            _call(server, INVOKE_READ_ONLY_TOOL, {"ref": "responder/diagnose"})

        self.assertIn("skill", str(caught.exception))


class ResourceTests(unittest.TestCase):
    def test_content_arrives_only_when_it_is_read(self) -> None:
        server = _server()

        opened = json.loads(
            _text(_call(server, OPEN_TOOL, {"ref": "responder/runbook"}))
        )
        self.assertNotIn("RUNBOOK-BODY", json.dumps(opened))
        self.assertIn(
            "RUNBOOK-BODY",
            _text(_call(server, READ_TOOL, {"ref": "responder/runbook"})),
        )

    def test_a_resource_reads_by_its_own_uri_as_well_as_by_ref(self) -> None:
        server = _server()

        result = _call(
            server, READ_TOOL, {"ref": "contexture://runbooks/crash-loop"}
        )
        self.assertIn("RUNBOOK-BODY", _text(result))


class RegistrationTests(unittest.TestCase):
    """Host config now points at the server instead of replacing it."""

    LAUNCH = Launch(
        name="contexture-demo",
        command="uv",
        args=("run", "contexture", "serve"),
    )

    def test_claude_code_config_is_a_launch_command_not_a_context_file(self) -> None:
        import json

        config = json.loads(claude_code_config(self.LAUNCH))
        entry = config["mcpServers"]["contexture-demo"]

        self.assertEqual(entry["type"], "stdio")
        self.assertEqual(entry["command"], "uv")
        self.assertEqual(entry["args"], ["run", "contexture", "serve"])

    def test_codex_config_stanza_quotes_its_command(self) -> None:
        stanza = codex_config(self.LAUNCH)

        self.assertIn("[mcp_servers.contexture-demo]", stanza)
        self.assertIn('command = "uv"', stanza)
        self.assertIn('args = ["run", "contexture", "serve"]', stanza)

    def test_both_hosts_are_given_the_same_launch_command(self) -> None:
        """The claim under test: one server, two hosts, one command."""

        commands = cli_commands(self.LAUNCH)
        suffix = "-- uv run contexture serve"

        self.assertTrue(commands["claude-code"].endswith(suffix))
        self.assertTrue(commands["codex"].endswith(suffix))
        # Claude Code defaults to local scope; a shared file needs it named.
        self.assertIn("--scope project", commands["claude-code"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
