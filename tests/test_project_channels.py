"""A project with downstream connections, served by `contexture serve`.

Until now this was the one shape the command line could not serve. `channels`
is a live object; a TOML table holds strings; and so a project that talked to
anything had to write the entry point the README opens by promising it will not
need. That was HANDOFF item A's open question.

**What closed it was ADR 015, not a new mechanism.** `provision` was a function
returning an async context manager, and nothing in this package turns a named
function into a live object. `Channels` is a *class*, and "a class is a
zero-argument factory" is the rule `roots` has used since ADR 013. So the
project table learned one key and no new machinery.

The downstream here is a dictionary behind an async context manager. What is
being tested is that the handle reaches a capability, opened, before the first
request — a real socket would only add a second thing that can fail.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from contexture.cli import UsageError
from contexture.cli.project import ProjectConfig, load_channels

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: A handle whose constructor takes no arguments and whose connection happens
#: in `open` — the shape the project table can name.
CHANNELS = '''
from contextlib import asynccontextmanager
import os

from contexture import Channels

OPENED = []


@asynccontextmanager
async def connect(url):
    OPENED.append(url)
    try:
        yield {"url": url, "pods": ["api-7d9f", "worker-2c1a"]}
    finally:
        OPENED.append("closed")


class ClusterChannels(Channels):
    def __init__(self) -> None:
        self.url = os.environ.get("CLUSTER_URL", "https://cluster.internal")
        self.session = None

    async def open(self) -> None:
        self.session = await self.enter(connect(self.url))

    async def close(self) -> None:
        self.session = None
'''

ROLE = '''
from contexture import Role, Tool


class ListPods(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="list_pods",
            description="List the pods this server can see.",
            read_only=True,
        )

    async def invoke(self) -> str:
        return f"{self.channels.url}: {', '.join(self.channels.session['pods'])}"


class Operations(Role):
    def __init__(self) -> None:
        super().__init__(
            name="operations",
            description="Operate a cluster this process does not own.",
            instructions="Read before you write.",
            tools=[ListPods()],
        )
'''

PYPROJECT = '''
[tool.uv]
package = false

[tool.contexture]
name = "connected"
roots = ["ops:Operations"]
channels = "ops.channels:ClusterChannels"
'''


def _write_project(directory: str) -> Path:
    root = Path(directory)
    (root / "ops").mkdir()
    (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (root / "ops" / "__init__.py").write_text(ROLE, encoding="utf-8")
    (root / "ops" / "channels.py").write_text(CHANNELS, encoding="utf-8")
    return root


class ConfigTests(unittest.TestCase):
    def test_an_application_target_is_the_complete_project_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _write_project(directory)
            (root / "pyproject.toml").write_text(
                "[tool.contexture]\napp = \"ops:app\"\n", encoding="utf-8"
            )
            config = ProjectConfig.load(root)

        self.assertEqual(config.app, "ops:app")
        self.assertEqual(config.roots, ())

    def test_an_application_target_cannot_mix_with_legacy_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _write_project(directory)
            (root / "pyproject.toml").write_text(
                "[tool.contexture]\napp = \"ops:app\"\nroots = [\"ops:Operations\"]\n",
                encoding="utf-8",
            )
            with self.assertRaises(UsageError) as caught:
                ProjectConfig.load(root)

        self.assertIn("both `app` and legacy", str(caught.exception))

    def test_the_table_carries_one_channels_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = ProjectConfig.load(_write_project(directory))

        self.assertEqual(config.channels, "ops.channels:ClusterChannels")

    def test_a_project_that_reaches_nothing_says_nothing(self) -> None:
        """The ordinary case stays the ordinary case: the key is optional."""

        with tempfile.TemporaryDirectory() as directory:
            root = _write_project(directory)
            (root / "pyproject.toml").write_text(
                PYPROJECT.replace(
                    'channels = "ops.channels:ClusterChannels"\n', ""
                ),
                encoding="utf-8",
            )
            config = ProjectConfig.load(root)

        self.assertIsNone(config.channels)
        self.assertIsNone(load_channels(config.channels))

    def test_two_handles_are_refused_where_they_are_written(self) -> None:
        """One manager, one handle — two would be two answers."""

        with tempfile.TemporaryDirectory() as directory:
            root = _write_project(directory)
            (root / "pyproject.toml").write_text(
                PYPROJECT.replace(
                    'channels = "ops.channels:ClusterChannels"',
                    'channels = ["a:A", "b:B"]',
                ),
                encoding="utf-8",
            )
            with self.assertRaises(UsageError) as caught:
                ProjectConfig.load(root)

        self.assertIn("one handle", str(caught.exception).replace("\n", " "))

    def test_a_role_under_channels_is_refused(self) -> None:
        """A `roots` entry written under the wrong key.

        Building it here would give every capability in the project a second,
        never-registered controller to reach for.
        """

        with self.assertRaises(UsageError) as caught:
            load_channels("contexture.demo:KubernetesPlatform")

        self.assertIn("belongs in `roots`", str(caught.exception))


class ResolutionTests(unittest.TestCase):
    def test_naming_a_class_builds_it(self) -> None:
        """The whole trick: a class is a zero-argument factory (ADR 013).

        A live handle cannot be written into a TOML table. A class can be
        named, and this is the same door `roots` goes through.
        """

        with tempfile.TemporaryDirectory() as directory:
            root = _write_project(directory)
            sys.path.append(str(root))
            self.addCleanup(lambda: sys.path.remove(str(root)))
            self.addCleanup(
                lambda: [
                    sys.modules.pop(name, None)
                    for name in ("ops", "ops.channels")
                ]
            )

            built = load_channels("ops.channels:ClusterChannels", project=root)

        self.assertEqual(type(built).__name__, "ClusterChannels")
        # Constructed, not connected: `open` is what dials, and it has not run.
        self.assertIsNone(built.session)


class OverTheWireTests(unittest.TestCase):
    """`contexture serve`, on a project with a connection, through a client.

    In a subprocess and over a real stdio wire, because the claim is about the
    command line: that a project with downstream connections needs no
    hand-written entry point. Nothing in process can show that.
    """

    def test_a_declared_handle_is_open_before_the_first_request(self) -> None:
        script = textwrap.dedent(
            """
            import asyncio, os, sys
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            async def main():
                env = dict(os.environ,
                           PYTHONPATH=os.pathsep.join(sys.argv[1:3]),
                           CLUSTER_URL="https://staging.internal")
                params = StdioServerParameters(
                    command=sys.executable,
                    args=["-m", "contexture.cli", "serve"],
                    env=env,
                    cwd=sys.argv[2],
                )
                async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
                    await s.initialize()
                    got = await s.call_tool(
                        "contexture_invoke_read_only",
                        {"ref": "operations/list_pods"},
                    )
                    print(got.content[0].text)

            asyncio.run(main())
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            root = _write_project(directory)
            finished = subprocess.run(
                [sys.executable, "-c", script, str(PROJECT_ROOT), str(root)],
                capture_output=True,
                text=True,
                timeout=90,
            )

        self.assertEqual(finished.returncode, 0, finished.stderr[-2000:])
        # The URL proves the constructor ran and read the environment; the pod
        # names prove `open` ran and its session reached the capability.
        self.assertIn(
            "https://staging.internal: api-7d9f, worker-2c1a", finished.stdout
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
