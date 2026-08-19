"""Tests that the package layering is real and not merely documented.

The architecture claims each layer may import the ones below it and never the
reverse. A claim like that decays silently — one convenient import inside
`core` and the whole shape is gone with nothing failing. These tests are what
make it fail.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parent.parent / "src"
PACKAGE = SOURCE_ROOT / "contexture"

#: Layer name -> the layers it is allowed to import from.
ALLOWED: dict[str, set[str]] = {
    "core": set(),
    "tree": {"core"},
    "server": {"core", "tree"},
    # Reference applications sit above everything and are imported by nothing.
    # They reach the object model through the public facade, not by layer, so
    # `server` is the only sibling layer they may name. See
    # LayeringTests.test_examples_use_only_the_public_facade.
    "examples": {"server"},
    # The command line sits above everything: it scaffolds, then serves.
    "cli": {"core", "tree", "server"},
}

#: Layers permitted to import the official MCP SDK. The object model is not one
#: of them: `core` must stay describable without a wire protocol in the room.
SDK_LAYERS = frozenset({"server", "examples"})


#: Package data that ships in the wheel but is never imported. A project
#: template contains `.py` files on purpose: they are what a generated project
#: starts from, and they belong to no layer of this one.
DATA_DIRECTORIES = frozenset({"templates"})


def _source_modules(root: Path) -> list[Path]:
    return [
        path
        for path in sorted(root.rglob("*.py"))
        if not (set(path.relative_to(PACKAGE).parts) & DATA_DIRECTORIES)
    ]


def _layer_of(path: Path) -> str:
    relative = path.relative_to(PACKAGE)
    head = relative.parts[0]
    if head.endswith(".py"):
        return head[: -len(".py")]
    return head


def _imported_layers(path: Path) -> set[str]:
    """Return the sibling layers a module imports, resolving relative imports."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    depth_to_package = len(path.relative_to(PACKAGE).parts) - 1
    found: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module and node.module.startswith("contexture."):
                    found.add(node.module.split(".")[1])
                continue
            # `from ..core.errors import X` inside core/role.py means level 2
            # from a depth-1 module, i.e. the package root.
            if node.level > depth_to_package and node.module:
                found.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("contexture."):
                    found.add(alias.name.split(".")[1])

    return found


def _contexture_imports(path: Path) -> set[str]:
    """Return every `contexture`-rooted module a file imports, absolute or not."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                found.add("." * node.level + (node.module or ""))
            elif node.module == "contexture" or (
                node.module or ""
            ).startswith("contexture."):
                found.add(node.module or "")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "contexture" or alias.name.startswith("contexture."):
                    found.add(alias.name)
    return found


class LayeringTests(unittest.TestCase):
    def test_every_module_belongs_to_a_known_layer(self) -> None:
        for path in _source_modules(PACKAGE):
            if path.name == "__init__.py" and path.parent == PACKAGE:
                continue
            with self.subTest(module=str(path.relative_to(PACKAGE))):
                self.assertIn(_layer_of(path), ALLOWED)

    def test_no_layer_imports_one_above_it(self) -> None:
        for path in _source_modules(PACKAGE):
            if path.name == "__init__.py" and path.parent == PACKAGE:
                continue  # the facade is allowed to reach every layer
            layer = _layer_of(path)
            permitted = ALLOWED[layer] | {layer}
            for imported in _imported_layers(path):
                with self.subTest(module=str(path.relative_to(PACKAGE))):
                    self.assertIn(
                        imported,
                        permitted,
                        f"{layer} must not import {imported}",
                    )

    def test_only_the_server_layer_imports_the_mcp_sdk(self) -> None:
        """The framework claim, checked rather than asserted in prose.

        Business code declares roles and capabilities; the SDK appears only
        where declarations are projected onto the wire. If `core` ever imports
        `mcp`, the object model has quietly become a protocol binding.
        """

        for path, relative, tree in _modules():
            if _layer_of(path) in SDK_LAYERS:
                continue
            with self.subTest(module=relative):
                self.assertNotIn("mcp", _imported_packages(tree))
                self.assertNotIn("mcp_types", _imported_packages(tree))

    def test_importing_core_loads_no_upper_layer(self) -> None:
        """The strongest form of the claim: check it at runtime, not in the AST."""

        script = (
            "import sys; sys.path.insert(0, %r);"
            "import contexture.core;"
            "upper = [m for m in sys.modules if m.startswith('contexture.') "
            "and m.split('.')[1] in ('server', 'tree', 'examples')];"
            "print(','.join(sorted(upper)))" % str(SOURCE_ROOT)
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(
            result.stdout.strip(),
            "",
            "importing contexture.core pulled in an upper layer",
        )

    def test_importing_core_does_not_load_the_mcp_sdk(self) -> None:
        """A project that only models context should not pay for a transport."""

        script = (
            "import sys; sys.path.insert(0, %r);"
            "import contexture.core;"
            "print(','.join(sorted(m for m in sys.modules "
            "if m == 'mcp' or m.startswith('mcp.'))))" % str(SOURCE_ROOT)
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(result.stdout.strip(), "")


    def test_examples_use_only_the_public_facade(self) -> None:
        """A reference application must be copy-pasteable out of this package.

        Reaching into `contexture.core.*` would make the example unusable as a
        starting point — a copied directory cannot resolve a relative import
        beyond its own top level — and would quietly contradict the claim these
        files make about themselves.
        """

        allowed = {"contexture", "contexture.server"}
        for path in _source_modules(PACKAGE / "examples"):
            with self.subTest(module=str(path.relative_to(PACKAGE))):
                for imported in _contexture_imports(path):
                    if imported.startswith("."):
                        # A relative import must stay inside the example itself.
                        self.assertEqual(
                            imported.count("."),
                            1,
                            f"{path.name} reaches outside the example with "
                            f"{imported!r}; use the public facade instead.",
                        )
                        continue
                    self.assertIn(
                        imported,
                        allowed,
                        f"{path.name} imports {imported!r}; examples may only "
                        f"use {sorted(allowed)}.",
                    )


class IOBoundaryTests(unittest.TestCase):
    """Only the scaffold may write, and nothing may reach the network.

    One module in the whole package touches the filesystem, and it is the one
    that writes a project *for the user*. Nothing on the path from a
    declaration to the wire opens a file, which is why the boundary is worth
    checking rather than assuming.

    Checks run over the parsed tree rather than the source text, because a
    substring search cannot tell `open(` from `urlopen(`.
    """

    FILESYSTEM_WRITERS = {"cli.py"}
    NETWORK_MODULES: set[str] = set()

    WRITE_CALLS = {"write_text", "write_bytes", "mkdir", "touch", "unlink"}
    NETWORK_PACKAGES = {"urllib", "socket", "http", "httpx", "requests", "aiohttp"}

    def test_only_the_scaffold_touches_the_filesystem(self) -> None:
        for path, relative, tree in _modules():
            if relative in self.FILESYSTEM_WRITERS:
                continue
            with self.subTest(module=relative):
                self.assertEqual(_filesystem_calls(tree), set())

    def test_only_the_transport_reaches_the_network(self) -> None:
        for path, relative, tree in _modules():
            if relative in self.NETWORK_MODULES:
                continue
            with self.subTest(module=relative):
                self.assertEqual(
                    _imported_packages(tree) & self.NETWORK_PACKAGES,
                    set(),
                )


def _modules() -> list[tuple[Path, str, ast.Module]]:
    return [
        (
            path,
            path.relative_to(PACKAGE).as_posix(),
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path)),
        )
        for path in _source_modules(PACKAGE)
    ]


def _filesystem_calls(tree: ast.Module) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "open":
            found.add("open")
        elif (
            isinstance(func, ast.Attribute)
            and func.attr in IOBoundaryTests.WRITE_CALLS
        ):
            found.add(func.attr)
    return found


def _imported_packages(tree: ast.Module) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found
