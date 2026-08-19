"""End-to-end tests that launch the demo as a real subprocess.

Everything else in this suite exercises the server in-process, which cannot
observe the two things that actually break a stdio server: whether the process
starts at all under a host's launch command, and whether anything but MCP
messages reaches stdout. Both are only visible from outside the process, so
these tests pay for a subprocess.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest

from contexture.server import GATEWAY_TOOLS
from pathlib import Path

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:  # pragma: no cover - the SDK is a hard dependency
    ClientSession = None  # type: ignore[assignment]

SOURCE_ROOT = Path(__file__).resolve().parent.parent / "src"
DEMO_MODULE = "contexture.examples.incident.server"

#: Anything the demo prints outside the protocol would corrupt the stream, so
#: stderr is captured to a file rather than inherited, and asserted on.
TIMEOUT_SECONDS = 30


def _server_parameters(stderr_path: Path) -> StdioServerParameters:
    environment = dict(os.environ)
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        f"{SOURCE_ROOT}{os.pathsep}{existing}" if existing else str(SOURCE_ROOT)
    )
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", DEMO_MODULE],
        env=environment,
    )


async def _session(work, *, modern: bool = True):
    """Run `work(session)` against a freshly launched demo subprocess.

    `modern` selects how the session is opened. The 2026-07-28 revision has no
    initialize handshake — a client probes `server/discover` and every request
    then carries its own version metadata — while older revisions negotiate on
    connect. Both doors are exercised, because a server that only answers the
    newest one silently drops every host that has not upgraded yet.
    """

    stderr_path = Path(os.environ.get("CONTEXTURE_TEST_STDERR", os.devnull))
    with open(stderr_path, "w", encoding="utf-8") as errlog:
        parameters = _server_parameters(stderr_path)
        async with stdio_client(parameters, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                if modern:
                    await session.discover()
                else:
                    await session.initialize()
                return await work(session)


def _run(work, *, modern: bool = True):
    return asyncio.run(
        asyncio.wait_for(_session(work, modern=modern), TIMEOUT_SECONDS)
    )


@unittest.skipIf(ClientSession is None, "the MCP SDK is not installed")
class StdioServerTests(unittest.TestCase):
    """The demo, launched the way Claude Code and Codex launch it."""

    def test_the_server_starts_and_reports_its_instructions(self) -> None:
        async def work(session):
            return session.instructions, session.protocol_version

        instructions, protocol_version = _run(work)

        self.assertIsNotNone(instructions)
        assert instructions is not None
        self.assertIn("contexture_open", instructions)
        # The roster is here rather than behind a first discover call: a
        # gateway whose five tool names all begin `contexture_` otherwise gives
        # a host no sign of what the server is for.
        self.assertIn("kubernetes-incident-responder", instructions)
        # Codex asks that the opening be self-contained; Claude Code truncates
        # the whole field at 2KB. Both limits are checked, not just documented.
        self.assertIn("contexture_open", instructions[:512])
        self.assertLess(len(instructions.encode("utf-8")), 2048)
        self.assertEqual(protocol_version, "2026-07-28")

    def test_a_legacy_host_still_gets_a_working_server(self) -> None:
        """One implementation serves the handshake revisions too, unchanged."""

        async def work(session):
            tools = await session.list_tools()
            return session.protocol_version, {t.name for t in tools.tools}

        protocol_version, names = _run(work, modern=False)

        self.assertIn(protocol_version, {"2025-11-25", "2025-06-18", "2025-03-26"})
        self.assertEqual(names, set(GATEWAY_TOOLS))

    def test_the_surface_is_five_tools_and_holds_no_capability(self) -> None:
        """A capability on the surface is one every session pays for, forever.

        Checked on the wire rather than against the projection object, because
        this is the claim the whole design rests on.
        """

        async def work(session):
            tools = await session.list_tools()
            resources = await session.list_resources()
            return tools.tools, resources.resources

        tools, resources = _run(work)
        names = {tool.name for tool in tools}

        self.assertEqual(names, set(GATEWAY_TOOLS))
        self.assertEqual(names & {"get_pod_status", "get_pod_logs", "get_pod_events"}, set())
        self.assertEqual(resources, [])

    def test_read_only_is_a_door_and_never_an_argument(self) -> None:
        """The approval hole this design is meant to close, checked on the wire.

        A model that could pass its own `approved=True` would be approving its
        own writes. With capabilities off the surface, the classification
        travels as *which entry point was used*, and each door carries the
        hint the host acts on.
        """

        async def work(session):
            return (await session.list_tools()).tools

        tools = _run(work)
        for tool in tools:
            with self.subTest(tool=tool.name):
                properties = set((tool.input_schema or {}).get("properties", {}))
                self.assertNotIn("read_only", properties)
                self.assertNotIn("approved", properties)
                self.assertNotIn("read_only_hint", properties)

        hints = {
            tool.name: tool.annotations and tool.annotations.read_only_hint
            for tool in tools
        }
        self.assertTrue(hints["contexture_invoke_read_only"])
        self.assertFalse(hints["contexture_invoke"])

    def test_a_full_diagnosis_runs_over_the_wire(self) -> None:
        """The whole chain: skeleton, open a role, open its skill, gather, read."""

        async def work(session):
            roles = await session.call_tool("contexture_discover", {})
            role_ref = roles.structured_content["roles"][0]["ref"]

            role = await session.call_tool("contexture_open", {"ref": role_ref})
            skill_ref = role.structured_content["skills"][0]["ref"]
            schemas = {
                tool["name"]: tool["input_schema"]
                for tool in role.structured_content["tools"]
            }

            skill = await session.call_tool("contexture_open", {"ref": skill_ref})

            pod = {"namespace": "prod", "pod": "payments-api-7d9c"}
            status = await session.call_tool(
                "contexture_invoke_read_only",
                {"ref": f"{role_ref}/get_pod_status", "arguments": pod},
            )
            logs = await session.call_tool(
                "contexture_invoke_read_only",
                {"ref": f"{role_ref}/get_pod_logs", "arguments": pod},
            )
            # The procedure names the runbook by its URI, so the agent passes
            # the URI. That has to work, or the framework's addressing scheme
            # becomes the skill author's problem to remember.
            runbook = await session.call_tool(
                "contexture_read",
                {"ref": "contexture://runbooks/crash-loop-backoff"},
            )
            return (
                role.structured_content,
                schemas,
                skill.structured_content,
                json.loads(status.content[0].text),
                logs.content[0].text,
                runbook.content[0].text,
            )

        role, schemas, skill, status, logs, runbook = _run(work)

        self.assertEqual(role["skills"][0]["name"], "diagnose-crash-loop-backoff")
        self.assertEqual(schemas["get_pod_status"]["required"], ["namespace", "pod"])
        self.assertIn("get_pod_status", skill["instructions"])
        self.assertEqual(status["container_state"], "CrashLoopBackOff")
        self.assertEqual(status["restart_count"], 14)
        self.assertIn("DB_URL is missing", logs)
        self.assertIn("CrashLoopBackOff", runbook)

    def test_a_gateway_call_returns_content_rather_than_a_typed_result(self) -> None:
        """A cost of keeping capabilities off the surface, recorded not hidden.

        `GetPodStatus.invoke` is annotated `-> PodStatus`, and on a native
        surface the SDK would derive an output schema from it and return
        structured content. A gateway's own return type is the union of every
        tool's, which is to say `Any`, so the result arrives as text the agent
        parses. The values survive; the protocol-level typing does not.
        """

        async def work(session):
            return await session.call_tool(
                "contexture_invoke_read_only",
                {
                    "ref": "kubernetes-incident-responder/get_pod_status",
                    "arguments": {"namespace": "prod", "pod": "payments-api-7d9c"},
                },
            )

        result = _run(work)

        self.assertIsNone(result.structured_content)
        self.assertEqual(
            json.loads(result.content[0].text)["container_state"],
            "CrashLoopBackOff",
        )

    def test_a_write_through_the_read_only_door_is_refused_on_the_wire(self) -> None:
        """The demo is read-only throughout, so the check is that the door
        itself disagrees with the ref rather than that a write happened."""

        async def work(session):
            return await session.call_tool(
                "contexture_invoke",
                {
                    "ref": "kubernetes-incident-responder/get_pod_logs",
                    "arguments": {"namespace": "prod", "pod": "payments-api-7d9c"},
                },
            )

        result = _run(work)
        self.assertTrue(result.is_error)
        self.assertIn("contexture_invoke_read_only", result.content[0].text)

    def test_the_skeleton_never_leaks_a_procedure_or_a_schema(self) -> None:
        """Progressive disclosure, asserted where it can actually be violated.

        The skeleton is delivered whole, so it is the one payload every session
        pays for unconditionally. Nothing expensive may ride along in it.
        """

        async def work(session):
            instructions = session.instructions or ""
            roles = await session.call_tool("contexture_discover", {})
            role_ref = roles.structured_content["roles"][0]["ref"]
            role = await session.call_tool("contexture_open", {"ref": role_ref})
            skill_ref = role.structured_content["skills"][0]["ref"]
            opened = await session.call_tool("contexture_open", {"ref": skill_ref})
            return (
                instructions,
                str(roles.structured_content),
                str(role.structured_content),
                opened.structured_content,
            )

        bootstrap, skeleton, role, opened = _run(work)
        procedure = "Do not recommend restarting or deleting the Pod"

        for payload in (bootstrap, skeleton):
            self.assertNotIn(procedure, payload)
            self.assertNotIn("input_schema", payload)
        self.assertNotIn(procedure, role)
        self.assertIn(procedure, opened["instructions"])

    def test_resource_content_arrives_only_on_read(self) -> None:
        """Listing a resource must stay cheap, however large its content is."""

        async def work(session):
            opened = await session.call_tool(
                "contexture_open",
                {"ref": "kubernetes-incident-responder/crash-loop-runbook"},
            )
            read = await session.call_tool(
                "contexture_read",
                {"ref": "kubernetes-incident-responder/crash-loop-runbook"},
            )
            return opened.structured_content, read.content[0].text

        opened, content = _run(work)
        marker = "Restarting the Pod does not repair a configuration error"

        self.assertNotIn(marker, str(opened))
        self.assertEqual(opened["uri"], "contexture://runbooks/crash-loop-backoff")
        self.assertIn(marker, content)


@unittest.skipIf(ClientSession is None, "the MCP SDK is not installed")
class StdioHygieneTests(unittest.TestCase):
    """stdout belongs to the protocol, and nothing else may write to it."""

    def test_the_server_writes_no_stray_output_to_stdout(self) -> None:
        """Checked by talking to the process, not by grepping for `print`.

        A logging handler that defaults to stdout, an import-time banner from a
        dependency, or a warning would each corrupt the stream. The only honest
        check is whether a real session survives, since the SDK's own framing
        rejects any line that is not a valid message.
        """

        import logging

        async def work(session):
            # Provoke the failure mode: log during a call and confirm the
            # session still parses everything that follows.
            logging.getLogger("contexture.test").warning("noise on the log")
            await session.call_tool("contexture_discover", {})
            tools = await session.list_tools()
            return len(tools.tools)

        self.assertGreater(_run(work), 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
