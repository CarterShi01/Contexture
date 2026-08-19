"""The Goal domain as one role.

This is what one-creator's `GoalManager` becomes. The class docstring was its
`summary()` — the line it called "always-resident L0" — and `instructions` was
its full docstring; here those are the routing card and the active payload,
which is the same split the framework enforces rather than a convention a
selftest has to check.

Flat, with no child roles. All eight tools are about declaring areas and goals,
and a child role earns its round trip when a session enters one branch
*instead of* another. There is no such division here: changing a goal needs the
same tools as reviewing one. `project` / `workitem` will be a different answer.
"""
from __future__ import annotations

from contexture import Role

from .resources import CurrentFocus, ObjectShapes
from .skills import ReviewTheAttentionChain
from .tools import (
    GetArea,
    GetGoal,
    ListAreas,
    ListGoals,
    UpdateFocus,
    UpdateGoalContext,
    UpsertArea,
    UpsertGoal,
)


class GoalDomain(Role):
    """Declare where attention goes: areas that never end and hold a quota, goals that end and hold criteria."""

    # `goal-domain` is what the class name derives to, and every reference
    # beneath a root starts with it. This is the same identifier one-creator
    # addresses the domain by, so a reader moving between the two reads one
    # word rather than two spellings of it.
    name = "goal"

    instructions = """\
Treat the stored row as the structured authority. Read before changing, and
load referenced material only when the task requires it.

An area and a goal are not the same shape, and conflating them is the mistake
this domain exists to prevent. An **area** never ends: it holds a budget — a
share of attention — and a maintenance standard. A **goal** ends: it holds a
horizon, which forces a review when it arrives, and criteria for what counts as
success. Every goal names exactly one area, and a goal belonging to no area
counts toward nobody's share.

Two things here cannot be set through any tool, and refusing them is the point
rather than a limitation:

- `budget` and `status` on an area. The budgets of active areas must total 100,
  which makes them the denominator this domain is measured against — and the
  party being measured must not move its own denominator. A new area is always
  budget 0, paused.
- `status` on a goal. Whether something is done or abandoned is the founder's
  judgement, not an inference from its fields.

Anything that changes a declaration runs through the writing door, where a host
can put a person in front of it, and takes the revision you read as
`expected_revision` — if someone changed the row in between, the write is
refused rather than silently applied to a value you never saw.

To review how attention is allocated, open `review-the-attention-chain`. It
assembles material; the judgement is yours.
"""

    # Reads
    list_areas = ListAreas
    list_goals = ListGoals
    get_area = GetArea
    get_goal = GetGoal

    # Writes — each behind contexture_invoke, never the read-only door
    upsert_area = UpsertArea
    upsert_goal = UpsertGoal
    update_goal_context = UpdateGoalContext
    update_focus = UpdateFocus

    # A method, not a capability
    review = ReviewTheAttentionChain

    # Content that is already there
    focus = CurrentFocus
    objects = ObjectShapes


__all__ = ["GoalDomain"]
