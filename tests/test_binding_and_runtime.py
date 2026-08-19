"""Tests for least-privilege bindings and execution-time enforcement."""

from __future__ import annotations

import unittest

from contexture import (
    CapabilityDeniedError,
    ConfirmationRequired,
    MCPBinding,
    MCPServer,
    ModelValidationError,
    NodeNotFoundError,
)

from examples.engineering_team import (
    DEPLOYMENT_URI,
    REPO_README_URI,
    RUNBOOK_URI,
    build_demo_environment,
)


class BindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = build_demo_environment()

    def test_server_id_reserves_slash_for_host_references(self) -> None:
        with self.assertRaises(ModelValidationError):
            MCPServer(
                server_id="cluster/production",
                name="kubernetes",
                description="Invalid server id for the host reference format.",
            )

    def test_unknown_tool_cannot_be_granted(self) -> None:
        with self.assertRaises(ModelValidationError):
            MCPBinding(
                server=self.environment.kubernetes_server,
                allowed_tools=["does_not_exist"],
            )

    def test_unknown_resource_cannot_be_granted(self) -> None:
        with self.assertRaises(ModelValidationError):
            MCPBinding(
                server=self.environment.kubernetes_server,
                allowed_resources=["resource://kubernetes/does-not-exist"],
            )

    def test_ungranted_tool_is_denied(self) -> None:
        binding = self.environment.troubleshooter.mcp_bindings[0]
        with self.assertRaises(CapabilityDeniedError):
            binding.require_tool("delete_pod")

    def test_ungranted_resource_is_denied(self) -> None:
        binding = self.environment.operator.mcp_bindings[0]
        self.assertIsNotNone(binding.require_resource(DEPLOYMENT_URI))
        with self.assertRaises(CapabilityDeniedError):
            binding.require_resource(RUNBOOK_URI)


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.environment = build_demo_environment()

    async def test_read_only_tool_runs_without_confirmation(self) -> None:
        outcome = await self.environment.runtime.call_tool(
            "engineering-team/k8s-troubleshooter",
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

        _, headers = self.environment.kubernetes_transport.requests[-1]
        self.assertEqual(headers["Mcp-Method"], "tools/call")
        self.assertEqual(headers["Mcp-Name"], "get_pod_logs")
        self.assertEqual(headers["Mcp-Param-Namespace"], "payments")
        self.assertEqual(headers["MCP-Protocol-Version"], "2026-07-28")

    async def test_write_tool_requires_explicit_confirmation(self) -> None:
        with self.assertRaises(ConfirmationRequired):
            await self.environment.runtime.call_tool(
                "engineering-team/k8s-operator",
                "production-kubernetes/delete_pod",
                {"namespace": "payments", "pod": "payment-service-1"},
            )

        outcome = await self.environment.runtime.call_tool(
            "engineering-team/k8s-operator",
            "production-kubernetes/delete_pod",
            {"namespace": "payments", "pod": "payment-service-1"},
            approved=True,
        )
        self.assertFalse(outcome.is_error)

    async def test_ungranted_tool_is_denied_at_the_runtime(self) -> None:
        with self.assertRaises(CapabilityDeniedError):
            await self.environment.runtime.call_tool(
                "engineering-team/k8s-troubleshooter",
                "production-kubernetes/delete_pod",
                {"namespace": "payments", "pod": "payment-service-1"},
            )

    async def test_each_role_reaches_only_its_own_server(self) -> None:
        outcome = await self.environment.runtime.call_tool(
            "engineering-team/github-liaison",
            "github-cloud/create_issue",
            {
                "repository": "payments/payments-api",
                "title": "CrashLoopBackOff",
                "body": "Connection refused.",
            },
            approved=True,
        )
        self.assertFalse(outcome.is_error)
        self.assertTrue(self.environment.github_transport.requests)

        with self.assertRaises(CapabilityDeniedError):
            await self.environment.runtime.call_tool(
                "engineering-team/k8s-troubleshooter",
                "github-cloud/create_issue",
                {
                    "repository": "payments/payments-api",
                    "title": "CrashLoopBackOff",
                    "body": "Connection refused.",
                },
                approved=True,
            )

    async def test_github_tool_is_not_host_classified_read_only(self) -> None:
        with self.assertRaises(ConfirmationRequired):
            await self.environment.runtime.call_tool(
                "engineering-team/github-liaison",
                "github-cloud/create_issue",
                {
                    "repository": "payments/payments-api",
                    "title": "CrashLoopBackOff",
                    "body": "Connection refused.",
                },
            )

    async def test_readme_resource_is_readable_only_by_the_liaison(self) -> None:
        read = await self.environment.runtime.read_resource(
            "engineering-team/github-liaison",
            f"github-cloud/{REPO_README_URI}",
        )
        self.assertIn("Payments Platform", read.text or "")

        with self.assertRaises(CapabilityDeniedError):
            await self.environment.runtime.read_resource(
                "engineering-team/k8s-troubleshooter",
                f"github-cloud/{REPO_README_URI}",
            )

    async def test_a_malformed_reference_is_a_lookup_error(self) -> None:
        with self.assertRaises(NodeNotFoundError):
            await self.environment.runtime.read_resource(
                "engineering-team/k8s-troubleshooter",
                "missing-separator",
            )
