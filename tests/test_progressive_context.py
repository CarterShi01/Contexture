"""Tests for route-versus-active progressive disclosure."""

from __future__ import annotations

import unittest

from role_runtime import CapabilitySelection, CompileRequest

from examples.kubernetes_team import build_demo_environment


class ProgressiveContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = build_demo_environment()

    def test_root_exposes_only_child_routes(self) -> None:
        compiled = self.environment.runtime.compile("k8s-team").to_dict()
        role = compiled["role"]

        self.assertIn("instructions", role)
        self.assertEqual(len(role["available_sub_roles"]), 2)
        self.assertNotIn("instructions", role["available_sub_roles"][0])
        self.assertEqual(role["available_sub_roles"][0]["kind"], "role")

    def test_active_role_keeps_capabilities_as_routes(self) -> None:
        compiled = self.environment.runtime.compile(
            "k8s-team/k8s-troubleshooter"
        ).to_dict()
        role = compiled["role"]

        self.assertNotIn("instructions", role["available_skills"][0])
        self.assertNotIn("inputSchema", role["available_mcp_tools"][0])
        self.assertNotIn("uri", role["available_data_sources"][0])

    def test_selection_activates_only_requested_capabilities(self) -> None:
        compiled = self.environment.runtime.compile(
            "k8s-team/k8s-troubleshooter",
            CompileRequest(
                selection=CapabilitySelection(
                    skill_names=("inspect-pod-failure",),
                    tool_refs=("production-kubernetes/get_pod_logs",),
                    data_refs=("runbook/kubernetes-incidents",),
                )
            ),
        ).to_dict()
        activated = compiled["activated_capabilities"]

        self.assertIn("instructions", activated["skills"][0])
        self.assertIn("inputSchema", activated["mcp_tools"][0])
        self.assertIn("uri", activated["data_sources"][0])
        self.assertEqual(len(activated["mcp_tools"]), 1)
