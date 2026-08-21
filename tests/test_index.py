"""Tests for the compiled index: the facts derived from a registered forest.

`ControllerManager` owns what exists; `Index` owns every question asked *about*
it — where a node hangs, what one of a kind there is, what a tool costs to call
— and answers each from a table built once, while it compiles, and never again.
Two properties this file exists to pin:

**It is a snapshot.** Registering another root after an index is compiled does
not change it. That is what makes "a served surface does not vary as a
consequence of an earlier call" structural rather than a convention.

**It carries the bindings.** One per tool, keyed by the address that opens it,
which is what replaced a process-wide cache keyed by object identity.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from contexture.core.errors import LookupFailure, NodeNotFoundError  # noqa: E402
from contexture.core.model.index import Index  # noqa: E402
from contexture.core.model.manager import ControllerManager  # noqa: E402
from contexture.core.model.role import Role  # noqa: E402
from contexture.core.model.tool import Tool  # noqa: E402

from test_manager import (  # noqa: E402
    Channels,
    GetPodStatus,
    IncidentResponse,
    Platform,
    Standalone,
    platform_manager,
)


def _index(channels: object | None = None) -> Index:
    return Index.of(platform_manager(channels))


class AddressResolutionTests(unittest.TestCase):
    def test_every_node_is_told_where_it_hangs(self) -> None:
        index = _index()
        tool = index.find("platform/incident-response/get_pod_status")
        self.assertEqual(
            tool.path, ("platform", "incident-response", "get_pod_status")
        )
        self.assertEqual(index.roots[0].path, ("platform",))

    def test_ref_of_spells_the_address_the_node_carries(self) -> None:
        index = _index()
        tool = index.find("platform/incident-response/get_pod_status")
        self.assertEqual(
            index.ref_of(tool), "platform/incident-response/get_pod_status"
        )

    def test_the_address_is_segments_not_a_spelling(self) -> None:
        """`core` still does not know what a separator is.

        The tuple carries position; joining it is the index's decision, and this
        is what keeps a separator from creeping down onto a node.
        """

        for _, node in _index().walk():
            self.assertIsInstance(node.path, tuple)
            for segment in node.path:
                self.assertNotIn("/", segment)

    def test_the_same_class_under_two_roles_is_two_controllers(self) -> None:
        """Two declarations of one class are two capabilities, not one."""

        index = _index()
        first = index.find("platform/incident-response/get_pod_status")
        second = index.find("platform/deployment-ops/get_pod_status")
        self.assertIsNot(first, second)
        self.assertIs(type(first), type(second))
        self.assertNotEqual(first.path, second.path)

    def test_a_node_from_another_forest_has_no_address_here(self) -> None:
        loose = GetPodStatus()
        with self.assertRaises(Exception):
            _index().ref_of(loose)


class LookupTests(unittest.TestCase):
    def test_find_answers_from_one_lookup(self) -> None:
        skill = _index().find("platform/incident-response/diagnose")
        self.assertEqual(skill.kind, "skill")

    def test_an_empty_address_says_so(self) -> None:
        with self.assertRaises(NodeNotFoundError) as caught:
            _index().find("")
        self.assertIs(caught.exception.reason, LookupFailure.EMPTY_REF)

    def test_a_missing_root_names_the_root(self) -> None:
        with self.assertRaises(NodeNotFoundError) as caught:
            _index().find("nothing/here")
        self.assertIs(caught.exception.reason, LookupFailure.NO_SUCH_ROOT)
        self.assertEqual(caught.exception.segment, "nothing")

    def test_a_missing_member_names_the_segment_and_its_scope(self) -> None:
        with self.assertRaises(NodeNotFoundError) as caught:
            _index().find("platform/incident-response/nope")
        self.assertIs(caught.exception.reason, LookupFailure.NO_SUCH_MEMBER)
        self.assertEqual(caught.exception.segment, "nope")
        self.assertEqual(caught.exception.scope, "incident-response")

    def test_going_below_a_leaf_says_it_holds_nothing(self) -> None:
        with self.assertRaises(NodeNotFoundError) as caught:
            _index().find("platform/incident-response/get_pod_status/deeper")
        self.assertIs(caught.exception.reason, LookupFailure.NOT_A_CONTAINER)
        self.assertEqual(caught.exception.scope, "get_pod_status")

    def test_a_ref_that_is_not_a_tool_is_refused_by_tool(self) -> None:
        with self.assertRaises(NodeNotFoundError) as caught:
            _index().tool("platform/incident-response")
        self.assertIs(caught.exception.reason, LookupFailure.WRONG_KIND)


class QueryTests(unittest.TestCase):
    def test_of_kind_is_the_flat_view(self) -> None:
        index = _index()
        self.assertEqual(
            [tool.name for tool in index.of_kind("tool")],
            ["get_pod_status", "get_pod_status"],
        )
        self.assertEqual([role.name for role in index.of_kind("role")][0], "platform")
        self.assertEqual(len(index.of_kind("skill")), 1)
        self.assertEqual(index.of_kind("resource"), ())

    def test_parent_and_children_agree(self) -> None:
        index = _index()
        root = index.roots[0]
        self.assertIsNone(index.parent_of(root))
        for child in index.children_of(root):
            self.assertIs(index.parent_of(child), root)

    def test_a_leaf_holds_nothing(self) -> None:
        index = _index()
        tool = index.find("platform/incident-response/get_pod_status")
        self.assertEqual(index.children_of(tool), ())

    def test_walk_is_depth_first_in_declared_order(self) -> None:
        self.assertEqual(
            [ref for ref, _ in _index().walk()],
            [
                "platform",
                "platform/incident-response",
                "platform/incident-response/diagnose",
                "platform/incident-response/get_pod_status",
                "platform/deployment-ops",
                "platform/deployment-ops/get_pod_status",
            ],
        )

    def test_membership_is_by_address(self) -> None:
        index = _index()
        self.assertIn("platform/incident-response", index)
        self.assertNotIn("platform/nope", index)

    def test_len_is_the_whole_forest(self) -> None:
        self.assertEqual(len(_index()), 6)


class BindingTests(unittest.TestCase):
    """One binding per tool, present the moment the index is compiled."""

    def test_every_tool_has_a_binding_keyed_by_its_ref(self) -> None:
        index = _index()
        for node in index.of_kind("tool"):
            ref = index.ref_of(node)
            self.assertIsNotNone(index.binding_of(ref))

    def test_schema_of_reads_through_the_binding(self) -> None:
        index = _index()
        tool = index.find("platform/incident-response/get_pod_status")
        # The default binding carries an empty schema; the point here is that
        # the path from a node to its schema goes through its binding at all.
        self.assertEqual(index.schema_of(tool), index.binding_of(index.ref_of(tool)).schema)


class SnapshotTests(unittest.TestCase):
    def test_registering_after_compiling_does_not_change_the_index(self) -> None:
        """The reason an index does not hold the registry it was built from.

        A protocol that forbids a server to vary its surface as a consequence of
        an earlier call needs "what is served does not change" to be structural.
        Compile once, register more, and the compiled index is untouched.
        """

        manager = platform_manager()
        index = Index.of(manager)
        before = [ref for ref, _ in index.walk()]

        manager.register_role(Standalone)

        self.assertEqual([ref for ref, _ in index.walk()], before)
        self.assertNotIn("standalone", index)
        # A freshly compiled index, by contrast, sees the new root.
        self.assertIn("standalone", Index.of(manager))

    def test_the_channels_handle_is_captured_for_the_served_path(self) -> None:
        channels = Channels("captured")
        index = Index.of(platform_manager(channels))
        self.assertIs(index.channels, channels)


class ConstructionTests(unittest.TestCase):
    def test_an_empty_registry_will_not_compile(self) -> None:
        from contexture.core.errors import ModelValidationError

        with self.assertRaises(ModelValidationError):
            Index.of(ControllerManager())

    def test_one_root_or_many_compiles_the_same_way(self) -> None:
        self.assertIn("platform", Index.of(Platform))
        self.assertIn("incident-response", Index.of([IncidentResponse, Role(
            name="other", description="Other.", instructions="Route."
        )]))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
