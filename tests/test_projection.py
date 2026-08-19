"""Tests for the gateway surface.

The surface is five tools whatever the declaration holds, business
capabilities never appear on it, and the read-only classification survives as
which entry point was used rather than as an argument a model could fill in.
"""

from __future__ import annotations

import asyncio
import json
import re
import unittest

from mcp.server.mcpserver.exceptions import ToolError

from contexture.core.resources import Resource
from contexture.core.role import Role
from contexture.core.skill import Skill
from contexture.core.tools import Tool
from mcp.server.mcpserver import Context
from contexture.server import instructions
from contexture.tree import SEPARATOR, ContextTree
from contexture.server import (
    DISCOVER_TOOL,
    Launch,
    GATEWAY_TOOLS,
    INVOKE_READ_ONLY_TOOL,
    INVOKE_TOOL,
    OPEN_TOOL,
    READ_TOOL,
    ContextureApp,
    claude_code_config,
    cli_commands,
    codex_config,
)

PROCEDURE = "Read the status, then the logs."


class GetPodLogs(Tool):
    """Return the recent container logs for a Pod."""

    name = "get_pod_logs"
    read_only = True

    async def invoke(self, namespace: str, pod: str, previous: bool = False) -> str:
        return f"{namespace}/{pod} previous={previous}"


class DeletePod(Tool):
    """Delete a Pod so its controller recreates it."""

    name = "delete_pod"

    async def invoke(self, namespace: str, pod: str) -> str:
        return f"deleted {namespace}/{pod}"


class Runbook(Resource):
    """How to diagnose a container that keeps restarting."""

    uri = "contexture://runbooks/crash-loop"
    mime_type = "text/markdown"

    async def read(self) -> str:
        return "RUNBOOK-BODY"


class Diagnose(Skill):
    """Find why a Pod restarts repeatedly."""

    name = "diagnose"
    instructions = PROCEDURE


class Responder(Role):
    """Diagnose and repair unhealthy Pods."""

    instructions = "Inspect before changing anything."

    diagnose = Diagnose
    logs = GetPodLogs
    remove = DeletePod
    runbook = Runbook


def _server():
    return ContextureApp(roots=Responder(), name="test").build_server()


def _call(server, name, arguments=None):
    return asyncio.run(server.call_tool(name, arguments or {}))


def _text(result):
    return result.content[0].text


class SurfaceTests(unittest.TestCase):
    def test_the_surface_is_the_five_gateway_tools_and_nothing_else(self) -> None:
        server = _server()

        listed = tuple(tool.name for tool in asyncio.run(server.list_tools()))
        self.assertEqual(listed, GATEWAY_TOOLS)

    def test_no_business_capability_reaches_the_surface(self) -> None:
        """A registered capability is one every session pays for, forever."""

        server = _server()

        rendered = json.dumps(
            [tool.model_dump(mode="json") for tool in asyncio.run(server.list_tools())]
        )
        self.assertNotIn("get_pod_logs", rendered)
        self.assertNotIn("delete_pod", rendered)
        self.assertNotIn(PROCEDURE, rendered)

        resources = asyncio.run(server.list_resources())
        self.assertEqual(resources, [])

    def test_only_the_writing_door_is_free_of_the_read_only_hint(self) -> None:
        server = _server()
        hints = {
            tool.name: tool.annotations and tool.annotations.read_only_hint
            for tool in asyncio.run(server.list_tools())
        }

        self.assertEqual(hints[INVOKE_TOOL], False)
        for name in (DISCOVER_TOOL, OPEN_TOOL, READ_TOOL, INVOKE_READ_ONLY_TOOL):
            with self.subTest(tool=name):
                self.assertTrue(hints[name])

    def test_read_only_is_never_an_argument(self) -> None:
        """A model that could pass its own approval flag would be approving
        its own writes."""

        server = _server()
        for tool in asyncio.run(server.list_tools()):
            with self.subTest(tool=tool.name):
                self.assertNotIn(
                    "read_only", tool.input_schema.get("properties", {})
                )

    def test_the_instructions_carry_the_role_roster(self) -> None:
        """A gateway whose five tool names all begin `contexture_` gives a host
        nothing to go on until the roster tells it what this server is for."""

        server = _server()

        self.assertIn("responder", server.instructions)
        self.assertIn("Diagnose and repair unhealthy Pods.", server.instructions)
        self.assertNotIn(PROCEDURE, server.instructions)


class NavigationTests(unittest.TestCase):
    def test_discover_returns_the_skeleton(self) -> None:
        server = _server()

        payload = json.loads(_text(_call(server, DISCOVER_TOOL)))
        self.assertEqual([card["ref"] for card in payload["roles"]], ["responder"])

    def test_opening_a_role_delivers_the_schemas_the_surface_no_longer_has(
        self,
    ) -> None:
        server = _server()

        opened = json.loads(_text(_call(server, OPEN_TOOL, {"ref": "responder"})))
        schemas = {tool["name"]: tool["input_schema"] for tool in opened["tools"]}
        self.assertEqual(
            sorted(schemas["get_pod_logs"]["properties"]),
            ["namespace", "pod", "previous"],
        )
        self.assertEqual(schemas["get_pod_logs"]["required"], ["namespace", "pod"])

    def test_a_wrong_ref_is_a_sentence_and_not_a_traceback(self) -> None:
        server = _server()

        with self.assertRaises(ToolError) as caught:
            _call(server, OPEN_TOOL, {"ref": "responder/banana"})

        message = str(caught.exception)
        self.assertIn("banana", message)
        self.assertIn("get_pod_logs", message)


class InvocationTests(unittest.TestCase):
    def test_a_read_only_tool_runs_through_the_read_only_door(self) -> None:
        server = _server()

        result = _call(
            server,
            INVOKE_READ_ONLY_TOOL,
            {"ref": "responder/get_pod_logs",
             "arguments": {"namespace": "prod", "pod": "api"}},
        )
        self.assertIn("prod/api", _text(result))

    def test_a_writing_tool_runs_through_the_writing_door(self) -> None:
        server = _server()

        result = _call(
            server,
            INVOKE_TOOL,
            {"ref": "responder/delete_pod",
             "arguments": {"namespace": "prod", "pod": "api"}},
        )
        self.assertIn("deleted prod/api", _text(result))

    def test_a_write_sent_through_the_read_only_door_is_refused(self) -> None:
        """The host decided whether to involve a human from the door's hint.

        Honouring a mismatch would run a write under a read-only approval.
        """

        server = _server()

        with self.assertRaises(ToolError) as caught:
            _call(
                server,
                INVOKE_READ_ONLY_TOOL,
                {"ref": "responder/delete_pod",
                 "arguments": {"namespace": "prod", "pod": "api"}},
            )

        message = str(caught.exception)
        self.assertIn("not read-only", message)
        self.assertIn(INVOKE_TOOL, message)

    def test_a_read_sent_through_the_writing_door_is_refused(self) -> None:
        server = _server()

        with self.assertRaises(ToolError) as caught:
            _call(
                server,
                INVOKE_TOOL,
                {"ref": "responder/get_pod_logs",
                 "arguments": {"namespace": "prod", "pod": "api"}},
            )

        self.assertIn(INVOKE_READ_ONLY_TOOL, str(caught.exception))

    def test_arguments_are_validated_against_the_derived_schema(self) -> None:
        """Validation left the wire with the tool; it did not stop happening."""

        server = _server()

        with self.assertRaises(ToolError) as caught:
            _call(
                server,
                INVOKE_READ_ONLY_TOOL,
                {"ref": "responder/get_pod_logs", "arguments": {"namespace": "prod"}},
            )

        self.assertIn("pod", str(caught.exception))

    def test_a_ref_that_names_a_skill_is_refused_by_invoke(self) -> None:
        server = _server()

        with self.assertRaises(ToolError) as caught:
            _call(server, INVOKE_READ_ONLY_TOOL, {"ref": "responder/diagnose"})

        self.assertIn("skill", str(caught.exception))


class ResourceTests(unittest.TestCase):
    def test_content_arrives_only_when_it_is_read(self) -> None:
        server = _server()

        opened = json.loads(
            _text(_call(server, OPEN_TOOL, {"ref": "responder/runbook"}))
        )
        self.assertNotIn("RUNBOOK-BODY", json.dumps(opened))
        self.assertIn(
            "RUNBOOK-BODY",
            _text(_call(server, READ_TOOL, {"ref": "responder/runbook"})),
        )

    def test_a_resource_reads_by_its_own_uri_as_well_as_by_ref(self) -> None:
        server = _server()

        result = _call(
            server, READ_TOOL, {"ref": "contexture://runbooks/crash-loop"}
        )
        self.assertIn("RUNBOOK-BODY", _text(result))


class RegistrationTests(unittest.TestCase):
    """Host config now points at the server instead of replacing it."""

    LAUNCH = Launch(
        name="contexture-demo",
        command="uv",
        args=("run", "contexture", "serve"),
    )

    def test_claude_code_config_is_a_launch_command_not_a_context_file(self) -> None:
        import json

        config = json.loads(claude_code_config(self.LAUNCH))
        entry = config["mcpServers"]["contexture-demo"]

        self.assertEqual(entry["type"], "stdio")
        self.assertEqual(entry["command"], "uv")
        self.assertEqual(entry["args"], ["run", "contexture", "serve"])

    def test_codex_config_stanza_quotes_its_command(self) -> None:
        stanza = codex_config(self.LAUNCH)

        self.assertIn("[mcp_servers.contexture-demo]", stanza)
        self.assertIn('command = "uv"', stanza)
        self.assertIn('args = ["run", "contexture", "serve"]', stanza)

    def test_both_hosts_are_given_the_same_launch_command(self) -> None:
        """The claim under test: one server, two hosts, one command."""

        commands = cli_commands(self.LAUNCH)
        suffix = "-- uv run contexture serve"

        self.assertTrue(commands["claude-code"].endswith(suffix))
        self.assertTrue(commands["codex"].endswith(suffix))
        # Claude Code defaults to local scope; a shared file needs it named.
        self.assertIn("--scope project", commands["claude-code"])


class StatelessnessTests(unittest.TestCase):
    """The gateway must answer out of the declaration and nothing else.

    Since the 2026-07-28 revision a server may not vary its surface per
    connection or as a consequence of an earlier call, and Contexture's whole
    navigation model rests on that: a `ref` is an address, not a cursor. Both
    properties hold today because nobody has written state into a gateway
    function. These tests are what makes writing some fail — a cache of "the
    role opened last", added to save tokens, would read as a reasonable
    optimization and would quietly put this server out of specification.

    Every assertion here compares a server that has done work against a server
    that has done none. Comparing two exercised servers to each other is the
    trap: a cache that degrades an answer after its first delivery poisons both
    snapshots equally, and the comparison passes while the server is already
    non-compliant. Only a cold answer is a trustworthy baseline.
    """

    @classmethod
    def setUpClass(cls) -> None:
        """Capture the cold baseline once, before any test has run.

        Every answer in it is the first call of its own server's life, and the
        sweep runs in the opposite order to `_surface`, so a payload carrying
        anything about the call before it lands where the comparison can see.
        Taking this per test instead would make each test's baseline depend on
        which tests ran first — and the earliest failure would be the only one
        that ever went red.
        """

        cls.cold = {DISCOVER_TOOL: _text(_call(_server(), DISCOVER_TOOL))}
        for ref in reversed(cls._refs()):
            cls.cold[ref] = _text(_call(_server(), OPEN_TOOL, {"ref": ref}))

    @staticmethod
    def _refs() -> list[str]:
        """Every ref the fixture addresses, read off the model, not the gateway.

        Enumerating through `discover` and `open` would spend the very calls a
        cold baseline is made of: by the time the list was in hand, every ref
        on it would already have been delivered once.
        """

        app = ContextureApp(roots=Responder(), name="test")
        refs = []
        for ref, role in app.tree.roles_with_refs():
            refs.append(ref)
            refs.extend(
                f"{ref}/{member.name}"
                for member in (*role.skills, *role.tools, *role.resources)
            )
        return refs

    def _surface(self, server) -> dict[str, str]:
        """Everything `server` discloses now, as raw response text."""

        surface = {DISCOVER_TOOL: _text(_call(server, DISCOVER_TOOL))}
        for ref in self._refs():
            surface[ref] = _text(_call(server, OPEN_TOOL, {"ref": ref}))
        return surface

    def _exercise(self, server) -> None:
        """Put a server through every call it will ever be asked to serve."""

        refs = self._refs()
        for ref in refs + list(reversed(refs)):
            _call(server, OPEN_TOOL, {"ref": ref})
        _call(server, DISCOVER_TOOL)
        _call(
            server,
            INVOKE_READ_ONLY_TOOL,
            {"ref": "responder/get_pod_logs",
             "arguments": {"namespace": "prod", "pod": "api"}},
        )
        _call(server, READ_TOOL, {"ref": "responder/runbook"})

    def test_history_never_changes_an_answer(self) -> None:
        """Repetition, and the order refs are opened in, change nothing."""

        server = _server()
        self._exercise(server)

        self.assertEqual(self._surface(server), self.cold)

    def test_a_ref_resolves_on_a_server_that_was_never_discovered(self) -> None:
        """`discover` is where an agent learns a ref, not where one is issued."""

        server = _server()

        opened = json.loads(
            _text(_call(server, OPEN_TOOL, {"ref": "responder/get_pod_logs"}))
        )
        self.assertEqual(opened["name"], "get_pod_logs")

    def test_running_a_write_leaves_the_surface_untouched(self) -> None:
        """The one call most likely to be given a memory is the one that
        changes the world. It must not change this server."""

        server = _server()
        listed_before = [
            tool.model_dump(mode="json") for tool in asyncio.run(server.list_tools())
        ]

        _call(
            server,
            INVOKE_TOOL,
            {"ref": "responder/delete_pod",
             "arguments": {"namespace": "prod", "pod": "api"}},
        )

        self.assertEqual(self._surface(server), self.cold)
        self.assertEqual(
            [tool.model_dump(mode="json") for tool in asyncio.run(server.list_tools())],
            listed_before,
        )

    def test_a_failed_call_leaves_the_surface_untouched(self) -> None:
        """An error path is where a half-written cache would survive."""

        server = _server()

        for name, arguments in (
            (OPEN_TOOL, {"ref": "responder/banana"}),
            (INVOKE_READ_ONLY_TOOL, {"ref": "responder/delete_pod",
                                     "arguments": {"namespace": "p", "pod": "a"}}),
            (INVOKE_READ_ONLY_TOOL, {"ref": "responder/get_pod_logs",
                                     "arguments": {"namespace": "prod"}}),
        ):
            with self.subTest(tool=name), self.assertRaises(ToolError):
                _call(server, name, arguments)

        self.assertEqual(self._surface(server), self.cold)

    def test_a_used_server_owes_a_new_one_the_same_answers(self) -> None:
        """Two hosts connecting to one declaration are owed the same server.

        They share an app, and so share the `Dispatch` whose schema cache the
        first connection warms. The second must not be able to tell.
        """

        app = ContextureApp(roots=Responder(), name="test")
        first = app.build_server()
        self._exercise(first)
        second = app.build_server()

        self.assertEqual(
            tuple(tool.name for tool in asyncio.run(second.list_tools())),
            GATEWAY_TOOLS,
        )
        self.assertEqual(self._surface(second), self.cold)

    def test_the_schema_cache_is_a_cache_and_not_a_state(self) -> None:
        """`Dispatch` memoizes derivation; dropping it must change nothing."""

        app = ContextureApp(roots=Responder(), name="test")
        server = app.build_server()
        self._exercise(server)

        warm = self._surface(server)
        app.dispatch._derived.clear()

        self.assertEqual(self._surface(server), warm)
        self.assertEqual(warm, self.cold)


#: Claude Code truncates server instructions at this many bytes.
HOST_LIMIT = 2048

#: Shapes to hold the roster to, as (branching factor, depth). The first two
#: fit whole; the rest are past the budget, which is where the rules bite.
ROSTER_SHAPES = ((2, 2), (5, 3), (8, 3), (3, 4), (10, 4))


def _forest(branch: int, depth: int) -> list[Role]:
    """A uniform forest, for asking what the roster does when it runs out."""

    def build(ref: str, remaining: int) -> Role:
        children = (
            [build(f"{ref}-{i}", remaining - 1) for i in range(branch)]
            if remaining > 1
            else []
        )
        return Role(
            name=ref,
            description=f"Role {ref} does something specific.",
            instructions="Do the thing.",
            children=children,
        )

    return [build(f"r{i}", depth) for i in range(branch)]


def _listed(text: str) -> list[str]:
    """The refs a roster actually names, ignoring its truncation line."""

    return re.findall(r"^- ([^:.][^:]*):", text, re.MULTILINE)


class ToolDisclosureTests(unittest.TestCase):
    """What a tool tells an agent about how to call it.

    A tool is reachable two ways — as a card in its role, and by opening its
    ref — and both have to describe the same call. They did not: the card
    carried the derived input schema, while opening the tool listed the raw
    parameter names off `invoke`. That list included any parameter the
    framework fills rather than the model, so the payload named an argument the
    schema would reject.
    """

    def test_both_ways_to_a_tool_describe_the_same_call(self) -> None:
        app = ContextureApp(roots=Responder(), name="test")

        card = next(
            tool
            for tool in app.tree.open("responder")["tools"]
            if tool["name"] == "get_pod_logs"
        )
        opened = app.tree.open("responder/get_pod_logs")

        self.assertEqual(opened["input_schema"], card["input_schema"])
        self.assertEqual(opened["read_only"], card["read_only"])

    def test_a_disclosed_schema_carries_no_derived_titles(self) -> None:
        """`"title": "invokeArguments"` is a pydantic artefact, not information.

        It is the name of the model the SDK built from `invoke`, and the
        per-property titles under it are the parameter names capitalised. Both
        reach the agent on every tool card of every open.
        """

        app = ContextureApp(roots=Responder(), name="test")
        schema = app.tree.open("responder/get_pod_logs")["input_schema"]

        self.assertNotIn("title", schema)
        self.assertEqual(
            [key for value in schema["properties"].values() for key in value],
            ["type", "type", "default", "type"],
        )

    def test_a_parameter_named_title_survives_the_stripping(self) -> None:
        """The obvious way to strip titles deletes this tool's first argument."""

        class Publish(Tool):
            """Publish a note."""

            name = "publish"

            async def invoke(self, title: str, body: str = "") -> str:
                return title

        class Notes(Role):
            """Keep notes."""

            instructions = "Write it down."

            publish = Publish

        app = ContextureApp(roots=Notes(), name="test")
        schema = app.tree.open("notes/publish")["input_schema"]

        self.assertEqual(sorted(schema["properties"]), ["body", "title"])
        self.assertNotIn("title", schema["properties"]["title"])

    def test_stripping_the_disclosed_schema_leaves_validation_alone(self) -> None:
        """The SDK validates against its own copy, which keeps its titles."""

        server = _server()

        self.assertIn(
            "previous=True",
            _text(
                _call(
                    server,
                    INVOKE_READ_ONLY_TOOL,
                    {
                        "ref": "responder/get_pod_logs",
                        "arguments": {
                            "namespace": "prod",
                            "pod": "api",
                            "previous": True,
                        },
                    },
                )
            ),
        )

    def test_a_framework_filled_parameter_is_never_disclosed(self) -> None:
        """`ctx` is the framework's to fill, so an agent must not be told of it.

        The SDK keeps it out of the schema on its own. What it cannot do is
        keep it out of a list `core` builds by reading the signature, because
        `core` has no way to tell the two kinds of parameter apart — which is
        why a disclosure payload now carries the schema and nothing else.
        """

        class Progressing(Tool):
            """Do something slow enough to report on."""

            name = "progressing"
            read_only = True

            async def invoke(self, ctx: Context, target: str) -> str:
                return target

        class Slow(Role):
            """Run something slow."""

            instructions = "Report progress."

            progressing = Progressing

        app = ContextureApp(roots=Slow(), name="test")
        opened = app.tree.open("slow/progressing")
        card = app.tree.open("slow")["tools"][0]

        for payload in (opened, card):
            with self.subTest(payload=payload.get("ref")):
                self.assertNotIn("ctx", json.dumps(payload))
                self.assertEqual(
                    sorted(payload["input_schema"]["properties"]), ["target"]
                )

        # The signature itself still reports every parameter: it describes the
        # function, not the call, and the framework fills one of them.
        self.assertEqual(Progressing().parameters(), ("ctx", "target"))


class RosterTests(unittest.TestCase):
    """What the bootstrap roster promises when it cannot say everything.

    The roster is the only thing a host reads before calling anything, and it
    is budgeted, so it is always at risk of describing a choice that is not the
    real one. ADR 004 stated the rule and ADR 007 kept it: every sibling is
    visible before the choice, and what cannot be seen together is opened
    rather than guessed between.
    """

    def _partial_groups(self, tree: ContextTree, text: str) -> list[str]:
        """Parents the roster names some — but not all — of the children of."""

        held: dict[str, int] = {}
        for ref, _ in tree.roles_with_refs():
            if SEPARATOR in ref:
                parent = ref.rsplit(SEPARATOR, 1)[0]
                held[parent] = held.get(parent, 0) + 1

        shown: dict[str, int] = {}
        for ref in _listed(text):
            if SEPARATOR in ref:
                parent = ref.rsplit(SEPARATOR, 1)[0]
                shown[parent] = shown.get(parent, 0) + 1

        return [
            parent
            for parent, total in held.items()
            if 0 < shown.get(parent, 0) < total
        ]

    def test_a_sibling_set_is_never_shown_in_part(self) -> None:
        """Three of a role's eight sub-roles look like the whole choice.

        This is the failure the budget produces on its own: it stops mid-group,
        and nothing in the text says the group it stopped inside of was cut.
        Listing none of that role's children is strictly better — the reader
        then knows to open it.
        """

        for branch, depth in ROSTER_SHAPES:
            with self.subTest(shape=f"{branch}x{depth}"):
                tree = ContextTree.of(_forest(branch, depth))
                text = instructions.build(tree)

                self.assertEqual(self._partial_groups(tree, text), [])

    def test_the_roster_fits_the_budget_the_host_actually_enforces(self) -> None:
        """Whole groups must not be bought by overrunning the host's limit."""

        for branch, depth in ROSTER_SHAPES:
            with self.subTest(shape=f"{branch}x{depth}"):
                tree = ContextTree.of(_forest(branch, depth))

                self.assertLessEqual(len(instructions.build(tree)), HOST_LIMIT)

    def test_a_forest_that_fits_is_listed_whole(self) -> None:
        """Group-wise spending must not cost a small server its full roster."""

        tree = ContextTree.of(_forest(2, 2))
        listed = _listed(instructions.build(tree))

        self.assertEqual(len(listed), len(list(tree.roles_with_refs())))
        self.assertNotIn("...and", instructions.build(tree))

    def test_what_was_dropped_is_counted_and_pointed_at(self) -> None:
        tree = ContextTree.of(_forest(8, 3))
        text = instructions.build(tree)

        total = len(list(tree.roles_with_refs()))
        line = next(l for l in text.splitlines() if l.startswith("- ...and"))

        self.assertIn(f"{total - len(_listed(text))} more role(s)", line)
        self.assertIn("open one of the roles above", line)

    def test_roots_are_cut_last_and_recovered_by_a_named_call(self) -> None:
        """A root is the first segment of every ref beneath it.

        Cutting the root list silently would hide whole branches with no way
        back. It is also the one cut a single call undoes, because since
        ADR 007 the roots are exactly what discover answers with — so this is
        the one place the roster may show a group in part, and it has to say
        which call completes it.
        """

        crowded = ContextTree.of(
            [
                Role(name=f"root-{i:03d}", description="D" * 70, instructions="x")
                for i in range(60)
            ]
        )
        text = instructions.build(crowded)
        line = next(l for l in text.splitlines() if l.startswith("- ...and"))

        self.assertLessEqual(len(text), HOST_LIMIT)
        self.assertIn("more root role(s)", line)
        self.assertIn(DISCOVER_TOOL, line)
        self.assertGreater(len(_listed(text)), 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
