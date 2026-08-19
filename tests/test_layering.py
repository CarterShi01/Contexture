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
    "compiler": {"core"},
    "discovery": {"core", "compiler"},
    "targets": {"core", "compiler"},
    "protocol": {"core"},
    "execution": {"core", "compiler", "protocol"},
    "server": {"core", "compiler", "discovery"},
    # Reference applications sit above everything and are imported by nothing.
    "examples": {"core", "compiler", "discovery", "server"},
}

#: Layers permitted to import the official MCP SDK. The object model is not one
#: of them: `core` must stay describable without a wire protocol in the room.
SDK_LAYERS = frozenset({"server", "examples"})


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


class LayeringTests(unittest.TestCase):
    def test_every_module_belongs_to_a_known_layer(self) -> None:
        for path in sorted(PACKAGE.rglob("*.py")):
            if path.name == "__init__.py" and path.parent == PACKAGE:
                continue
            with self.subTest(module=str(path.relative_to(PACKAGE))):
                self.assertIn(_layer_of(path), ALLOWED)

    def test_no_layer_imports_one_above_it(self) -> None:
        for path in sorted(PACKAGE.rglob("*.py")):
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
            "and m.split('.')[1] in ('protocol', 'execution', 'targets', "
            "'server', 'discovery', 'examples')];"
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


class IOBoundaryTests(unittest.TestCase):
    """Only two modules may touch the outside world.

    Checks run over the parsed tree rather than the source text, because a
    substring search cannot tell `open(` from `urlopen(`.
    """

    FILESYSTEM_WRITERS = {"targets/writer.py"}
    NETWORK_MODULES = {"protocol/transport.py"}

    WRITE_CALLS = {"write_text", "write_bytes", "mkdir", "touch", "unlink"}
    NETWORK_PACKAGES = {"urllib", "socket", "http", "httpx", "requests", "aiohttp"}

    def test_only_the_writer_touches_the_filesystem(self) -> None:
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
        for path in sorted(PACKAGE.rglob("*.py"))
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
