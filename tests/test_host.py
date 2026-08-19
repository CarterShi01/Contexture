"""Tests for the inbound MCP host port."""

from __future__ import annotations

import unittest
from typing import Any, Mapping

from contexture import DuplicateNameError, MCPResource, MCPTool, NodeNotFoundError
from contexture.protocol import (
    InMemoryHost,
    InMemoryTransport,
    MCPClient,
    MCPHostPort,
    ResourceContents,
    ToolResult,
)

from examples.engineering_team import build_github_host, build_kubernetes_host

TOOL = MCPTool(
    name="echo",
    description="Return what it was given.",
    input_schema={
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
)

RESOURCE = MCPResource(
    name="greeting",
    description="A fixed greeting.",
    uri="memory://greeting",
    mime_type="text/plain",
)


async def _echo(arguments: Mapping[str, Any]) -> ToolResult:
    return ToolResult.text(arguments["text"])


async def _greet(uri: str) -> ResourceContents:
    return ResourceContents(uri=uri, text="hello", mime_type="text/plain")


def _host() -> InMemoryHost:
    host = InMemoryHost()
    host.register_tool(TOOL, _echo)
    host.register_resource(RESOURCE, _greet)
    return host


class PortTests(unittest.TestCase):
    def test_the_reference_host_satisfies_the_port(self) -> None:
        host: MCPHostPort = InMemoryHost()
        self.assertTrue(hasattr(host, "register_tool"))
        self.assertTrue(hasattr(host, "register_resource"))

    def test_registering_one_tool_twice_is_rejected(self) -> None:
        host = _host()
        with self.assertRaises(DuplicateNameError):
            host.register_tool(TOOL, _echo)

    def test_registering_one_resource_twice_is_rejected(self) -> None:
        host = _host()
        with self.assertRaises(DuplicateNameError):
            host.register_resource(RESOURCE, _greet)

    def test_an_unregistered_lookup_is_a_lookup_error(self) -> None:
        with self.assertRaises(NodeNotFoundError):
            _host().get_tool("missing")


class RoundTripTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.host = _host()
        self.client = MCPClient(
            transport=InMemoryTransport(handler=self.host.handle)
        )

    async def test_a_registered_tool_answers_tools_list(self) -> None:
        catalog = await self.client.list_tools()
        self.assertEqual([tool.name for tool in catalog.tools], ["echo"])

    async def test_a_registered_tool_answers_tools_call(self) -> None:
        outcome = await self.client.call_tool(TOOL, {"text": "ping"})
        self.assertTrue(outcome.is_complete)
        self.assertFalse(outcome.is_error)
        self.assertEqual(outcome.content[0]["text"], "ping")

    async def test_a_registered_resource_answers_resources_read(self) -> None:
        catalog = await self.client.list_resources()
        self.assertEqual(
            [resource.uri for resource in catalog.resources], [RESOURCE.uri]
        )

        read = await self.client.read_resource(RESOURCE)
        self.assertEqual(read.text, "hello")

    async def test_an_unknown_method_returns_a_protocol_error(self) -> None:
        response = await self.host.handle({"id": 1, "method": "prompts/list"})
        self.assertEqual(response["error"]["code"], -32601)


class DemoHostTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_demo_hosts_serve_their_declared_catalogs(self) -> None:
        kubernetes = build_kubernetes_host()
        github = build_github_host()

        self.assertEqual(
            sorted(kubernetes.tools),
            ["delete_pod", "get_events", "get_pod_logs"],
        )
        self.assertEqual(sorted(github.tools), ["create_issue"])

        client = MCPClient(transport=InMemoryTransport(handler=kubernetes.handle))
        outcome = await client.call_tool(
            kubernetes.get_tool("get_pod_logs"),
            {"namespace": "payments", "pod": "api-1", "container": "api"},
        )
        self.assertIn("connection refused", outcome.content[0]["text"])
