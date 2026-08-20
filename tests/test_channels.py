"""What a capability reaches outside its own process, and how it got there.

A Tool is built by the declaration machinery and shared by every call in the
process, so it cannot hold a connection — it has to be handed one. These tests
check the whole path that hand-off travels: an application builds its
connections, registers its controllers against them, and a capability reached
through the wire finds the object the application built.

The in-process cases pin the mechanism. The stdio case pins the claim, because
a resource read and a tool call arrive through different SDK machinery and only
a real client exercises both.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
import os
import sys
import tempfile
import unittest
from pathlib import Path

from contexture import ControllerManager
from contexture.server import ContextureApp

# The suite is discovered with the project root as its top level, so a test
# module is imported under its bare name and a sibling fixture is not a
# package member. Both runners reach it the same way.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import channels_fixture as fixture  # noqa: E402

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:  # pragma: no cover - the SDK is a hard dependency
    ClientSession = None  # type: ignore[assignment]

SOURCE_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_MODULE = "tests.channels_fixture"
TIMEOUT_SECONDS = 30


def _run(work, *, marks: Path | None = None):
    async def session() -> object:
        environment = dict(os.environ)
        existing = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            f"{SOURCE_ROOT}{os.pathsep}{existing}" if existing else str(SOURCE_ROOT)
        )
        if marks is not None:
            environment["LIFECYCLE_MARKS"] = str(marks)
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", FIXTURE_MODULE],
            env=environment,
        )
        with open(os.devnull, "w", encoding="utf-8") as errlog:
            async with stdio_client(parameters, errlog=errlog) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.discover()
                    return await work(client)

    return asyncio.run(asyncio.wait_for(session(), TIMEOUT_SECONDS))


def _text(result) -> str:
    return "".join(
        block.text for block in result.content if getattr(block, "type", "") == "text"
    )


class HandOffTests(unittest.TestCase):
    """The mechanism, in process."""

    def test_a_capability_reaches_what_the_application_built(self) -> None:
        app = fixture.build()
        tool = app.manager.find(("operations", "escalation", "notify_squad"))
        self.assertIs(tool.channels, app.manager.channels)

        answer = asyncio.run(tool.invoke(squad="payments"))
        self.assertEqual(answer, "https://gateway.internal:notify:payments#1")

    def test_it_knows_its_own_address_too(self) -> None:
        """The other thing a shared instance cannot work out for itself."""

        app = fixture.build()
        tool = app.manager.find(("operations", "escalation", "where_am_i"))
        self.assertEqual(
            asyncio.run(tool.invoke()),
            "operations/escalation/where_am_i -> https://gateway.internal",
        )

    def test_two_apps_in_one_process_keep_their_own_connections(self) -> None:
        left, right = fixture.build(), fixture.build()
        left.manager.channels.gateway.endpoint = "https://left.internal"
        right.manager.channels.gateway.endpoint = "https://right.internal"

        left_tool = left.manager.find(("operations", "escalation", "where_am_i"))
        right_tool = right.manager.find(("operations", "escalation", "where_am_i"))

        self.assertIn("left.internal", asyncio.run(left_tool.invoke()))
        self.assertIn("right.internal", asyncio.run(right_tool.invoke()))

    def test_channels_may_be_handed_over_without_holding_a_registry(self) -> None:
        """The short door, for an application that never wanted one."""

        channels = fixture.Channels(
            gateway=fixture.Gateway(endpoint="https://short.internal"),
            catalogue={"runbook": "-"},
        )
        app = ContextureApp(roots=fixture.Operations(), channels=channels)
        tool = app.manager.find(("operations", "escalation", "notify_squad"))
        self.assertIs(tool.channels, channels)

    def test_a_manager_and_channels_together_are_refused(self) -> None:
        manager = ControllerManager(channels=object())
        manager.register(fixture.Operations)
        with self.assertRaises(Exception) as caught:
            ContextureApp(roots=manager, channels=object())
        self.assertIn("two answers", str(caught.exception))

    def test_nothing_outside_the_process_is_the_ordinary_case(self) -> None:
        app = ContextureApp(roots=fixture.Operations())
        self.assertIsNone(
            app.manager.find(("operations", "escalation", "notify_squad")).channels
        )


class LifecycleTests(unittest.TestCase):
    """Opening a handle that cannot simply be constructed, and closing it."""

    @staticmethod
    def _manager(marks: list[str], *, fail: bool = False) -> ControllerManager:
        @asynccontextmanager
        async def open_channels():
            marks.append("open")
            if fail:
                raise RuntimeError("gateway unreachable")
            try:
                yield fixture.Channels(
                    gateway=fixture.Gateway(endpoint="https://opened.internal"),
                    catalogue={"runbook": "-"},
                )
            finally:
                marks.append("close")

        manager = ControllerManager(provision=open_channels)
        manager.register(fixture.Operations)
        return manager

    def test_a_handle_is_open_only_while_it_is_being_served(self) -> None:
        marks: list[str] = []
        manager = self._manager(marks)
        tool = manager.find(("operations", "escalation", "notify_squad"))
        self.assertIsNone(tool.channels)

        async def serve() -> str:
            async with manager.provisioned():
                marks.append("serving")
                return await tool.invoke(squad="payments")

        answer = asyncio.run(serve())
        self.assertIn("https://opened.internal", answer)
        self.assertEqual(marks, ["open", "serving", "close"])
        # Cleared rather than left behind: a late call sees None, which fails
        # legibly, instead of a session somebody already closed.
        self.assertIsNone(tool.channels)

    def test_the_handle_is_closed_even_when_serving_raises(self) -> None:
        marks: list[str] = []
        manager = self._manager(marks)

        async def serve() -> None:
            async with manager.provisioned():
                raise RuntimeError("a request blew up")

        with self.assertRaises(RuntimeError):
            asyncio.run(serve())
        self.assertEqual(marks, ["open", "close"])
        self.assertIsNone(manager.channels)

    def test_a_handle_that_cannot_be_opened_stops_the_server_starting(self) -> None:
        marks: list[str] = []
        manager = self._manager(marks, fail=True)

        async def serve() -> None:
            async with manager.provisioned():
                marks.append("serving")

        with self.assertRaises(RuntimeError) as caught:
            asyncio.run(serve())
        self.assertIn("gateway unreachable", str(caught.exception))
        self.assertNotIn("serving", marks)

    def test_it_may_be_opened_again(self) -> None:
        """A factory, not a context manager, so a second run still works."""

        marks: list[str] = []
        manager = self._manager(marks)

        async def twice() -> None:
            for _ in range(2):
                async with manager.provisioned():
                    pass

        asyncio.run(twice())
        self.assertEqual(marks, ["open", "close", "open", "close"])

    def test_a_context_manager_instead_of_a_factory_is_refused(self) -> None:
        """And refused where it was written, not on the second run."""

        @asynccontextmanager
        async def open_channels():
            yield object()

        with self.assertRaises(Exception) as caught:
            ControllerManager(provision=open_channels())  # type: ignore[arg-type]
        self.assertIn("not a factory", str(caught.exception))

    def test_something_that_opens_nothing_is_refused(self) -> None:
        manager = ControllerManager(provision=lambda: object())
        manager.register(fixture.Operations)

        async def serve() -> None:
            async with manager.provisioned():
                pass

        with self.assertRaises(Exception) as caught:
            asyncio.run(serve())
        self.assertIn("not an async context manager", str(caught.exception))

    def test_a_value_and_a_way_to_open_one_together_are_refused(self) -> None:
        with self.assertRaises(Exception) as caught:
            ControllerManager(channels=object(), provision=lambda: None)
        self.assertIn("both channels and a way to open them", str(caught.exception))

    def test_a_manager_with_nothing_to_open_still_answers(self) -> None:
        """One shape for both kinds, so a caller need not ask which it holds."""

        channels = object()
        manager = ControllerManager(channels=channels)
        manager.register(fixture.Operations)

        async def serve() -> object:
            async with manager.provisioned() as opened:
                return opened

        self.assertIs(asyncio.run(serve()), channels)


@unittest.skipIf(ClientSession is None, "the MCP SDK is not installed")
class OverTheWireTests(unittest.TestCase):
    """The claim, through a real client and a real subprocess.

    A tool call and a resource read reach a capability through different SDK
    machinery — one carries a request context, the other is a bare function the
    SDK calls with no arguments at all. A hand-off that travelled with the
    request would work for one and not the other, and only this test can tell
    the difference.
    """

    def test_a_tool_call_reaches_the_gateway(self) -> None:
        async def work(client):
            return await client.call_tool(
                "contexture_invoke",
                {
                    "ref": "operations/escalation/notify_squad",
                    "arguments": {"squad": "payments"},
                },
            )

        self.assertIn("https://gateway.internal:notify:payments", _text(_run(work)))

    def test_a_resource_read_reaches_the_same_object(self) -> None:
        async def work(client):
            return await client.read_resource("contexture://runbooks/escalation")

        contents = _run(work).contents
        self.assertIn("Page the owner", contents[0].text)

    def test_an_opened_card_still_hides_the_hand_off(self) -> None:
        """`channels` is framework plumbing, not part of what a tool accepts.

        It is stamped onto the node rather than passed as a parameter, so it
        cannot reach a schema — but a card is what an agent calls against, so
        the claim is checked where an agent would meet it.
        """

        async def work(client):
            return await client.call_tool(
                "contexture_open", {"ref": "operations/escalation"}
            )

        payload = json.loads(_text(_run(work)))
        for card in payload["tools"]:
            self.assertNotIn("channels", json.dumps(card))
            self.assertNotIn("path", card["input_schema"].get("properties", {}))


@unittest.skipIf(ClientSession is None, "the MCP SDK is not installed")
class LifecycleOverTheWireTests(unittest.TestCase):
    """Opening and closing, observed from outside the process that does it.

    In-process cases can show that `provisioned()` opens and closes. Only a
    subprocess can show *when* — that opening happened before the server was
    able to answer anything, and that closing happened at all rather than being
    skipped by a process that simply exited.
    """

    def test_it_opens_before_serving_and_closes_after(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marks = Path(directory) / "marks.txt"

            async def work(client):
                return await client.call_tool(
                    "contexture_invoke",
                    {
                        "ref": "operations/escalation/notify_squad",
                        "arguments": {"squad": "payments"},
                    },
                )

            answer = _text(_run(work, marks=marks))
            steps = marks.read_text(encoding="utf-8").split()

        # The call reached a gateway that only exists between these two marks.
        self.assertIn("https://gateway.internal:notify:payments", answer)
        self.assertEqual(steps, ["open", "close"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
