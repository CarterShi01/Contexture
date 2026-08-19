"""Tests for rendering one declaration into several agent surfaces."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from contexture import Resource, Role, Skill, TargetRenderError, Tool
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


class InspectPodFailure(Skill):
    """Diagnose why a Pod is crashing, restarting, or failing to start."""

    instructions = "1. Identify the cluster. 2. Read the logs."


class GetPodLogs(Tool):
    """Return recent container logs for one Pod."""

    name = "get_pod_logs"
    read_only = True

    async def invoke(self, namespace: str, pod: str) -> str:
        return f"{namespace}/{pod}"


class DeletePod(Tool):
    """Delete one Pod so its controller recreates it."""

    name = "delete_pod"

    async def invoke(self, namespace: str, pod: str) -> str:
        return f"{namespace}/{pod}"


class CrashLoopRunbook(Resource):
    """How to diagnose a container that keeps restarting."""

    uri = "contexture://runbooks/crash-loop"
    mime_type = "text/markdown"

    async def read(self) -> str:
        return "# Runbook"


class K8sTroubleshooter(Role):
    """Diagnose unhealthy Pods without changing the cluster."""

    instructions = "Start with read-only inspection."

    inspect = InspectPodFailure
    logs = GetPodLogs
    runbook = CrashLoopRunbook


class K8sOperator(Role):
    """Repair unhealthy workloads once the cause is known."""

    instructions = "Change the cluster only after the cause is established."

    logs = GetPodLogs
    delete = DeletePod


class EngineeringTeam(Role):
    """Route Kubernetes work to the role that owns it."""

    instructions = "Pick the role that matches the request."

    troubleshooter = K8sTroubleshooter
    operator = K8sOperator


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

    def test_claude_code_emits_memory_and_skills(self) -> None:
        rendered = ClaudeCodeAdapter().render(self.role)

        self.assertIn("CLAUDE.md", rendered.paths)
        self.assertIn(
            ".claude/skills/inspect-pod-failure/SKILL.md", rendered.paths
        )

        skill = rendered.get(".claude/skills/inspect-pod-failure/SKILL.md")
        self.assertTrue(skill.content.startswith("---\n"))
        self.assertIn("name: inspect-pod-failure", skill.content)

    def test_no_target_generates_server_configuration(self) -> None:
        """Contexture is the server now; nothing here configures another one."""

        for name, rendered in render_all(self.role, all_adapters()).items():
            with self.subTest(target=name):
                for path in rendered.paths:
                    self.assertNotIn("mcp.json", path)
                    self.assertNotIn("config.toml", path)

    def test_codex_inlines_skills_and_says_so(self) -> None:
        rendered = CodexAdapter().render(self.role)

        self.assertEqual(rendered.paths, ("AGENTS.md",))
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

        root = rendered.get(".cursor/rules/engineering-team.mdc").content
        self.assertIn("alwaysApply: true", root)
        child = rendered.get(".cursor/rules/k8s-troubleshooter.mdc").content
        self.assertIn("alwaysApply: false", child)

    def test_a_role_surface_lists_only_that_roles_own_capabilities(self) -> None:
        rendered = CursorAdapter().render(self.role)

        troubleshooter = rendered.get(
            ".cursor/rules/k8s-troubleshooter.mdc"
        ).content
        self.assertIn("get_pod_logs", troubleshooter)
        self.assertNotIn(
            "delete_pod",
            troubleshooter,
            "the troubleshooter never declared delete_pod",
        )

        operator = rendered.get(".cursor/rules/k8s-operator.mdc").content
        self.assertIn("delete_pod", operator)
        self.assertNotIn(
            "crash-loop",
            operator,
            "the runbook belongs to the troubleshooter",
        )

    def test_the_access_column_uses_the_declared_classification(self) -> None:
        operator = (
            CursorAdapter()
            .render(self.role)
            .get(".cursor/rules/k8s-operator.mdc")
            .content
        )

        # delete_pod is not declared read_only, so the surface must say
        # approval is required rather than treat every tool alike.
        for line in operator.splitlines():
            if "delete_pod" in line:
                self.assertIn("needs approval", line)
            if "get_pod_logs" in line:
                self.assertIn("read-only", line)

    def test_a_flattening_target_reports_what_it_dropped(self) -> None:
        for adapter in (CodexAdapter(), CursorAdapter()):
            with self.subTest(target=adapter.name):
                self.assertTrue(adapter.render(self.role).notes)

    def test_a_lossless_target_reports_nothing(self) -> None:
        self.assertEqual(ClaudeCodeAdapter().render(self.role).notes, ())

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
