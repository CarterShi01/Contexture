"""Tests for the registry that owns the controllers a process serves.

Three claims carry this layer and each is checked rather than assumed: a
controller is told its address once instead of recomputing it, every registered
controller reaches the same handle the application built before any of them
existed, and one capability cannot end up with two addresses.
"""

from __future__ import annotations

import gc
import unittest

from contexture.core.errors import (
    DeclarationError,
    LookupFailure,
    ModelValidationError,
    NodeNotFoundError,
)
from contexture.core.model.manager import ControllerManager
from contexture.core.model.node import ContextNode
from contexture.core.model.role import Role
from contexture.core.model.skill import Skill
from contexture.core.model.tool import Tool


class GetPodStatus(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="get_pod_status",
            description="Return the phase of one Pod.",
            read_only=True,
        )

    async def invoke(self, pod: str) -> str:
        return pod


class Diagnose(Skill):
    def __init__(self) -> None:
        super().__init__(
            name="diagnose",
            description="Work out why a Pod keeps restarting.",
            instructions="Read the status, then the logs.",
        )


class IncidentResponse(Role):
    def __init__(self) -> None:
        super().__init__(
            name="incident-response",
            description="Handle a production incident.",
            instructions="Establish what is happening before changing anything.",
            skills=[Diagnose()],
            tools=[GetPodStatus()],
        )

class DeploymentOps(Role):
    def __init__(self) -> None:
        super().__init__(
            name="deployment-ops",
            description="Ship and roll back workloads.",
            instructions="Prefer rolling forward.",
            tools=[GetPodStatus()],
        )


class Platform(Role):
    def __init__(self) -> None:
        super().__init__(
            name="platform",
            description="The Kubernetes platform.",
            instructions="Route to the branch that owns the question.",
            children=[IncidentResponse(), DeploymentOps()],
        )

class Standalone(Role):
    def __init__(self) -> None:
        super().__init__(
            name="standalone",
            description="A root nothing else holds.",
            instructions="Answer on your own.",
            tools=[GetPodStatus()],
        )


class Channels:
    """Stands in for whatever an application builds before it serves."""

    def __init__(self, label: str = "gateway") -> None:
        self.label = label


def platform_manager(channels: object | None = None) -> ControllerManager:
    manager = ControllerManager(channels=channels)
    manager.register_role(Platform)
    return manager


class RegistrationTests(unittest.TestCase):
    def test_a_class_is_built_here(self) -> None:
        """Registration is where a controller comes into existence.

        Taking the class rather than an instance is what lets the channels be
        in hand first, which is the order `main()` reads in.
        """

        manager = ControllerManager()
        root = manager.register_role(Platform)
        self.assertIsInstance(root, Platform)
        self.assertIs(manager.roots[0], root)

    def test_an_instance_is_taken_as_it_is(self) -> None:
        built = Role(name="built", description="Built.", instructions="Hold.")
        manager = ControllerManager()
        self.assertIs(manager.register_role(built), built)

    def test_a_class_is_built_here_and_the_node_is_returned(self) -> None:
        """Registration is the moment a declared root comes into existence."""

        manager = ControllerManager()
        registered = manager.register_role(Platform)
        self.assertIsInstance(registered, Platform)
        self.assertIsNot(registered, Platform)
        self.assertEqual(registered.path, ("platform",))

    def test_registering_something_that_is_not_a_role_is_refused(self) -> None:
        manager = ControllerManager()
        with self.assertRaises(ModelValidationError) as caught:
            manager.register_role(GetPodStatus)  # type: ignore[arg-type]
        self.assertIn("is not a Role", str(caught.exception))

    def test_two_roots_may_not_share_a_name(self) -> None:
        manager = ControllerManager()
        manager.register_role(Platform)
        with self.assertRaises(ModelValidationError) as caught:
            manager.register_role(Platform)
        self.assertIn("first segment", str(caught.exception))

    def test_each_kind_has_its_own_registration_method(self) -> None:
        """Three methods, because what a root is decides what may hang below.

        Naming the kind at the call site is what makes "this is a standalone
        tool" something a reader sees, rather than something inferred from the
        type of an argument — and it is the only shape Go can express, where a
        typed slice per kind is the alternative to a list of `any`.
        """

        manager = ControllerManager()
        manager.register_role(IncidentResponse)
        manager.register_skill(Diagnose)
        manager.register_tool(GetPodStatus)
        self.assertEqual([held.name for held in manager.roles], ["incident-response"])
        self.assertEqual([held.name for held in manager.skills], ["diagnose"])
        self.assertEqual([held.name for held in manager.tools], ["get_pod_status"])
        self.assertEqual(
            [held.name for held in manager.roots],
            ["incident-response", "diagnose", "get_pod_status"],
        )

    def test_two_roots_of_two_kinds_may_not_share_a_name(self) -> None:
        """Three lists, one namespace: a root name is a ref's first segment."""

        class Clash(Role):
            def __init__(self) -> None:
                super().__init__(
                    name="get_pod_status",
                    description="Named like the standalone tool.",
                    instructions="Anything.",
                )

        manager = ControllerManager()
        manager.register_tool(GetPodStatus)
        with self.assertRaises(ModelValidationError) as caught:
            manager.register_role(Clash)
        self.assertIn("a tool and a role", str(caught.exception))


class AddressTests(unittest.TestCase):
    def test_every_node_is_told_where_it_hangs(self) -> None:
        manager = platform_manager()
        tool = manager.find(("platform", "incident-response", "get_pod_status"))
        self.assertEqual(
            tool.path, ("platform", "incident-response", "get_pod_status")
        )
        self.assertEqual(manager.roots[0].path, ("platform",))

    def test_the_address_is_segments_not_a_spelling(self) -> None:
        """`core` still does not know what a separator is.

        The tuple carries position; joining it is `disclosure`'s decision, and
        this test is what keeps a separator from creeping down a layer.
        """

        manager = platform_manager()
        for _, node in manager.walk():
            self.assertIsInstance(node.path, tuple)
            for segment in node.path:
                self.assertNotIn("/", segment)

    def test_the_same_class_under_two_roles_is_two_controllers(self) -> None:
        """Two declarations of one class are two capabilities, not one.

        Each gets its own instance and therefore its own address, which is why
        this is allowed where holding one object twice is not.
        """

        manager = platform_manager()
        first = manager.find(("platform", "incident-response", "get_pod_status"))
        second = manager.find(("platform", "deployment-ops", "get_pod_status"))
        self.assertIsNot(first, second)
        self.assertIs(type(first), type(second))
        self.assertNotEqual(first.path, second.path)

    def test_one_object_may_not_be_held_twice(self) -> None:
        shared = Tool(name="get_pod_status", description="Status.")
        left = Role(
            name="left", description="Left.", instructions="Left.", tools=[shared]
        )
        right = Role(
            name="right", description="Right.", instructions="Right.", tools=[shared]
        )
        root = Role(
            name="root",
            description="Root.",
            instructions="Route.",
            children=[left, right],
        )
        manager = ControllerManager()
        with self.assertRaises(ModelValidationError) as caught:
            manager.register_role(root)
        message = str(caught.exception)
        self.assertIn("held twice", message)
        self.assertIn("root/left/get_pod_status", message)
        self.assertIn("root/right/get_pod_status", message)

    def test_a_cycle_is_named_as_one(self) -> None:
        outer = Role(name="outer", description="Outer.", instructions="Outer.")
        inner = Role(
            name="inner", description="Inner.", instructions="Inner.", children=[outer]
        )
        outer.children.append(inner)
        manager = ControllerManager()
        with self.assertRaises(ModelValidationError) as caught:
            manager.register_role(outer)
        self.assertIn("contains itself", str(caught.exception))


class IndependenceTests(unittest.TestCase):
    """Two instances of one Role class are two independent subtrees.

    A member used to be materialised once, when the class body was read, and
    shared by every instance of the declaring class. That was invisible while
    nothing was ever written onto a node — and stopped being invisible the
    moment a registry started stamping an address and a handle onto one.
    """

    def test_one_class_registered_twice_becomes_two_independent_nodes(self) -> None:
        """A class is a declaration, not the node. Each position gets its own.

        Anything a registry stamps onto a node — its address, the handle it may
        reach outside this process — would otherwise be written onto an object
        two servers in one process are both serving.
        """

        first = ControllerManager(channels="left").register_role(IncidentResponse)
        second = ControllerManager(channels="right").register_role(IncidentResponse)
        self.assertIsNot(first, second)
        self.assertIsNot(first.skills[0], second.skills[0])
        self.assertIsNot(first.tools[0], second.tools[0])
        self.assertEqual(first.skills[0].name, second.skills[0].name)
        self.assertEqual(first.tools[0].channels, "left")
        self.assertEqual(second.tools[0].channels, "right")

    def test_a_role_may_be_held_here_and_registered_there(self) -> None:
        manager = ControllerManager()
        manager.register_role(Platform)
        manager.register_role(IncidentResponse)
        held = manager.find(("platform", "incident-response", "diagnose"))
        root = manager.find(("incident-response", "diagnose"))
        self.assertIsNot(held, root)
        self.assertEqual(held.path, ("platform", "incident-response", "diagnose"))
        self.assertEqual(root.path, ("incident-response", "diagnose"))

    def test_two_managers_do_not_write_over_each_other(self) -> None:
        """The property the whole change exists for.

        Two servers in one process, each with its own downstream connections,
        must not find their capabilities pointing at the other's.
        """

        left = ControllerManager(channels=Channels("left"))
        right = ControllerManager(channels=Channels("right"))
        left.register_role(Platform)
        right.register_role(Platform)
        self.assertEqual(
            left.find(("platform", "incident-response")).channels.label, "left"
        )
        self.assertEqual(
            right.find(("platform", "incident-response")).channels.label, "right"
        )

    def test_a_class_where_a_node_belongs_is_refused(self) -> None:
        """`tools=[GetPodStatus]` is the mistake; the message names the fix.

        Left to itself it is quiet and strange: a class carries the base
        dataclass's slot descriptors, so every unbuilt member reads as having
        the same name and the uniqueness check fails with a sentence about two
        members sharing a name that nobody wrote.
        """

        with self.assertRaises(ModelValidationError) as caught:
            Role(
                name="mistaken",
                description="Holds a class.",
                instructions="Anything.",
                tools=[GetPodStatus],  # type: ignore[list-item]
            )
        message = str(caught.exception)
        self.assertIn("GetPodStatus()", message)
        self.assertIn("a class is the factory", message)

    def test_the_imperative_door_holds_nodes_from_either_source(self) -> None:
        """A role assembled at run time may mix declared nodes with ad-hoc ones."""

        role = Role(
            name="mixed",
            description="Mixed.",
            instructions="Hold both.",
            tools=[GetPodStatus(), Tool(name="pinned", description="P.")],
        )
        manager = ControllerManager()
        manager.register_role(role)
        self.assertEqual(
            sorted(tool.name for tool in manager.of_kind("tool")),
            ["get_pod_status", "pinned"],
        )


class ConstructionTimeTests(unittest.TestCase):
    """When a declared graph comes into existence, and where.

    The headline property of this object model: a module full of declarations
    builds nothing when it is imported. Classes state what a capability is;
    a `ControllerManager` is the one thing that turns them into nodes, because
    registration is the only moment a node can be told where it hangs and
    handed what it may reach.
    """

    def test_declaring_a_forest_constructs_nothing(self) -> None:
        gc.collect()
        before = sum(
            1 for held in gc.get_objects() if isinstance(held, ContextNode)
        )

        class Leaf(Tool):
            def __init__(self) -> None:
                super().__init__(name="leaf", description="A leaf.")

            async def invoke(self) -> str:
                return ""

        class Branch(Role):
            def __init__(self) -> None:
                super().__init__(
                    name="branch",
                    description="A branch.",
                    instructions="Route.",
                    tools=[Leaf()],
                )

        class Trunk(Role):
            def __init__(self) -> None:
                super().__init__(
                    name="trunk",
                    description="A trunk.",
                    instructions="Route.",
                    children=[Branch()],
                )

        gc.collect()
        after = sum(
            1 for held in gc.get_objects() if isinstance(held, ContextNode)
        )
        self.assertEqual(before, after)

    def test_registration_is_where_the_nodes_appear(self) -> None:
        manager = ControllerManager(channels="handle")
        root = manager.register_role(IncidentResponse)
        self.assertEqual(len(manager), 3)
        self.assertEqual(root.path, ("incident-response",))
        self.assertEqual(root.tools[0].channels, "handle")

    def test_a_shared_base_class_supplies_what_a_subclass_does_not(self) -> None:
        """Twenty tools of one domain that differ in three fields."""

        class DomainTool(Tool):
            def __init__(self, **stated: object) -> None:
                super().__init__(
                    **{
                        "description": "A tool in this domain.",
                        "read_only": True,
                        **stated,
                    }
                )

        class Specific(DomainTool):
            def __init__(self) -> None:
                super().__init__(name="specific")

            async def invoke(self) -> str:
                return ""

        built = Specific()
        self.assertEqual(built.name, "specific")
        self.assertEqual(built.description, "A tool in this domain.")
        self.assertTrue(built.read_only)


class ChannelTests(unittest.TestCase):
    def test_every_controller_reaches_the_handle(self) -> None:
        channels = Channels()
        manager = platform_manager(channels)
        self.assertEqual(len(manager), 6)
        for _, node in manager.walk():
            self.assertIs(node.channels, channels)

    def test_no_handle_is_an_ordinary_answer(self) -> None:
        # Members are materialised once per class body, so a handle stamped by
        # any manager in this process is still on them. Clearing it is what
        # isolates this case, and it is a real property rather than a test
        # nuisance: two managers over one declaration share its nodes.
        manager = platform_manager()
        manager.rebind_channels(None)
        for _, node in manager.walk():
            self.assertIsNone(node.channels)

    def test_rebinding_reaches_everything_already_registered(self) -> None:
        manager = platform_manager(Channels("first"))
        replacement = Channels("second")
        manager.rebind_channels(replacement)
        self.assertIs(manager.channels, replacement)
        for _, node in manager.walk():
            self.assertIs(node.channels, replacement)

    def test_a_root_registered_later_gets_the_same_handle(self) -> None:
        channels = Channels()
        manager = ControllerManager(channels=channels)
        manager.register_role(Platform)
        manager.register_role(Standalone)
        self.assertIs(
            manager.find(("standalone", "get_pod_status")).channels, channels
        )


class LookupTests(unittest.TestCase):
    def test_find_answers_from_one_lookup(self) -> None:
        manager = platform_manager()
        skill = manager.find(("platform", "incident-response", "diagnose"))
        self.assertEqual(skill.kind, "skill")

    def test_an_empty_address_says_so(self) -> None:
        with self.assertRaises(NodeNotFoundError) as caught:
            platform_manager().find(())
        self.assertIs(caught.exception.reason, LookupFailure.EMPTY_REF)

    def test_a_missing_root_names_the_root(self) -> None:
        with self.assertRaises(NodeNotFoundError) as caught:
            platform_manager().find(("nothing", "here"))
        self.assertIs(caught.exception.reason, LookupFailure.NO_SUCH_ROOT)
        self.assertEqual(caught.exception.segment, "nothing")

    def test_a_missing_member_names_the_segment_and_its_scope(self) -> None:
        with self.assertRaises(NodeNotFoundError) as caught:
            platform_manager().find(("platform", "incident-response", "nope"))
        self.assertIs(caught.exception.reason, LookupFailure.NO_SUCH_MEMBER)
        self.assertEqual(caught.exception.segment, "nope")
        self.assertEqual(caught.exception.scope, "incident-response")

    def test_going_below_a_leaf_says_it_holds_nothing(self) -> None:
        with self.assertRaises(NodeNotFoundError) as caught:
            platform_manager().find(
                ("platform", "incident-response", "get_pod_status", "deeper")
            )
        self.assertIs(caught.exception.reason, LookupFailure.NOT_A_CONTAINER)
        self.assertEqual(caught.exception.scope, "get_pod_status")


class QueryTests(unittest.TestCase):
    def test_of_kind_is_the_flat_view(self) -> None:
        manager = platform_manager()
        self.assertEqual(
            [tool.name for tool in manager.of_kind("tool")],
            ["get_pod_status", "get_pod_status"],
        )
        self.assertEqual([role.name for role in manager.of_kind("role")][0], "platform")
        self.assertEqual(len(manager.of_kind("skill")), 1)
        self.assertEqual(manager.of_kind("resource"), ())

    def test_parent_and_children_agree(self) -> None:
        manager = platform_manager()
        root = manager.roots[0]
        self.assertIsNone(manager.parent_of(root))
        for child in manager.children_of(root):
            self.assertIs(manager.parent_of(child), root)

    def test_a_leaf_holds_nothing(self) -> None:
        manager = platform_manager()
        tool = manager.find(("platform", "incident-response", "get_pod_status"))
        self.assertEqual(manager.children_of(tool), ())

    def test_address_of_answers_only_for_what_it_registered(self) -> None:
        manager = platform_manager()
        self.assertEqual(manager.address_of(manager.roots[0]), ("platform",))
        self.assertIsNone(manager.address_of(GetPodStatus))

    def test_walk_is_depth_first_in_declared_order(self) -> None:
        manager = platform_manager()
        self.assertEqual(
            ["/".join(path) for path, _ in manager.walk()],
            [
                "platform",
                "platform/incident-response",
                "platform/incident-response/diagnose",
                "platform/incident-response/get_pod_status",
                "platform/deployment-ops",
                "platform/deployment-ops/get_pod_status",
            ][:6],
        )

    def test_membership_is_by_address(self) -> None:
        manager = platform_manager()
        self.assertIn(("platform", "incident-response"), manager)
        self.assertNotIn(("platform", "nope"), manager)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
