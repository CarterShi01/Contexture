"""Tests for the registry that owns the controllers a process serves.

Three claims carry this layer and each is checked rather than assumed: a
controller is told its address once instead of recomputing it, every registered
controller reaches the same handle the application built before any of them
existed, and one capability cannot end up with two addresses.
"""

from __future__ import annotations

import unittest

from contexture.core.errors import (
    LookupFailure,
    ModelValidationError,
    NodeNotFoundError,
)
from contexture.core.model.manager import ControllerManager
from contexture.core.model.role import Role
from contexture.core.model.skill import Skill
from contexture.core.model.tool import Tool


class GetPodStatus(Tool):
    """Return the phase of one Pod."""

    name = "get_pod_status"
    read_only = True

    async def invoke(self, pod: str) -> str:
        return pod


class Diagnose(Skill):
    """Work out why a Pod keeps restarting."""

    instructions = "Read the status, then the logs."


class IncidentResponse(Role):
    """Handle a production incident."""

    instructions = "Establish what is happening before changing anything."

    status = GetPodStatus
    diagnose = Diagnose


class DeploymentOps(Role):
    """Ship and roll back workloads."""

    instructions = "Prefer rolling forward."

    status = GetPodStatus


class Platform(Role):
    """The Kubernetes platform."""

    instructions = "Route to the branch that owns the question."

    incidents = IncidentResponse
    deploys = DeploymentOps


class Standalone(Role):
    """A root nothing else holds."""

    instructions = "Answer on your own."

    status = GetPodStatus


class Channels:
    """Stands in for whatever an application builds before it serves."""

    def __init__(self, label: str = "gateway") -> None:
        self.label = label


def platform_manager(channels: object | None = None) -> ControllerManager:
    manager = ControllerManager(channels=channels)
    manager.register(Platform)
    return manager


class RegistrationTests(unittest.TestCase):
    def test_a_class_is_built_here(self) -> None:
        """Registration is where a controller comes into existence.

        Taking the class rather than an instance is what lets the channels be
        in hand first, which is the order `main()` reads in.
        """

        manager = ControllerManager()
        root = manager.register(Platform)
        self.assertIsInstance(root, Platform)
        self.assertIs(manager.roots[0], root)

    def test_an_instance_is_taken_as_it_is(self) -> None:
        built = Platform()
        manager = ControllerManager()
        self.assertIs(manager.register(built), built)

    def test_registering_something_that_is_not_a_role_is_refused(self) -> None:
        manager = ControllerManager()
        with self.assertRaises(ModelValidationError) as caught:
            manager.register(GetPodStatus)  # type: ignore[arg-type]
        self.assertIn("registers roots", str(caught.exception))

    def test_two_roots_may_not_share_a_name(self) -> None:
        manager = ControllerManager()
        manager.register(Platform)
        with self.assertRaises(ModelValidationError) as caught:
            manager.register(Platform)
        self.assertIn("first segment", str(caught.exception))

    def test_register_all_returns_each_root(self) -> None:
        manager = ControllerManager()
        registered = manager.register_all([IncidentResponse, DeploymentOps])
        self.assertEqual(
            [root.name for root in registered],
            ["incident-response", "deployment-ops"],
        )


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
        shared = GetPodStatus()
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
            manager.register(root)
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
            manager.register(outer)
        self.assertIn("contains itself", str(caught.exception))


class SecondAddressTests(unittest.TestCase):
    """Registering as a root something another root already holds.

    Two instances of one Role class share their member objects — a member is
    materialised once, when the class body is read — so registering
    `IncidentResponse` beside a `Platform` that already holds it does not
    produce a second copy. It produces one skill at two addresses, which is the
    thing an address exists to prevent, and the manager is the first place in
    this package that can see it.
    """

    def test_a_held_role_may_not_also_be_a_root(self) -> None:
        manager = ControllerManager()
        manager.register(Platform)
        with self.assertRaises(ModelValidationError) as caught:
            manager.register(IncidentResponse)
        message = str(caught.exception)
        self.assertIn("held twice", message)
        self.assertIn("platform/incident-response/diagnose", message)

    def test_the_sharing_that_makes_it_so(self) -> None:
        first, second = IncidentResponse(), IncidentResponse()
        self.assertIsNot(first, second)
        self.assertIs(first.skills[0], second.skills[0])


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
        manager.register(Platform)
        manager.register(Standalone)
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
        self.assertIsNone(manager.address_of(GetPodStatus()))

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
