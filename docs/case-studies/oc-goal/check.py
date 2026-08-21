"""Drive every node of this demo, and assert what had to survive the port.

    OC_OBJECT_DB_PATH=/tmp/oc-goal-check.db python -m oc_goal.seed
    OC_OBJECT_DB_PATH=/tmp/oc-goal-check.db python check.py

Point it at a scratch database, never at one holding real data: it writes.

There is no MCP SDK in the loop. That is deliberate for what this file is for —
everything below the wire, exercised on a machine that cannot install one. What
it therefore does *not* cover is the wire itself: schema derivation from
`invoke`'s type hints, the gateway refusing a write sent through the read-only
door, and the stdio framing. Those need `contexture serve` against a real host.

The assertions in section 5 are the ones worth reading. Each is a guarantee
one-creator's `@write` decorator provided and that had to keep working once the
contract moved onto the Tool class.
"""
import asyncio
import json

from contexture.core.model.disclosure import Disclosure
from oc_goal.goal import GoalDomain
from oc_goal.goal.model import Area, Goal
from oc_goal.goal.resources import CurrentFocus, ObjectShapes
from oc_goal.goal.tools import (
    GetArea, GetGoal, ListAreas, ListGoals,
    UpdateFocus, UpdateGoalContext, UpsertArea, UpsertGoal,
)
from oc_goal.citizens import ConflictError, CitizenError, InvariantError

ok, bad = [], []


def check(label, condition, detail=""):
    (ok if condition else bad).append(label)
    print(("  ok   " if condition else "  FAIL ") + label + (" — " + detail if detail else ""))


async def main():
    tree = Disclosure.of(GoalDomain())

    print("\n[1] tree")
    roots = [r["ref"] for r in tree.skeleton()["roles"]]
    check("discover returns one root", roots == ["goal"], str(roots))
    payload = tree.open("goal")
    check("open goal returns instructions", bool(payload.get("instructions")))
    check("8 tools", len(payload["tools"]) == 8, str(len(payload["tools"])))
    check("1 skill", len(payload["skills"]) == 1)
    check("2 resources", len(payload["resources"]) == 2)
    check("no child roles", payload["sub_roles"] == [])
    check("skill opens to its procedure",
          "Assemble the material" in tree.open("goal/review-the-attention-chain")["instructions"])
    check("write tool is not read-only", tree.tool("goal/upsert-goal").read_only is False)
    check("read tool is read-only", tree.tool("goal/list-areas").read_only is True)

    print("\n[2] reads")
    areas = await ListAreas().invoke()
    check("list-areas counts 3", areas["count"] == 3, str(areas["count"]))
    check("active budgets sum to 100", areas["active_budget_sum"] == 100,
          str(areas["active_budget_sum"]))
    check("areas sorted by budget desc",
          [a["slug"] for a in areas["areas"]] == ["product", "craft", "health"],
          str([a["slug"] for a in areas["areas"]]))
    goals = await ListGoals().invoke()
    check("list-goals counts 3", goals["count"] == 3)
    check("goals grouped by area",
          [g["slug"] for g in goals["goals"]] ==
          ["own-the-storage-layer", "sustainable-week", "ship-first-release"],
          str([g["slug"] for g in goals["goals"]]))
    one = await GetGoal().invoke(slug="ship-first-release")
    check("get-goal returns the row", one["area"] == "product")
    check("get-goal carries its context config", isinstance(one.get("context"), dict))
    try:
        await GetArea().invoke(slug="nope")
        check("get-area rejects unknown slug", False)
    except KeyError:
        check("get-area rejects unknown slug", True)

    print("\n[3] resources")
    focus = json.loads(await CurrentFocus().read())
    check("focus reads back", focus["main_thread"].startswith("Get the first release"))
    shapes = json.loads(await ObjectShapes().read())
    check("object shapes cover three citizens", set(shapes) == {"Area", "Goal", "Focus"})
    area_props = shapes["Area"]["properties"] if "properties" in shapes["Area"] else {}
    check("Area shape is a document envelope", bool(shapes["Area"]))

    print("\n[4] writes")
    before = Goal.get("ship-first-release")
    result = await UpsertGoal().invoke(
        slug="ship-first-release", why="Validated only when someone outside depends on it.",
        expected_revision=before.revision)
    check("upsert-goal succeeds", result["ok"] is True)
    after = Goal.get("ship-first-release")
    check("revision incremented", after.revision == before.revision + 1,
          "%s -> %s" % (before.revision, after.revision))
    check("updated_at moved", after.updated_at != before.updated_at)

    print("\n[5] the guarantees that had to survive the move")
    try:
        await UpsertGoal().invoke(slug="ship-first-release", why="stale write",
                                  expected_revision=before.revision)
        check("CAS rejects a stale revision", False)
    except ConflictError:
        check("CAS rejects a stale revision", True)

    try:
        await UpsertGoal().invoke(slug="brand-new", why="A goal with no area at all.",
                                  area="does-not-exist")
        check("closed-set check rejects an unknown area", False)
    except CitizenError:
        check("closed-set check rejects an unknown area", True)

    try:
        await UpsertArea().invoke(slug="product", why="short", expected_revision=1)
        check("field constraint rejects a too-short why", False)
    except (InvariantError, ConflictError) as exc:
        check("field constraint rejects a too-short why", isinstance(exc, InvariantError),
              type(exc).__name__)

    created = await UpsertArea().invoke(slug="scratch", why="A new area created by the tool.")
    check("created area is budget 0 / paused",
          created["budget"] == 0 and created["status"] == "paused",
          "%s/%s" % (created["budget"], created["status"]))

    try:
        await UpdateFocus().invoke()
        check("empty focus update is refused", False)
    except CitizenError:
        check("empty focus update is refused", True)

    updated = await UpdateFocus().invoke(main_thread="Cut the release branch today.")
    check("focus update reports what changed", updated["changed"] == ["main_thread"],
          str(updated.get("changed")))
    document = updated["document"]
    check("focus update applies", document["main_thread"] == "Cut the release branch today.")
    check("focus update leaves other fields alone", document["not_doing"] == [
        "Anything that starts with a rewrite", "New areas until these three are honest"])

    goal_row = Goal.get("ship-first-release")
    ctx = dict(goal_row.context)
    ctx["environment"] = {**ctx["environment"], "memory_scopes": []}
    await UpdateGoalContext().invoke(slug="ship-first-release", context=ctx,
                                     expected_revision=goal_row.revision)
    check("goal context narrows under CAS",
          Goal.get("ship-first-release").context["environment"]["memory_scopes"] == [])

    print("\n[6] invariants still hold after all that")
    check("Area.check_all clean", Area.check_all() == [], str(Area.check_all()))
    check("Goal.check_all clean", Goal.check_all() == [], str(Goal.check_all()))

    print("\n%d passed, %d failed" % (len(ok), len(bad)))
    if bad:
        print("failed: " + ", ".join(bad))
    return 1 if bad else 0


raise SystemExit(asyncio.run(main()))
