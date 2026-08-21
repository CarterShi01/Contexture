"""The business-facing Application declaration stays inert until compiled."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from contexture import Contexture, Role, Skill, Tool
from contexture.core.errors import ModelValidationError
from contexture.server import build_server, compile_application


SOURCE_ROOT = Path(__file__).resolve().parent.parent
_built = 0


class Hello(Tool):
    def __init__(self) -> None:
        global _built
        _built += 1
        super().__init__(name="hello", description="Say hello.", read_only=True)

    async def invoke(self) -> str:
        return "hello"


class Greeting(Skill):
    def __init__(self) -> None:
        super().__init__(
            name="greeting",
            description="Greet a caller.",
            instructions="Call hello.",
            uses=("root/hello",),
        )


class Root(Role):
    def __init__(self) -> None:
        super().__init__(
            name="root",
            description="The root role.",
            instructions="Greet callers.",
            skills=[Greeting()],
            tools=[Hello()],
        )


class ApplicationTests(unittest.TestCase):
    def test_a_declaration_stores_factories_without_constructing_them(self) -> None:
        global _built
        _built = 0
        roots = [Root]

        app = Contexture(name=" hello ", roots=roots)

        self.assertEqual(_built, 0)
        self.assertEqual(app.name, "hello")
        self.assertEqual(app.roots, (Root,))
        roots.clear()
        self.assertEqual(app.roots, (Root,))

    def test_a_root_must_be_a_node_class(self) -> None:
        with self.assertRaisesRegex(ModelValidationError, "already-built"):
            Contexture(name="hello", roots=(Root(),))

    def test_a_declaration_requires_a_name_and_a_root(self) -> None:
        with self.assertRaisesRegex(ModelValidationError, "non-empty"):
            Contexture(name=" ", roots=(Root,))
        with self.assertRaisesRegex(ModelValidationError, "at least one"):
            Contexture(name="hello", roots=())

    def test_importing_the_public_facade_and_declaring_an_app_loads_no_sdk(self) -> None:
        script = "\n".join(
            [
                "import sys",
                f"sys.path.insert(0, {str(SOURCE_ROOT)!r})",
                "from contexture import Contexture, Role",
                "class Root(Role):",
                "    def __init__(self):",
                "        super().__init__(name='root', description='Root.', instructions='Do work.')",
                "app = Contexture(name='hello', roots=(Root,))",
                "assert not any(name.split('.')[0] in {'mcp', 'mcp_types'} for name in sys.modules)",
            ]
        )
        subprocess.run([sys.executable, "-c", script], check=True)

    def test_each_compile_builds_a_fresh_forest_and_the_server_uses_it(self) -> None:
        global _built
        _built = 0
        app = Contexture(name="hello", roots=(Root,))

        first = compile_application(app)
        second = compile_application(app)

        self.assertIsNot(first.index.find("root"), second.index.find("root"))
        self.assertEqual(_built, 2)
        self.assertIs(build_server(app).index.roots[0].__class__, Root)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
