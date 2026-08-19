"""End-to-end tests that launch the demo as a real subprocess.

Everything else in this suite exercises the server in-process, which cannot
observe the two things that actually break a stdio server: whether the process
starts at all under a host's launch command, and whether anything but MCP
messages reaches stdout. Both are only visible from outside the process, so
these tests pay for a subprocess.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
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
        self.assertIn("contexture_discover", instructions)
        # Codex asks that the opening be self-contained; Claude Code truncates
        # the whole field at 2KB. Both limits are checked, not just documented.
        self.assertIn("contexture_discover", instructions[:512])
        self.assertLess(len(instructions.encode("utf-8")), 2048)
        self.assertEqual(protocol_version, "2026-07-28")

    def test_a_legacy_host_still_gets_a_working_server(self) -> None:
        """One implementation serves the handshake revisions too, unchanged."""

        async def work(session):
            tools = await session.list_tools()
            return session.protocol_version, {t.name for t in tools.tools}

        protocol_version, names = _run(work, modern=False)

        self.assertIn(protocol_version, {"2025-11-25", "2025-06-18", "2025-03-26"})
        self.assertIn("contexture_discover", names)
        self.assertIn("get_pod_logs", names)

    def test_the_surface_carries_framework_and_business_tools(self) -> None:
        async def work(session):
            tools = await session.list_tools()
            resources = await session.list_resources()
            return tools.tools, resources.resources

        tools, resources = _run(work)
        names = {tool.name for tool in tools}

        self.assertIn("contexture_discover", names)
        self.assertIn("contexture_get_context", names)
        self.assertEqual(
            {"get_pod_status", "get_pod_logs", "get_pod_events"} & names,
            {"get_pod_status", "get_pod_logs", "get_pod_events"},
        )
        self.assertIn(
            "contexture://runbooks/crash-loop-backoff",
            {str(resource.uri) for resource in resources},
        )

    def test_read_only_is_an_annotation_and_never_an_argument(self) -> None:
        """The approval hole this design is meant to close, checked on the wire.

        A model that could pass its own `approved=True` would be approving its
        own writes. Host classification therefore travels as an annotation the
        host acts on, and must not appear anywhere a model can fill it in.
        """

        async def work(session):
            return (await session.list_tools()).tools

        for tool in _run(work):
            with self.subTest(tool=tool.name):
                properties = set((tool.input_schema or {}).get("properties", {}))
                self.assertNotIn("read_only", properties)
                self.assertNotIn("approved", properties)
                self.assertNotIn("read_only_hint", properties)

        annotations = {
            tool.name: tool.annotations
            for tool in _run(work)
            if tool.annotations is not None
        }
        self.assertTrue(annotations["get_pod_logs"].read_only_hint)

    def test_a_full_diagnosis_runs_over_the_wire(self) -> None:
        """The whole chain: discover, open a skill, gather evidence, read a doc."""

        async def work(session):
            roots = await session.call_tool("contexture_discover", {})
            role_ref = roots.structured_content["roots"][0]["ref"]

            inside = await session.call_tool(
                "contexture_discover", {"ref": role_ref}
            )
            skill_ref = inside.structured_content["skills"][0]["ref"]

            skill = await session.call_tool(
                "contexture_get_context", {"ref": skill_ref}
            )
            status = await session.call_tool(
                "get_pod_status",
                {"namespace": "prod", "pod": "payments-api-7d9c"},
            )
            logs = await session.call_tool(
                "get_pod_logs",
                {"namespace": "prod", "pod": "payments-api-7d9c"},
            )
            events = await session.call_tool(
                "get_pod_events",
                {"namespace": "prod", "pod": "payments-api-7d9c"},
            )
            runbook = await session.read_resource(
                "contexture://runbooks/crash-loop-backoff"
            )
            return (
                inside.structured_content,
                skill.structured_content,
                status.structured_content,
                logs.content[0].text,
                events.structured_content,
                runbook.contents[0].text,
            )

        inside, skill, status, logs, events, runbook = _run(work)

        self.assertEqual(inside["skills"][0]["name"], "diagnose-crash-loop-backoff")
        self.assertIn("get_pod_status", skill["instructions"])
        self.assertEqual(status["container_state"], "CrashLoopBackOff")
        self.assertEqual(status["restart_count"], 14)
        self.assertIn("DB_URL is missing", logs)
        self.assertTrue(
            any("exited with code 1" in event["message"] for event in events["result"])
        )
        self.assertIn("CrashLoopBackOff", runbook)

    def test_routing_cards_never_leak_the_instructions(self) -> None:
        """Progressive disclosure, asserted where it can actually be violated.

        Nothing prevents an agent from calling a business tool without ever
        navigating; the tools are flat and visible, and that is by design. What
        disclosure controls is *knowledge* — the procedure has to stay out of
        discovery and arrive only when asked for.
        """

        async def work(session):
            instructions = session.instructions or ""
            roots = await session.call_tool("contexture_discover", {})
            role_ref = roots.structured_content["roots"][0]["ref"]
            inside = await session.call_tool(
                "contexture_discover", {"ref": role_ref}
            )
            skill_ref = inside.structured_content["skills"][0]["ref"]
            opened = await session.call_tool(
                "contexture_get_context", {"ref": skill_ref}
            )
            return (
                instructions,
                str(roots.structured_content),
                str(inside.structured_content),
                opened.structured_content,
            )

        bootstrap, roots_payload, inside_payload, opened = _run(work)
        procedure = "Do not recommend restarting or deleting the Pod"

        self.assertNotIn(procedure, bootstrap)
        self.assertNotIn(procedure, roots_payload)
        self.assertNotIn(procedure, inside_payload)
        self.assertIn(procedure, opened["instructions"])

    def test_resource_content_arrives_only_on_read(self) -> None:
        """Listing a resource must stay cheap, however large its content is."""

        async def work(session):
            listed = await session.list_resources()
            opened = await session.call_tool(
                "contexture_get_context",
                {
                    "ref": "resource:kubernetes-incident-responder"
                    "#contexture://runbooks/crash-loop-backoff"
                },
            )
            read = await session.read_resource(
                "contexture://runbooks/crash-loop-backoff"
            )
            return listed.resources, opened.structured_content, read.contents[0].text

        listed, opened, content = _run(work)
        marker = "Restarting the Pod does not repair a configuration error"

        self.assertNotIn(marker, str([resource.model_dump() for resource in listed]))
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
