"""Tests for rendering one declaration into several agent surfaces."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from contexture import TargetRenderError
from contexture.targets import (
    Artifact,
    Change,
    ClaudeCodeAdapter,
    CodexAdapter,
    CursorAdapter,
    adapter_for,
    all_adapters,
    plan,
    render_all,
    write,
)

from examples.engineering_team import EngineeringTeam


class ArtifactTests(unittest.TestCase):
    def test_an_absolute_path_is_refused(self) -> None:
        with self.assertRaises(TargetRenderError):
            Artifact(path="/etc/passwd", content="x")

    def test_parent_traversal_is_refused(self) -> None:
        with self.assertRaises(TargetRenderError):
            Artifact(path="../outside.md", content="x")

    def test_digest_tracks_content(self) -> None:
        first = Artifact(path="a.md", content="one")
        same = Artifact(path="a.md", content="one")
        other = Artifact(path="a.md", content="two")
        self.assertEqual(first.digest, same.digest)
        self.assertNotEqual(first.digest, other.digest)


class RenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.role = EngineeringTeam()

    def test_claude_code_emits_memory_skills_and_mcp_config(self) -> None:
        rendered = ClaudeCodeAdapter().render(self.role)

        self.assertIn("CLAUDE.md", rendered.paths)
        self.assertIn(".mcp.json", rendered.paths)
        self.assertIn(
            ".claude/skills/inspect-pod-failure/SKILL.md", rendered.paths
        )

        skill = rendered.get(".claude/skills/inspect-pod-failure/SKILL.md")
        self.assertTrue(skill.content.startswith("---\n"))
        self.assertIn("name: inspect-pod-failure", skill.content)

    def test_mcp_config_carries_both_transports(self) -> None:
        config = json.loads(ClaudeCodeAdapter().render(self.role).get(".mcp.json").content)
        servers = config["mcpServers"]

        self.assertEqual(servers["production-kubernetes"]["type"], "stdio")
        self.assertEqual(servers["production-kubernetes"]["command"], "npx")
        self.assertEqual(servers["github-cloud"]["type"], "http")
        self.assertIn("url", servers["github-cloud"])

    def test_codex_inlines_skills_and_says_so(self) -> None:
        rendered = CodexAdapter().render(self.role)

        self.assertEqual(
            rendered.paths, ("AGENTS.md", ".codex/config.toml")
        )
        agents = rendered.get("AGENTS.md").content
        self.assertIn("Skill: inspect-pod-failure", agents)
        self.assertIn("1. Identify the cluster", agents)

        joined = " ".join(rendered.notes)
        self.assertIn("no separate skill artifact", joined)
        self.assertIn("route/active distinction was flattened", joined)

    def test_cursor_emits_one_rule_per_role_and_skill(self) -> None:
        rendered = CursorAdapter().render(self.role)

        self.assertIn(".cursor/rules/engineering-team.mdc", rendered.paths)
        self.assertIn(".cursor/rules/k8s-troubleshooter.mdc", rendered.paths)
        self.assertIn(
            ".cursor/rules/skill-inspect-pod-failure.mdc", rendered.paths
        )
        self.assertIn(".cursor/mcp.json", rendered.paths)

        root = rendered.get(".cursor/rules/engineering-team.mdc").content
        self.assertIn("alwaysApply: true", root)
        child = rendered.get(".cursor/rules/k8s-troubleshooter.mdc").content
        self.assertIn("alwaysApply: false", child)

    def test_a_role_surface_lists_only_that_roles_grants(self) -> None:
        rendered = CursorAdapter().render(self.role)

        troubleshooter = rendered.get(
            ".cursor/rules/k8s-troubleshooter.mdc"
        ).content
        self.assertIn("get_pod_logs", troubleshooter)
        self.assertNotIn(
            "delete_pod",
            troubleshooter,
            "the troubleshooter was never granted delete_pod",
        )

        operator = rendered.get(".cursor/rules/k8s-operator.mdc").content
        self.assertIn("delete_pod", operator)
        self.assertNotIn(
            "create_issue",
            operator,
            "the operator holds no binding to the GitHub server",
        )

    def test_the_access_column_uses_the_host_classification(self) -> None:
        operator = (
            CursorAdapter()
            .render(self.role)
            .get(".cursor/rules/k8s-operator.mdc")
            .content
        )

        # delete_pod is granted but not host-classified read-only, so the
        # surface must say approval is required rather than repeat the
        # server's own readOnlyHint.
        for line in operator.splitlines():
            if "delete_pod" in line:
                self.assertIn("needs approval", line)
            if "get_pod_logs" in line:
                self.assertIn("read-only", line)

    def test_every_target_reports_what_it_dropped(self) -> None:
        for name, rendered in render_all(self.role, all_adapters()).items():
            with self.subTest(target=name):
                self.assertTrue(rendered.notes)

    def test_rendering_is_deterministic(self) -> None:
        first = ClaudeCodeAdapter().render(EngineeringTeam())
        second = ClaudeCodeAdapter().render(EngineeringTeam())
        self.assertEqual(first.digest, second.digest)

    def test_adapter_lookup_by_name(self) -> None:
        self.assertIsInstance(adapter_for("claude-code"), ClaudeCodeAdapter)
        with self.assertRaises(LookupError):
            adapter_for("emacs")


class WriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rendered = ClaudeCodeAdapter().render(EngineeringTeam())

    def test_plan_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            computed = plan(self.rendered, directory)
            self.assertTrue(all(c.change is Change.CREATE for c in computed))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_write_creates_then_reports_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = write(self.rendered, directory)
            self.assertTrue(all(c.change is Change.CREATE for c in first))
            self.assertTrue((Path(directory) / "CLAUDE.md").exists())

            second = write(self.rendered, directory)
            self.assertTrue(second.is_current)
            self.assertEqual(second.writes, ())

    def test_drift_is_detected_as_an_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            write(self.rendered, directory)
            (Path(directory) / "CLAUDE.md").write_text("edited", encoding="utf-8")

            computed = plan(self.rendered, directory)
            changed = [c.artifact.path for c in computed.writes]
            self.assertEqual(changed, ["CLAUDE.md"])

    def test_dry_run_reports_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            computed = write(self.rendered, directory, dry_run=True)
            self.assertTrue(computed.writes)
            self.assertFalse((Path(directory) / "CLAUDE.md").exists())
