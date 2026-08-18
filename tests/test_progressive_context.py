"""Tests for route-versus-active progressive disclosure."""

from __future__ import annotations

import unittest

from role_runtime import CapabilitySelection, CompileRequest

from examples.engineering_team import RUNBOOK_URI, build_demo_environment


class ProgressiveContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = build_demo_environment()

    def test_root_exposes_only_child_routes(self) -> None:
        compiled = self.environment.runtime.compile("engineering-team").to_dict()
        role = compiled["role"]

        self.assertIn("instructions", role)
        self.assertEqual(len(role["available_sub_roles"]), 3)
        self.assertNotIn("instructions", role["available_sub_roles"][0])
        self.assertEqual(role["available_sub_roles"][0]["kind"], "role")

    def test_active_role_keeps_capabilities_as_routes(self) -> None:
        compiled = self.environment.runtime.compile(
            "engineering-team/k8s-troubleshooter"
        ).to_dict()
        role = compiled["role"]

        self.assertNotIn("instructions", role["available_skills"][0])
        self.assertNotIn("inputSchema", role["available_mcp_tools"][0])
        self.assertNotIn("uri", role["available_mcp_resources"][0])
        self.assertIn("resource_ref", role["available_mcp_resources"][0])

    def test_role_surface_hides_ungranted_capabilities(self) -> None:
        role = self.environment.runtime.compile(
            "engineering-team/k8s-troubleshooter"
        ).to_dict()["role"]

        tool_names = {tool["name"] for tool in role["available_mcp_tools"]}
        self.assertEqual(tool_names, {"get_pod_logs", "get_events"})

        servers = {tool["server_id"] for tool in role["available_mcp_tools"]}
        self.assertEqual(servers, {"production-kubernetes"})

    def test_selection_activates_only_requested_capabilities(self) -> None:
        compiled = self.environment.runtime.compile(
            "engineering-team/k8s-troubleshooter",
            CompileRequest(
                selection=CapabilitySelection(
                    skill_names=("inspect-pod-failure",),
                    tool_refs=("production-kubernetes/get_pod_logs",),
                    resource_refs=(f"production-kubernetes/{RUNBOOK_URI}",),
                )
            ),
        ).to_dict()
        activated = compiled["activated_capabilities"]

        self.assertIn("instructions", activated["skills"][0])
        self.assertIn("inputSchema", activated["mcp_tools"][0])
        self.assertEqual(len(activated["mcp_tools"]), 1)

        resource = activated["mcp_resources"][0]
        self.assertEqual(resource["uri"], RUNBOOK_URI)
        self.assertEqual(resource["mimeType"], "text/markdown")

    def test_activated_resource_carries_no_content(self) -> None:
        activated = self.environment.runtime.compile(
            "engineering-team/k8s-troubleshooter",
            CompileRequest(
                selection=CapabilitySelection(
                    resource_refs=(f"production-kubernetes/{RUNBOOK_URI}",),
                )
            ),
        ).to_dict()["activated_capabilities"]

        resource = activated["mcp_resources"][0]
        self.assertNotIn("text", resource)
        self.assertNotIn("contents", resource)
        self.assertNotIn("blob", resource)
