"""Tests for the MCP resource catalog, reads, and refresh safety."""

from __future__ import annotations

import unittest
from typing import Any, Mapping

from role_runtime import (
    InMemoryTransport,
    MCPBinding,
    MCPClient,
    MCPResource,
    MCPServer,
    ModelValidationError,
    Role,
    RoleRuntime,
)

from examples.engineering_team import RUNBOOK_URI, build_demo_environment

SERVER_ID = "docs-server"
FIRST_URI = "resource://docs/first"
SECOND_URI = "resource://docs/second"


def _resource(uri: str, name: str) -> MCPResource:
    return MCPResource(
        name=name,
        description=f"The {name} document.",
        uri=uri,
        mime_type="text/markdown",
    )


def _build_environment(handler) -> tuple[RoleRuntime, MCPServer]:
    server = MCPServer(
        server_id=SERVER_ID,
        name="docs",
        description="Serves documentation resources.",
        resources=[_resource(FIRST_URI, "first")],
    )
    role = Role(
        name="reader",
        description="Read documentation.",
        instructions="Read only what is granted.",
        mcp_bindings=[
            MCPBinding(server=server, allowed_resources=[FIRST_URI]),
        ],
    )
    runtime = RoleRuntime(
        root_role=role,
        mcp_clients={SERVER_ID: MCPClient(transport=InMemoryTransport(handler=handler))},
    )
    return runtime, server


class ResourceReferenceTests(unittest.TestCase):
    def test_resource_ref_survives_a_uri_containing_slashes(self) -> None:
        server = MCPServer(
            server_id=SERVER_ID,
            name="docs",
            description="Serves documentation resources.",
            resources=[_resource(FIRST_URI, "first")],
        )
        resource_ref = server.make_resource_ref(FIRST_URI)

        self.assertEqual(resource_ref, f"{SERVER_ID}/{FIRST_URI}")
        self.assertEqual(server.parse_resource_ref(resource_ref), FIRST_URI)

    def test_duplicate_resource_uris_are_rejected(self) -> None:
        with self.assertRaises(ModelValidationError):
            MCPServer(
                server_id=SERVER_ID,
                name="docs",
                description="Serves documentation resources.",
                resources=[
                    _resource(FIRST_URI, "first"),
                    _resource(FIRST_URI, "duplicate"),
                ],
            )


class ResourceReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_sends_the_protocol_uri_and_name_header(self) -> None:
        environment = build_demo_environment()
        read = await environment.runtime.read_resource(
            "engineering-team/k8s-troubleshooter",
            f"production-kubernetes/{RUNBOOK_URI}",
        )

        self.assertIn("CrashLoopBackOff", read.text or "")
        self.assertEqual(read.uri, RUNBOOK_URI)

        payload, headers = environment.kubernetes_transport.requests[-1]
        self.assertEqual(payload["method"], "resources/read")
        self.assertEqual(payload["params"]["uri"], RUNBOOK_URI)
        self.assertEqual(headers["Mcp-Method"], "resources/read")
        self.assertEqual(headers["Mcp-Name"], RUNBOOK_URI)


class ResourceCatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_resources_follows_every_page(self) -> None:
        async def handler(
            payload: dict[str, Any],
            headers: Mapping[str, str],
        ) -> dict[str, Any]:
            cursor = payload.get("params", {}).get("cursor")
            if cursor is None:
                page = {
                    "resources": [_resource(FIRST_URI, "first").to_protocol_dict()],
                    "nextCursor": "page-2",
                }
            else:
                page = {
                    "resources": [_resource(SECOND_URI, "second").to_protocol_dict()]
                }
            return {"jsonrpc": "2.0", "id": payload["id"], "result": page}

        client = MCPClient(transport=InMemoryTransport(handler=handler))
        catalog = await client.list_resources()

        self.assertEqual(
            [resource.uri for resource in catalog.resources],
            [FIRST_URI, SECOND_URI],
        )
        self.assertEqual(catalog.warnings, ())

    async def test_malformed_resource_is_skipped_with_a_warning(self) -> None:
        async def handler(
            payload: dict[str, Any],
            headers: Mapping[str, str],
        ) -> dict[str, Any]:
            return {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "resources": [
                        {"uri": SECOND_URI},
                        _resource(FIRST_URI, "first").to_protocol_dict(),
                    ]
                },
            }

        client = MCPClient(transport=InMemoryTransport(handler=handler))
        catalog = await client.list_resources()

        self.assertEqual(
            [resource.uri for resource in catalog.resources],
            [FIRST_URI],
        )
        self.assertEqual(len(catalog.warnings), 1)
        self.assertIn(SECOND_URI, catalog.warnings[0])


class CatalogRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_replaces_both_catalogs(self) -> None:
        async def handler(
            payload: dict[str, Any],
            headers: Mapping[str, str],
        ) -> dict[str, Any]:
            if payload["method"] == "tools/list":
                result: dict[str, Any] = {"tools": []}
            else:
                result = {
                    "resources": [
                        _resource(FIRST_URI, "first").to_protocol_dict(),
                        _resource(SECOND_URI, "second").to_protocol_dict(),
                    ]
                }
            return {"jsonrpc": "2.0", "id": payload["id"], "result": result}

        runtime, server = _build_environment(handler)
        refresh = await runtime.refresh_server_catalog(SERVER_ID)

        self.assertEqual(len(refresh.resources.resources), 2)
        self.assertEqual(
            {resource.uri for resource in server.resources},
            {FIRST_URI, SECOND_URI},
        )

    async def test_refresh_rejects_a_catalog_missing_a_granted_resource(self) -> None:
        async def handler(
            payload: dict[str, Any],
            headers: Mapping[str, str],
        ) -> dict[str, Any]:
            if payload["method"] == "tools/list":
                result: dict[str, Any] = {"tools": []}
            else:
                result = {
                    "resources": [_resource(SECOND_URI, "second").to_protocol_dict()]
                }
            return {"jsonrpc": "2.0", "id": payload["id"], "result": result}

        runtime, server = _build_environment(handler)
        with self.assertRaises(ModelValidationError):
            await runtime.refresh_server_catalog(SERVER_ID)

        self.assertEqual(
            [resource.uri for resource in server.resources],
            [FIRST_URI],
            "a rejected refresh must leave the previous catalog in place",
        )
