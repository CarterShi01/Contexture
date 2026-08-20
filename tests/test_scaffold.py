"""Tests for the scaffold: what `contexture new` writes, and whether it runs.

The point of a template is that a copy of it works. So these tests render one
into a temporary directory and then use it the way a user would — import the
declarations, list the graph, execute a tool — rather than asserting on the
template text.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
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
    load_roots,
    new_project,
    resolve_target,
)
from contexture.core.model.tree import ContextTree
from contexture.core.mcp_interface import Resource
from contexture.core.model.manager import ControllerManager

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class NameDerivationTests(unittest.TestCase):
    def test_one_argument_derives_every_name(self) -> None:
        names = Names.derive("My Context")
        self.assertEqual(names.project_name, "my-context")
        self.assertEqual(names.role_class, "MyContextAssistant")
        self.assertEqual(names.resource_scheme, "my-context")

    def test_punctuation_collapses_to_one_separator(self) -> None:
        self.assertEqual(Names.derive("k8s__ops!!team").project_name, "k8s-ops-team")

    def test_a_leading_digit_is_refused_with_a_reason(self) -> None:
        with self.assertRaises(UsageError) as caught:
            Names.derive("9lives")
        self.assertIn("Python identifier", str(caught.exception))

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

    def test_a_role_package_sits_at_the_project_root(self) -> None:
        """There is no package wrapping the packages.

        A Django project nests one because its outer directory holds a config
        package *and* every app; here the configuration is the
        `[tool.contexture]` table, so the outer directory holds roles and
        nothing else. Each root is a top-level package, the way an app is.
        """

        with tempfile.TemporaryDirectory() as directory:
            root = new_project("my-context", destination=Path(directory))
            self.assertTrue((root / "assistant" / "role.py").is_file())
            self.assertTrue((root / "publish.py").is_file())
            self.assertFalse((root / "my_context").exists())
            self.assertFalse((root / "module").exists())
            self.assertFalse((root / "__init__.py").exists())

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
        for name in [
            m for m in sys.modules if m.split(".")[0] in ("assistant", "publish")
        ]:
            del sys.modules[name]

    def test_the_generated_role_imports_and_declares_every_kind(self) -> None:
        module = importlib.import_module("assistant")
        role = ControllerManager().register_role(module.MyContextAssistant)

        self.assertIsInstance(role, Role)
        self.assertEqual(role.name, "my-context-assistant")
        self.assertEqual([s.name for s in role.skills], ["check-target"])
        self.assertEqual(
            sorted(t.name for t in role.tools), ["health_runbook", "ping"]
        )

    def test_the_generated_tools_execute(self) -> None:
        module = importlib.import_module("assistant")
        role = ControllerManager().register_role(module.MyContextAssistant)
        by_name = {tool.name: tool for tool in role.tools}

        result = asyncio.run(by_name["ping"].invoke(target="payments-api"))
        self.assertIn("payments-api", result)
        self.assertIn("reachable", asyncio.run(by_name["health_runbook"].invoke()))

    def test_the_generated_project_publishes_the_runbook(self) -> None:
        """The scaffold shows both planes: a tool to navigate to, and a URI."""

        (declared,) = importlib.import_module("publish").PUBLISHED
        published = declared()
        self.assertEqual(published.uri, "my-context://runbooks/health")
        self.assertEqual(
            published.opens, "my-context-assistant/health_runbook"
        )

    def test_the_generated_graph_discloses_progressively(self) -> None:
        module = importlib.import_module("assistant")
        tree = ContextTree.of(module.MyContextAssistant)

        card = tree.skeleton()["roles"][0]
        self.assertNotIn("instructions", card)

        opened = tree.open(card["ref"])
        self.assertNotIn("check-target", str(opened["skills"][0].get("instructions")))
        self.assertIn(
            "instructions",
            tree.open(f"{card['ref']}/check-target"),
        )

    def test_the_configured_root_resolves(self) -> None:
        """It resolves to the class; a manager is what turns one into nodes."""

        declared = resolve_target("assistant:MyContextAssistant")
        self.assertTrue(issubclass(declared, Role))
        self.assertEqual(
            ControllerManager().register_role(declared).name,
            "my-context-assistant",
        )

    def test_the_project_is_found_from_inside_it(self) -> None:
        found = find_project(self.root / "assistant")
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
                "PYTHONPATH": str(PROJECT_ROOT),
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
        result = self._run("list", "assistant.role")
        self.assertEqual(result.returncode, 2)
        self.assertIn("package.module:RoleClass", result.stderr)


class DemoTargetTests(unittest.TestCase):
    def test_the_bundled_demo_target_resolves(self) -> None:
        role = ControllerManager().register_role(resolve_target(DEMO_TARGET))

        self.assertEqual(role.name, "kubernetes-platform")
        self.assertEqual(
            [child.name for child in role.children],
            ["incident-response", "deployment-ops"],
        )


if __name__ == "__main__":
    unittest.main()


class ProjectPathTests(unittest.TestCase):
    """A project directory goes on the *end* of `sys.path`, never the front.

    The directory that goes on the path is the one holding `pyproject.toml`,
    so whatever else its author put beside that file becomes importable too.
    A project file called `colorsys.py` or `logging.py` is therefore a
    candidate to answer for the standard library's module of that name.

    **What this does and does not protect.** By the time roots are loaded, the
    command line has already imported what it needs, so a stdlib module
    already in `sys.modules` cannot be displaced whichever end is used. What
    is still open is every import that has *not* happened yet: a lazy import
    inside the SDK, or one inside a tool body that runs at request time on a
    server that stays up for hours. Appending closes that, and its cost — a
    project module sharing a name with something installed becomes unreachable
    — is what `_require_declared_here` turns into a sentence.
    """

    def _project_with(self, filename: str, body: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = new_project("my-context", destination=Path(directory.name))
        (root / filename).write_text(body, encoding="utf-8")
        self.addCleanup(
            lambda: [
                sys.modules.pop(name, None)
                for name in ("assistant", "assistant.role", "colorsys")
            ]
        )
        self.addCleanup(
            lambda: sys.path.remove(str(root)) if str(root) in sys.path else None
        )
        return root

    def test_a_project_module_cannot_answer_for_a_later_standard_library_import(
        self,
    ) -> None:
        """`colorsys` is chosen because nothing above has imported it yet.

        That is the whole scenario: the module a long-running server reaches
        for after it has already loaded somebody's declarations.
        """

        root = self._project_with(
            "colorsys.py", '"""Domain colours."""\nBRAND = "#ff0000"\n'
        )
        sys.modules.pop("colorsys", None)

        load_roots(["assistant:MyContextAssistant"], project=root)
        import colorsys

        self.assertTrue(hasattr(colorsys, "rgb_to_hls"))
        self.assertNotEqual(Path(colorsys.__file__).parent, root)

    def test_a_root_resolving_outside_the_project_is_refused_by_name(self) -> None:
        """The cost of appending, made loud.

        `json` is importable everywhere, so a project module by that name is
        unreachable once the project sits behind the standard library. Serving
        somebody else's module without a word is the failure worth refusing.
        """

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            with self.assertRaises(UsageError) as caught:
                resolve_target("json:JSONEncoder", project=project)

            message = str(caught.exception)
            self.assertIn("outside this project", message)
            self.assertIn("json", message)


class InspectFallbackTests(unittest.TestCase):
    """With no project in sight, `inspect` replays the bundled demo.

    This is what let `tools/inspect_disclosure.py` be deleted. That file was a
    45-line `sys.path` shim carrying a 171-line README, and the only thing in
    it that was not boilerplate was this default — the framework's own checkout
    has no `[tool.contexture]` project, so a contributor had nothing to inspect
    without one. Making the command itself answer serves the contributor and
    the reader who has just installed the package, with one behaviour instead
    of two entry points.

    `serve` deliberately does not do this. Printing something nobody asked for
    is recoverable; starting a server nobody asked for is a different kind of
    surprise.
    """

    def _run(self, *args: str, cwd: Path) -> subprocess.CompletedProcess:
        # The whole environment, unlike `CommandLineTests`, which strips it on
        # purpose to prove `list` needs no SDK. These commands do need one, and
        # on Windows a subprocess without `SystemRoot` cannot initialise
        # Winsock — which the SDK's imports reach before any of this runs.
        return subprocess.run(
            [sys.executable, "-m", "contexture.cli", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
        )

    def test_outside_a_project_inspect_replays_the_demo_and_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self._run("inspect", "--summary", cwd=Path(directory))

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("bundled demo", result.stderr)
            self.assertIn("session start", result.stdout)

    def test_the_notice_stays_off_stdout_so_json_remains_a_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self._run("inspect", "--json", cwd=Path(directory))

            self.assertEqual(result.returncode, 0, result.stderr)
            json.loads(result.stdout)

    def test_outside_a_project_serve_still_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self._run("serve", cwd=Path(directory))

            self.assertEqual(result.returncode, 2)
            self.assertIn("contexture new", result.stderr)
