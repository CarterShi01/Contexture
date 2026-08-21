"""End-to-end contract check for the oc-goal case study.

Run from this directory with ``uv run python check.py``. The check compiles the
real Contexture application and invokes capabilities through the production
binding, exercising schemas and gateway policy as well as persistence.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile

from contexture.core.model.system_api import Refused, SystemAPI
from contexture.server import compile_application

from oc_goal import app
from oc_goal.repository import ConflictError, GoalDomainError, GoalRepository
from oc_goal.seed import seed


async def check() -> None:
    with tempfile.TemporaryDirectory(prefix="oc-goal-check-") as directory:
        previous = os.environ.get("OC_OBJECT_DB_PATH")
        os.environ["OC_OBJECT_DB_PATH"] = os.path.join(directory, "oc.db")
        try:
            assert seed() == 7
            assert seed() == 0

            first = compile_application(app)
            second = compile_application(app)
            first.server()  # validates the two Resource declarations
            assert first.index.find("goal") is not second.index.find("goal")

            refs = {ref for ref, _ in first.index.walk()}
            assert refs == {
                "goal",
                "goal/review-attention",
                "goal/list-areas",
                "goal/list-goals",
                "goal/get-area",
                "goal/get-goal",
                "goal/upsert-area",
                "goal/upsert-goal",
                "goal/update-goal-context",
                "goal/update-focus",
                "goal/current-focus",
                "goal/object-shapes",
            }

            schema = first.index.binding_of("goal/upsert-area").schema
            assert schema["required"] == ["slug", "why"]
            assert "budget" not in schema["properties"]
            assert "status" not in schema["properties"]
            assert schema["properties"]["why"]["minLength"] == 10

            api = SystemAPI(first.disclosure)
            discovered = await api.discover()
            assert [role["ref"] for role in discovered["roles"]] == ["goal"]
            opened = await api.open("goal")
            assert len(opened["tools"]) == 10
            assert opened["skills"][0]["ref"] == "goal/review-attention"

            areas = await api.invoke_read_only("goal/list-areas")
            goals = await api.invoke_read_only("goal/list-goals")
            assert areas["count"] == 3
            assert areas["active_budget_sum"] == 100
            assert goals["count"] == 3
            assert (await api.invoke_read_only(
                "goal/get-area", {"slug": "product"}
            ))["budget"] == 55

            focus_document = await api.read_for_a_host("goal/current-focus")
            assert json.loads(focus_document)["revision"] == 1
            shapes = json.loads(await api.read_for_a_host("goal/object-shapes"))
            assert shapes["Area"]["properties"]["budget"]["maximum"] == 100
            assert shapes["Goal"]["properties"]["horizon"]["pattern"].startswith("^")

            created_area = await api.invoke(
                "goal/upsert-area",
                {
                    "slug": "writing",
                    "why": "Writing makes important reasoning inspectable.",
                },
            )
            assert created_area["created"] is True
            assert created_area["budget"] == 0
            assert created_area["status"] == "paused"
            assert created_area["revision"] == 1

            revised_area = await api.invoke(
                "goal/upsert-area",
                {
                    "slug": "writing",
                    "why": "Writing keeps important reasoning inspectable.",
                    "expected_revision": 1,
                },
            )
            assert revised_area["created"] is False
            assert revised_area["revision"] == 2

            try:
                await api.invoke(
                    "goal/upsert-area",
                    {
                        "slug": "writing",
                        "why": "A stale writer must never replace newer state.",
                        "expected_revision": 1,
                    },
                )
            except Exception as error:
                assert isinstance(error.__cause__, ConflictError)
            else:
                raise AssertionError("a stale compare-and-set write was accepted")

            created_goal = await api.invoke(
                "goal/upsert-goal",
                {
                    "slug": "publish-notes",
                    "why": "Useful notes should reach people who need them.",
                    "area": "product",
                },
            )
            assert created_goal["created"] is True
            assert created_goal["area"] == "product"

            try:
                await api.invoke(
                    "goal/upsert-goal",
                    {
                        "slug": "invalid-owner",
                        "why": "This goal deliberately names an inactive area.",
                        "area": "writing",
                    },
                )
            except Exception as error:
                assert isinstance(error.__cause__, GoalDomainError)
            else:
                raise AssertionError("a goal was assigned to an inactive area")

            goal = GoalRepository().goal("publish-notes")
            context = goal.context.model_dump(mode="json")
            context["environment"]["explicit_refs"] = ["not-a-uri"]
            try:
                await api.invoke(
                    "goal/update-goal-context",
                    {
                        "slug": goal.slug,
                        "context": context,
                        "expected_revision": goal.revision,
                    },
                )
            except Exception as error:
                assert "stable URI" in str(error)
            else:
                raise AssertionError("an invalid context reference was accepted")

            try:
                await api.invoke("goal/update-focus", {})
            except Exception as error:
                assert isinstance(error.__cause__, GoalDomainError)
            else:
                raise AssertionError("an empty focus update was accepted")

            changed_focus = await api.invoke(
                "goal/update-focus", {"week_top": ["Publish the case study"]}
            )
            assert changed_focus["revision"] == 2
            assert changed_focus["focus"]["week_top"] == ["Publish the case study"]

            try:
                await api.invoke_read_only(
                    "goal/upsert-area",
                    {
                        "slug": "wrong-door",
                        "why": "A write must use the writing gateway every time.",
                    },
                )
            except Refused as error:
                assert "contexture_invoke" in str(error)
            else:
                raise AssertionError("the read-only gateway accepted a write")

            try:
                await api.invoke("goal/list-areas")
            except Refused as error:
                assert "contexture_invoke_read_only" in str(error)
            else:
                raise AssertionError("the writing gateway accepted a read")
        finally:
            if previous is None:
                os.environ.pop("OC_OBJECT_DB_PATH", None)
            else:
                os.environ["OC_OBJECT_DB_PATH"] = previous


def main() -> int:
    asyncio.run(check())
    print("oc-goal: application, schemas, resources, reads, writes, and CAS pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
