"""Executable capabilities of the Goal role.

Every class says exactly what Contexture needs: explicit identity, a trusted
read/write classification, and a typed ``invoke`` method.  Persistence remains
behind :class:`GoalRepository`; no tool implements reflection or routing.
"""

from __future__ import annotations

import json

from contexture import Tool

from .models import (
    Area,
    ContextConfig,
    Criteria,
    Focus,
    FocusItem,
    Goal,
    Horizon,
    ObjectNames,
    Revision,
    Slug,
    Standard,
    Title,
    Why,
)
from .repository import GoalRepository


def _dump(value: Area | Goal | Focus) -> dict:
    return value.model_dump(mode="json")


class ListAreas(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="list-areas",
            description="List attention areas, their budgets, and standards.",
            read_only=True,
        )

    async def invoke(self) -> dict:
        areas = GoalRepository().sorted_areas()
        return {
            "count": len(areas),
            "active_budget_sum": sum(
                area.budget for area in areas if area.status == "active"
            ),
            "areas": [_dump(area) for area in areas],
        }


class ListGoals(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="list-goals",
            description="List goals, grouped by area, with horizons and criteria.",
            read_only=True,
        )

    async def invoke(self) -> dict:
        goals = GoalRepository().sorted_goals()
        return {"count": len(goals), "goals": [_dump(goal) for goal in goals]}


class GetArea(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="get-area",
            description="Return one attention area by slug.",
            read_only=True,
        )

    async def invoke(self, slug: Slug) -> dict:
        return _dump(GoalRepository().area(slug))


class GetGoal(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="get-goal",
            description="Return one goal by slug.",
            read_only=True,
        )

    async def invoke(self, slug: Slug) -> dict:
        return _dump(GoalRepository().goal(slug))


class UpsertArea(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="upsert-area",
            description=(
                "Create or revise an area without changing its human-owned "
                "budget or status."
            ),
            read_only=False,
        )

    async def invoke(
        self,
        slug: Slug,
        why: Why,
        title: Title | None = None,
        standard: Standard | None = None,
        objects: ObjectNames | None = None,
        expected_revision: Revision | None = None,
    ) -> dict:
        area, created = GoalRepository().upsert_area(
            slug=slug,
            why=why,
            title=title,
            standard=standard,
            objects=objects,
            expected_revision=expected_revision,
        )
        return {
            "ok": True,
            "storage": "storage://oc.object-db#area",
            "slug": area.slug,
            "created": created,
            "budget": area.budget,
            "status": area.status,
            "revision": area.revision,
        }


class UpsertGoal(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="upsert-goal",
            description=(
                "Create or revise a goal without changing its human-owned status."
            ),
            read_only=False,
        )

    async def invoke(
        self,
        slug: Slug,
        why: Why,
        area: Slug | None = None,
        title: Title | None = None,
        horizon: Horizon | None = None,
        success: Criteria | None = None,
        expected_revision: Revision | None = None,
    ) -> dict:
        goal, created = GoalRepository().upsert_goal(
            slug=slug,
            why=why,
            area=area,
            title=title,
            horizon=horizon,
            success=success,
            expected_revision=expected_revision,
        )
        return {
            "ok": True,
            "storage": "storage://oc.object-db#goal",
            "slug": goal.slug,
            "created": created,
            "area": goal.area,
            "status": goal.status,
            "revision": goal.revision,
        }


class UpdateGoalContext(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="update-goal-context",
            description="Replace one goal's context policy under compare-and-set.",
            read_only=False,
        )

    async def invoke(
        self,
        slug: Slug,
        context: ContextConfig,
        expected_revision: Revision,
    ) -> dict:
        goal = GoalRepository().update_goal_context(
            slug=slug,
            context=context,
            expected_revision=expected_revision,
        )
        return {"ok": True, "slug": goal.slug, "revision": goal.revision}


class UpdateFocus(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="update-focus",
            description="Change at least one field of the current focus declaration.",
            read_only=False,
        )

    async def invoke(
        self,
        main_thread: FocusItem | None = None,
        week_top: list[FocusItem] | None = None,
        not_doing: list[FocusItem] | None = None,
    ) -> dict:
        focus = GoalRepository().update_focus(
            main_thread=main_thread,
            week_top=week_top,
            not_doing=not_doing,
        )
        return {"ok": True, "revision": focus.revision, "focus": _dump(focus)}


class ReadCurrentFocus(Tool):
    """The read-only node published at ``goal://focus``."""

    def __init__(self) -> None:
        super().__init__(
            name="current-focus",
            description="Read the current main thread and not-doing list.",
            read_only=True,
        )

    async def invoke(self) -> str:
        return json.dumps(
            _dump(GoalRepository().focus()), ensure_ascii=False, indent=2
        )


class DescribeGoalObjects(Tool):
    """The read-only node published at ``goal://objects``."""

    def __init__(self) -> None:
        super().__init__(
            name="object-shapes",
            description="Read the validated shapes of Area, Goal, and Focus.",
            read_only=True,
        )

    async def invoke(self) -> str:
        shapes = {
            "Area": Area.model_json_schema(),
            "Goal": Goal.model_json_schema(),
            "Focus": Focus.model_json_schema(),
        }
        return json.dumps(shapes, ensure_ascii=False, indent=2)


__all__ = [
    "DescribeGoalObjects",
    "GetArea",
    "GetGoal",
    "ListAreas",
    "ListGoals",
    "ReadCurrentFocus",
    "UpdateFocus",
    "UpdateGoalContext",
    "UpsertArea",
    "UpsertGoal",
]
