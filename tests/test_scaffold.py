"""Tests for the scaffold: what `contexture new` writes, and whether it runs.

The point of a template is that a copy of it works. So these tests render one
into a temporary directory and then use it the way a user would — import the
declarations, list the graph, execute a tool — rather than asserting on the
template text.
"""

from __future__ import annotations

import asyncio
import importlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from contexture import Role
from contexture.cli import (
    DEMO_TARGET,
    Names,
    UsageError,
    available_templates,
    find_project,
    new_project,
    resolve_target,
)
from contexture.core.disclosure.tree import ContextTree

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class NameDerivationTests(unittest.TestCase):
    def test_one_argument_derives_every_name(self) -> None:
        names = Names.derive("My Context")
        self.assertEqual(names.project_name, "my-context")
        self.assertEqual(names.package_name, "my_context")
        self.assertEqual(names.role_class, "MyContextAssistant")
        self.assertEqual(names.resource_scheme, "my-context")

    def test_punctuation_collapses_to_one_separator(self) -> None:
        self.assertEqual(Names.derive("k8s__ops!!team").project_name, "k8s-ops-team")

    def test_a_leading_digit_is_refused_with_a_reason(self) -> None:
        with self.assertRaises(UsageError) as caught:
            Names.derive("9lives")
        self.assertIn("Python package name", str(caught.exception))

    def test_a_name_with_nothing_usable_is_refused(self) -> None:
        with self.assertRaises(UsageError):
            Names.derive("...")


class TemplateShippingTests(unittest.TestCase):
    def test_the_project_template_is_present(self) -> None:
        self.assertIn("project", available_templates())

    def test_an_unknown_template_names_the_known_ones(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(UsageError) as caught:
                new_project("x", destination=Path(directory), template="nope")
        self.assertIn("project", str(caught.exception))

    def test_no_tmpl_suffix_survives_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = new_project("my-context", destination=Path(directory))
            self.assertEqual(list(root.rglob("*.tmpl")), [])

    def test_no_placeholder_remains_in_any_generated_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = new_project("my-context", destination=Path(directory))
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                with self.subTest(file=path.name):
                    self.assertNotIn("$", path.read_text(encoding="utf-8"))

    def test_the_placeholder_package_is_renamed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = new_project("my-context", destination=Path(directory))
            self.assertTrue((root / "my_context").is_dir())
            self.assertFalse((root / "module").exists())

    def test_writing_over_an_existing_directory_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            new_project("my-context", destination=Path(directory))
            with self.assertRaises(UsageError):
                new_project("my-context", destination=Path(directory))


class GeneratedProjectTests(unittest.TestCase):
    """The generated project is used here, not inspected."""

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = new_project("my-context", destination=Path(self._directory.name))
        sys.path.insert(0, str(self.root))
        self.addCleanup(sys.path.remove, str(self.root))
        for name in [m for m in sys.modules if m.startswith("my_context")]:
            del sys.modules[name]

    def test_the_generated_role_imports_and_declares_every_kind(self) -> None:
        module = importlib.import_module("my_context.assistant")
        role = module.MyContextAssistant()

        self.assertIsInstance(role, Role)
        self.assertEqual(role.name, "my-context-assistant")
        self.assertEqual([s.name for s in role.skills], ["check-target"])
        self.assertEqual(
            sorted(t.name for t in role.tools), ["health_runbook", "ping"]
        )

    def test_the_generated_tools_execute(self) -> None:
        module = importlib.import_module("my_context.assistant")
        role = module.MyContextAssistant()
        by_name = {tool.name: tool for tool in role.tools}

        result = asyncio.run(by_name["ping"].invoke(target="payments-api"))
        self.assertIn("payments-api", result)
        self.assertIn("reachable", asyncio.run(by_name["health_runbook"].invoke()))

    def test_the_generated_surface_publishes_the_runbook(self) -> None:
        """The scaffold shows both planes: a tool to navigate to, and a URI."""

        surface = importlib.import_module("my_context.surface").SURFACE

        (published,) = surface
        self.assertEqual(published.uri, "my-context://runbooks/health")
        self.assertEqual(
            published.opens, "my-context-assistant/health_runbook"
        )

    def test_the_generated_graph_discloses_progressively(self) -> None:
        module = importlib.import_module("my_context.assistant")
        tree = ContextTree.of(module.MyContextAssistant())

        card = tree.skeleton()["roles"][0]
        self.assertNotIn("instructions", card)

        opened = tree.open(card["ref"])
        self.assertNotIn("check-target", str(opened["skills"][0].get("instructions")))
        self.assertIn(
            "instructions",
            tree.open(f"{card['ref']}/check-target"),
        )

    def test_the_configured_root_resolves(self) -> None:
        role = resolve_target("my_context.assistant:MyContextAssistant")
        self.assertEqual(role.name, "my-context-assistant")

    def test_the_project_is_found_from_inside_it(self) -> None:
        found = find_project(self.root / "my_context" / "assistant")
        self.assertEqual(found, self.root.resolve())

    def test_the_generated_project_declares_no_build_system(self) -> None:
        """It is served, not distributed. A build system would imply otherwise."""

        text = (self.root / "pyproject.toml").read_text(encoding="utf-8")
        self.assertNotIn("[build-system]", text)
        self.assertIn("[tool.contexture]", text)
        self.assertIn('dependencies = ["contexture-mcp"]', text)

    def test_the_generated_project_has_no_entry_point_of_its_own(self) -> None:
        """The framework ships the runner; the project ships declarations."""

        text = (self.root / "pyproject.toml").read_text(encoding="utf-8")
        self.assertNotIn("[project.scripts]", text)
        self.assertEqual(list(self.root.rglob("__main__.py")), [])


class CommandLineTests(unittest.TestCase):
    """The command is exercised as a subprocess, the way a user runs it."""

    def _run(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "contexture.cli", *args],
            cwd=str(cwd or PROJECT_ROOT),
            capture_output=True,
            text=True,
            env={
                "PYTHONPATH": str(PROJECT_ROOT / "src"),
                "PATH": "/usr/bin:/bin",
            },
        )

    def test_new_then_list_works_without_the_sdk_installed(self) -> None:
        """Scaffolding must not require the MCP SDK; only `serve` does."""

        with tempfile.TemporaryDirectory() as directory:
            created = self._run("new", "my-context", cwd=Path(directory))
            self.assertEqual(created.returncode, 0, created.stderr)

            listed = self._run("list", cwd=Path(directory) / "my-context")
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertIn("my-context-assistant", listed.stdout)
            self.assertIn("check-target", listed.stdout)
            self.assertIn("read-only", listed.stdout)

    def test_list_outside_a_project_explains_what_to_do(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self._run("list", cwd=Path(directory))
            self.assertEqual(result.returncode, 2)
            self.assertIn("contexture new", result.stderr)

    def test_a_malformed_target_is_refused(self) -> None:
        result = self._run("list", "my_context.assistant")
        self.assertEqual(result.returncode, 2)
        self.assertIn("package.module:RoleClass", result.stderr)


class DemoTargetTests(unittest.TestCase):
    def test_the_bundled_demo_target_resolves(self) -> None:
        role = resolve_target(DEMO_TARGET)

        self.assertEqual(role.name, "kubernetes-platform")
        self.assertEqual(
            [child.name for child in role.children],
            ["incident-response", "deployment-ops"],
        )


if __name__ == "__main__":
    unittest.main()
