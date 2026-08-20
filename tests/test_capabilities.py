"""Tests for the tools and resources an application implements.

A tool's schema comes from a Python signature rather than a hand-written dict,
and a resource's content is produced only when somebody asks for it.
"""

from __future__ import annotations

import asyncio
import unittest

from contexture.core.errors import (
    DeclarationError,
    DuplicateNameError,
    LookupFailure,
    ModelValidationError,
    NodeNotFoundError,
)
from contexture.core.mcp_interface import Prompt, Resource
from contexture.core.model.manager import ControllerManager
from contexture.core.model.role import Role
from contexture.core.model.skill import Skill
from contexture.core.model.tool import Tool


class ToolDeclarationTests(unittest.TestCase):
    def test_a_constructor_hands_its_identity_to_the_base(self) -> None:
        class GetPodLogs(Tool):
            def __init__(self) -> None:
                super().__init__(
                    name="get-pod-logs",
                    description="Return recent container logs for one Pod.",
                )

            async def invoke(self, namespace: str) -> str:
                return namespace

        tool = GetPodLogs()
        self.assertEqual(tool.name, "get-pod-logs")
        self.assertEqual(
            tool.description, "Return recent container logs for one Pod."
        )

    def test_a_name_is_stated_and_never_derived(self) -> None:
        """MCP tool names are flat and global, so a project must be able to pick.

        Nothing infers one from the class name: a TypeScript bundler renames
        classes, so an implementation of this framework there could not agree
        with this one about what a capability is called.
        """

        class GetPodLogs(Tool):
            def __init__(self) -> None:
                super().__init__(
                    name="get_pod_logs",
                    description="Return recent container logs for one Pod.",
                )

            async def invoke(self) -> str:
                return ""

        self.assertEqual(GetPodLogs().name, "get_pod_logs")

    def test_a_tool_without_a_description_is_refused_when_registered(self) -> None:
        class Undocumented(Tool):
            def __init__(self) -> None:
                super().__init__(
                    name="undocumented",
                )

            async def invoke(self) -> str:
                return ""

        class Holder(Role):
            def __init__(self) -> None:
                super().__init__(
                    name="holder",
                    description="Holds an undocumented tool.",
                    instructions="Anything.",
                    tools=[Undocumented()],
                )

        with self.assertRaises(TypeError) as caught:
            Undocumented()
        self.assertIn("description", str(caught.exception))

    def test_read_only_defaults_to_false(self) -> None:
        """The safe default: an unclassified tool is treated as one that writes."""

        class DeletePod(Tool):
            def __init__(self) -> None:
                super().__init__(
                    name="delete-pod",
                    description="Delete a Pod.",
                )

            async def invoke(self) -> str:
                return ""

        self.assertFalse(DeletePod().read_only)

    def test_parameters_come_from_the_signature_and_skip_self(self) -> None:
        class Complex(Tool):
            def __init__(self) -> None:
                super().__init__(
                    name="complex",
                    description="A tool with several parameters.",
                )

            async def invoke(
                self,
                namespace: str,
                pod: str,
                previous: bool = False,
            ) -> str:
                return ""

        built = Complex()
        self.assertEqual(
            built.parameters(), ("namespace", "pod", "previous")
        )

    def test_the_base_tool_reports_that_it_was_never_implemented(self) -> None:
        class Forgotten(Tool):
            def __init__(self) -> None:
                super().__init__(
                    name="forgotten",
                    description="Somebody declared this and stopped.",
                )

        with self.assertRaises(NotImplementedError):
            asyncio.run(Forgotten().invoke())

    def test_an_imperatively_built_tool_is_still_an_ordinary_tool(self) -> None:
        tool = Tool(name="manual", description="Built at runtime.")
        self.assertEqual(tool.compile("route")["kind"], "tool")


class RoleCompositionTests(unittest.TestCase):
    def _tool(self, tool_name: str) -> Tool:
        return Tool(name=tool_name, description="A tool.")

    def test_a_role_collects_declared_tools(self) -> None:
        class Runbook(Tool):
            def __init__(self) -> None:
                super().__init__(
                    name="runbook",
                    description="A runbook.",
                    read_only=True,
                )

            async def invoke(self) -> str:
                return "BODY"

        class Logs(Tool):
            def __init__(self) -> None:
                super().__init__(
                    name="logs",
                    description="Read logs.",
                )

            async def invoke(self) -> str:
                return ""

        class Responder(Role):
            def __init__(self) -> None:
                super().__init__(
                    name="responder",
                    description="Diagnose workloads.",
                    instructions="Look before touching.",
                    tools=[Logs(), Runbook()],
                )
        role = Responder()
        self.assertEqual(
            sorted(tool.name for tool in role.tools), ["logs", "runbook"]
        )

    def test_two_tools_with_one_name_are_refused_when_registered(self) -> None:
        class First(Tool):
            def __init__(self) -> None:
                super().__init__(
                    name="same",
                    description="First.",
                )

        class Second(Tool):
            def __init__(self) -> None:
                super().__init__(
                    name="same",
                    description="Second.",
                )

        class Clashing(Role):
            def __init__(self) -> None:
                super().__init__(
                    name="clashing",
                    description="A role that grants two tools with one name.",
                    instructions="Anything.",
                    tools=[First(), Second()],
                )

        with self.assertRaises(DuplicateNameError) as caught:
            ControllerManager().register_role(Clashing)
        self.assertIn("cannot share a name", str(caught.exception))
    def test_an_imperative_role_rejects_duplicate_tool_names(self) -> None:
        with self.assertRaises(DuplicateNameError):
            Role(
                name="r",
                description="A role.",
                instructions="Anything.",
                tools=[self._tool("same"), self._tool("same")],
            )

    def test_a_role_finds_its_own_members_by_name(self) -> None:
        """One cross-kind lookup, because the uniqueness invariant is cross-kind."""

        tool = self._tool("get_logs")
        skill = Skill(name="rb", description="RB.", instructions="Read it.")
        role = Role(
            name="r",
            description="A role.",
            instructions="Anything.",
            tools=[tool],
            skills=[skill],
        )

        self.assertIs(role.member("get_logs"), tool)
        self.assertIs(role.member("rb"), skill)
        self.assertEqual([node.name for node in role.members()], ["rb", "get_logs"])

    def test_a_missing_member_reports_what_the_role_holds(self) -> None:
        role = Role(
            name="r",
            description="A role.",
            instructions="Anything.",
            tools=[self._tool("get_logs")],
        )

        with self.assertRaises(NodeNotFoundError) as caught:
            role.member("nope")

        failure = caught.exception
        self.assertIs(failure.reason, LookupFailure.NO_SUCH_MEMBER)
        self.assertEqual(failure.scope, "r")
        self.assertEqual(failure.known, ("get_logs",))
        self.assertIsNone(failure.ref)  # only the tree knows the whole path


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class MemberNameTests(unittest.TestCase):
    """A member's name is the last segment of the reference that opens it.

    So the names inside one role have to be unique across kinds, not merely
    within them. These tests are what stop that constraint from decaying back
    into four independent checks.
    """

    @staticmethod
    def _skill() -> Skill:
        return Skill(name="diagnose", description="A procedure.", instructions="Go.")

    @staticmethod
    def _tool() -> Tool:
        return Tool(name="diagnose", description="A capability.")

    def test_a_skill_and_a_tool_may_not_share_a_name(self) -> None:
        with self.assertRaises(DuplicateNameError) as caught:
            Role(
                name="responder",
                description="A role.",
                instructions="Go.",
                skills=[self._skill()],
                tools=[self._tool()],
            )

        message = str(caught.exception)
        self.assertIn("diagnose", message)
        self.assertIn("skill", message)
        self.assertIn("tool", message)

    def test_a_sub_role_and_a_tool_may_not_share_a_name(self) -> None:
        child = Role(name="runbook", description="A role.", instructions="Go.")
        tool = Tool(name="runbook", description="A document.")

        with self.assertRaises(DuplicateNameError):
            Role(
                name="responder",
                description="A role.",
                instructions="Go.",
                children=[child],
                tools=[tool],
            )

    def test_distinct_names_across_kinds_are_accepted(self) -> None:
        role = Role(
            name="responder",
            description="A role.",
            instructions="Go.",
            skills=[self._skill()],
            tools=[Tool(name="get_pod_logs", description="A capability.")],
        )

        self.assertEqual([skill.name for skill in role.skills], ["diagnose"])
        self.assertEqual([tool.name for tool in role.tools], ["get_pod_logs"])


class RoleSelfDescriptionTests(unittest.TestCase):
    def test_an_opened_role_hands_out_a_card_for_every_member(self) -> None:
        """Opening a role is where its members become visible, and openable.

        A role used to describe only itself, because a member listed without a
        reference could be seen and never opened. It hands out references now
        without knowing how one is spelled: it asks the view it is compiled
        against, so every card it renders is openable by construction.

        Compiled with no view at all here, which is the standalone case — an
        unregistered node reads as its own root. That is what keeps
        `core.model` able to disclose a declaration on its own, with no tree
        and no server in the room.
        """

        role = Role(
            name="responder",
            description="A role.",
            instructions="Work from evidence.",
            skills=[
                Skill(name="diagnose", description="A procedure.", instructions="Go.")
            ],
            tools=[Tool(name="get_pod_logs", description="A capability.")],
        )

        compiled = role.compile("active")

        self.assertEqual(compiled["instructions"], "Work from evidence.")
        self.assertEqual(compiled["ref"], "responder")
        self.assertEqual(
            set(compiled),
            {
                "kind",
                "name",
                "description",
                "ref",
                "instructions",
                "roles",
                "skills",
                "tools",
            },
        )
        self.assertEqual(compiled["roles"], [])
        self.assertEqual([card["ref"] for card in compiled["skills"]], ["diagnose"])
        self.assertEqual([card["ref"] for card in compiled["tools"]], ["get_pod_logs"])

    def test_a_member_arrives_as_a_card_and_never_as_its_own_detail(self) -> None:
        """One level. The procedure inside a skill is a separate call.

        This is progressive disclosure on the containment axis, asserted at the
        one place it could be broken by accident: rendering a member at ACTIVE
        rather than ROUTE would deliver the whole subtree from the top.
        """

        procedure = "Never state what you have not read."
        role = Role(
            name="responder",
            description="A role.",
            instructions="Work from evidence.",
            skills=[
                Skill(
                    name="diagnose",
                    description="A procedure.",
                    instructions=procedure,
                )
            ],
        )

        compiled = role.compile("active")

        self.assertEqual(
            set(compiled["skills"][0]), {"kind", "name", "description", "ref"}
        )
        self.assertNotIn(procedure, str(compiled))


class ProtocolPlaneTests(unittest.TestCase):
    """A prompt and a resource are declared the way everything else is.

    They were once refused a subclass outright, on the grounds that they are
    pointers rather than nodes. The distinction is real and the type still
    keeps it; the *syntax* difference was not worth it — a business should
    write one kind of declaration, not one per plane. What each states is
    checked when it is built, like every other constructor here.
    """

    def test_a_resource_that_states_nothing_cannot_be_built(self) -> None:
        """Subclassing is how a resource is declared; stating nothing is not."""

        class Empty(Resource):
            pass

        with self.assertRaises(TypeError) as caught:
            Empty()
        self.assertIn("opens", str(caught.exception))

    def test_a_prompt_is_declared_as_a_class_like_everything_else(self) -> None:
        """One way to write a declaration, on every plane."""

        class Deploy(Prompt):
            def __init__(self) -> None:
                super().__init__(
                    description="Ship the current build.",
                    opens="team/ops/deploy",
                    model_may_open=False,
                )

        built = Deploy()
        self.assertEqual(built.opens, "team/ops/deploy")
        self.assertFalse(built.model_may_open)
        self.assertIsNone(built.name)

    def test_the_guard_does_not_fire_on_the_classes_it_guards(self) -> None:
        """`@dataclass(slots=True)` rebuilds the class object it decorates.

        The rebuilt class is created with `(object,)` for bases, so it is
        `object.__init_subclass__` that runs and not the one defined in the
        body — which is the only reason a guard can live inside the class it
        guards. It is the same rebuild that forces `Role` and its siblings to
        name their class explicitly in `super()`, and it is invisible from the
        code that would trip over it. Both classes still import and still
        construct, which is what this asserts.
        """

        resource = Resource(opens="platform/runbook", uri="x://r", description="A.")
        prompt = Prompt(opens="platform/deploy", description="B.")

        self.assertEqual(resource.kind, "resource")
        self.assertEqual(prompt.kind, "prompt")

    def test_both_are_reachable_from_the_one_import_a_declaration_uses(self) -> None:
        """A reader should not have to learn a layer name to publish a document."""

        import contexture

        self.assertIs(contexture.Resource, Resource)
        self.assertIs(contexture.Prompt, Prompt)
        self.assertIn("Resource", contexture.__all__)
        self.assertIn("Prompt", contexture.__all__)
