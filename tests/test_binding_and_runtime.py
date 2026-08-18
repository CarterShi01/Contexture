"""Tests for least-privilege bindings and execution-time enforcement."""

from __future__ import annotations

import unittest

from role_runtime import (
    CapabilityDeniedError,
    ConfirmationRequired,
    MCPBinding,
    MCPServer,
    ModelValidationError,
)

from examples.kubernetes_team import build_demo_environment


class BindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = build_demo_environment()

    def test_server_id_reserves_slash_for_tool_references(self) -> None:
        with self.assertRaises(ModelValidationError):
            MCPServer(
                server_id="cluster/production",
                name="kubernetes",
                description="Invalid server id for the Host tool reference format.",
            )

    def test_unknown_tool_cannot_be_granted(self) -> None:
        with self.assertRaises(ModelValidationError):
            MCPBinding(
                server=self.environment.server,
                allowed_tools=["does_not_exist"],
            )

    def test_ungranted_tool_is_denied(self) -> None:
        binding = self.environment.troubleshooter.mcp_bindings[0]
        with self.assertRaises(CapabilityDeniedError):
            binding.require_tool("delete_pod")


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.environment = build_demo_environment()

    async def test_read_only_tool_runs_without_confirmation(self) -> None:
        outcome = await self.environment.runtime.call_tool(
            "k8s-team/k8s-troubleshooter",
            "production-kubernetes/get_pod_logs",
            {
                "namespace": "payments",
                "pod": "payment-service-1",
                "container": "payment-service",
                "previous": True,
            },
        )
        self.assertTrue(outcome.is_complete)
        self.assertFalse(outcome.is_error)

        _, headers = self.environment.transport.requests[-1]
        self.assertEqual(headers["Mcp-Method"], "tools/call")
        self.assertEqual(headers["Mcp-Name"], "get_pod_logs")
        self.assertEqual(headers["Mcp-Param-Namespace"], "payments")
        self.assertEqual(headers["MCP-Protocol-Version"], "2026-07-28")

    async def test_write_tool_requires_explicit_confirmation(self) -> None:
        with self.assertRaises(ConfirmationRequired):
            await self.environment.runtime.call_tool(
                "k8s-team/k8s-operator",
                "production-kubernetes/delete_pod",
                {"namespace": "payments", "pod": "payment-service-1"},
            )

        outcome = await self.environment.runtime.call_tool(
            "k8s-team/k8s-operator",
            "production-kubernetes/delete_pod",
            {"namespace": "payments", "pod": "payment-service-1"},
            approved=True,
        )
        self.assertFalse(outcome.is_error)

    async def test_data_read_uses_binding_and_provider(self) -> None:
        result = await self.environment.runtime.read_data(
            "k8s-team/k8s-troubleshooter",
            "runbook/kubernetes-incidents",
        )
        self.assertIn("CrashLoopBackOff", result.content)
