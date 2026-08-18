"""Tests for MCP 2026-07-28 request metadata and headers."""

from __future__ import annotations

import base64
import unittest

from role_runtime import (
    ClientInfo,
    MCPProtocolError,
    MCPRequestFactory,
    MCPTool,
    ModelValidationError,
)
from role_runtime.mcp.protocol import (
    build_request_headers,
    encode_header_value,
    validate_x_mcp_headers,
)


class ProtocolTests(unittest.TestCase):
    def test_request_contains_per_request_protocol_metadata(self) -> None:
        factory = MCPRequestFactory(
            client_info=ClientInfo(name="test-client", version="1.0.0")
        )
        request = factory.build(
            request_id=7,
            method="tools/list",
            params={},
        )
        payload = request.to_dict()
        metadata = payload["params"]["_meta"]

        self.assertEqual(
            metadata["io.modelcontextprotocol/protocolVersion"],
            "2026-07-28",
        )
        self.assertEqual(
            metadata["io.modelcontextprotocol/clientInfo"]["name"],
            "test-client",
        )
        self.assertEqual(
            metadata["io.modelcontextprotocol/clientCapabilities"],
            {},
        )

    def test_tools_call_headers_include_custom_schema_headers(self) -> None:
        tool = MCPTool(
            name="execute_sql",
            description="Execute a query.",
            input_schema={
                "type": "object",
                "properties": {
                    "region": {
                        "type": "string",
                        "x-mcp-header": "Region",
                    },
                    "query": {"type": "string"},
                },
                "required": ["region", "query"],
            },
        )
        factory = MCPRequestFactory(
            client_info=ClientInfo(name="test-client", version="1.0.0")
        )
        request = factory.build(
            request_id=1,
            method="tools/call",
            params={
                "name": "execute_sql",
                "arguments": {
                    "region": "us-west1",
                    "query": "SELECT 1",
                },
            },
        )
        headers = build_request_headers(request, tool=tool)

        self.assertEqual(headers["Mcp-Method"], "tools/call")
        self.assertEqual(headers["Mcp-Name"], "execute_sql")
        self.assertEqual(headers["Mcp-Param-Region"], "us-west1")

    def test_non_ascii_header_value_uses_base64_sentinel(self) -> None:
        encoded = encode_header_value("Hello, café")
        expected = base64.b64encode("Hello, café".encode("utf-8")).decode("ascii")
        self.assertEqual(encoded, f"=?base64?{expected}?=")

    def test_invalid_x_mcp_header_location_is_rejected(self) -> None:
        tool = MCPTool(
            name="bad_tool",
            description="Contains an invalid header annotation.",
            input_schema={
                "type": "object",
                "oneOf": [
                    {
                        "type": "object",
                        "properties": {
                            "region": {
                                "type": "string",
                                "x-mcp-header": "Region",
                            }
                        },
                    }
                ],
            },
        )
        with self.assertRaises(ModelValidationError):
            validate_x_mcp_headers(tool)

    def test_tools_call_requires_name_header_source(self) -> None:
        factory = MCPRequestFactory(
            client_info=ClientInfo(name="test-client", version="1.0.0")
        )
        request = factory.build(
            request_id=3,
            method="tools/call",
            params={"arguments": {}},
        )
        with self.assertRaises(MCPProtocolError):
            build_request_headers(request)

    def test_boolean_is_not_accepted_as_json_rpc_id(self) -> None:
        factory = MCPRequestFactory(
            client_info=ClientInfo(name="test-client", version="1.0.0")
        )
        with self.assertRaises(MCPProtocolError):
            factory.build(
                request_id=True,
                method="tools/list",
                params={},
            )
