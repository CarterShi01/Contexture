"""What the Goal domain can do, one capability per class.

Each of these was a decorated method on one-creator's `GoalManager`. The bodies
are unchanged; what moved is the contract around them — from decorator
arguments to class attributes, and from an address the resource surface
published to a reference the role tree resolves:

    @read(address="area://index", name="area-index", …)   →   ListAreas(Tool)
    @write(target=Goal, fields=(…), precondition=cas())   →   UpsertGoal(CitizenTool)

Nothing here declares `read_only` on a write: inheriting `CitizenTool` is that
declaration, and the gateway enforces it by refusing a write sent through the
read-only door.

One thing is deliberately missing, and it is the only place this demo is weaker
than what it was ported from. One-creator trims every record through an egress
port before it leaves the process — a cross-cutting boundary that belongs to no
single citizen, injected by the host at registration. There is no host here to
inject one, so these tools return the row. That is defensible for a
single-principal demo and would not be once anything multi-tenant reads it.
"""
from __future__ import annotations

from ..citizens import CitizenError
from ..surface import CitizenTool, DocumentTool
from .model import Area, Focus, Goal

from contexture import Tool


# ── Ordering ─────────────────────────────────────────────────────────────
# Reproduced from one-creator so the output is byte-comparable against it. A
# citizen reads its own truth rather than a derived view, but the two sort rules
# that view used are part of what "the same answer" means.

def sorted_areas() -> list[dict]:
    """Budget descending, most important first."""

    return sorted(Area.rows(),
                  key=lambda a: (-int(a.get("budget") or 0), a.get("slug") or ""))


def sorted_goals() -> list[dict]:
    """Goals of one area stay together."""

    return sorted(Goal.rows(), key=lambda g: (g.get("area") or "", g.get("slug") or ""))


# ── Reads ────────────────────────────────────────────────────────────────

class ListAreas(Tool):
    """List every attention area with its quota and maintenance standard."""

    read_only = True

    async def invoke(self) -> dict:
        records = sorted_areas()
        return {
            "count": len(records),
            "active_budget_sum": sum(r.get("budget") or 0 for r in records
                                     if r.get("status") == "active"),
            "areas": records,
        }


class ListGoals(Tool):
    """List every goal with its horizon and success criteria."""

    read_only = True

    async def invoke(self) -> dict:
        records = sorted_goals()
        return {"count": len(records), "goals": records}


class GetArea(Tool):
    """Return one area declaration by slug."""

    read_only = True

    async def invoke(self, slug: str) -> dict:
        for row in sorted_areas():
            if row.get("slug") == slug:
                return row
        raise KeyError("no area named %r" % slug)


class GetGoal(Tool):
    """Return one goal declaration by slug."""

    read_only = True

    async def invoke(self, slug: str) -> dict:
        for row in sorted_goals():
            if row.get("slug") == slug:
                return row
        raise KeyError("no goal named %r" % slug)


# ── Writes ───────────────────────────────────────────────────────────────

class UpsertGoal(CitizenTool):
    """Create or change a goal declaration — the layer that has an end.

    `status` cannot be set here: done or abandoned is the founder's judgement.
    Budget lives on the area. `area` is the owning area, single-valued and
    required on create.
    """

    target = Goal
    patch_fields = ("why", "area", "title", "horizon", "success")
    writes = ("storage://oc.object-db#goal",)

    async def invoke(self, slug: str, why: str, area: str | None = None,
                     title: str | None = None, horizon: str | None = None,
                     success: list[str] | None = None,
                     expected_revision: int | None = None) -> dict:
        existing = self.row(slug)
        # On create, `area` is required and must be in the active closed set.
        # One-creator has this check twice over — the schema enum stops the
        # model, this stops a direct call that bypassed the schema. Only the
        # second one travels: deriving the enum from `Area.keys(status=...)`
        # needs a schema layer that reads the live store, which Contexture
        # derives from type hints and cannot do yet.
        resolved = getattr(area, "key", area) or (existing or {}).get("area")
        active = Area.keys(status="active")
        if not resolved:
            raise CitizenError(
                "a goal needs an area — it must belong to one (active: %s)" % sorted(active))
        if resolved not in active:
            raise CitizenError(
                "area %r is not in the active closed set (allowed: %s)"
                % (resolved, sorted(active)))

        result = self.write(slug, {
            "area": resolved,
            "title": title or (existing or {}).get("title") or slug,
            "why": why,
            "horizon": horizon,
            "success": list(success) if success is not None else None,
        }, expected=expected_revision)
        entry = result["entry"]
        return {"ok": True, "file": result["file"], "slug": slug,
                "created": result["created"],
                "area": entry.get("area"), "status": entry["status"]}


class UpsertArea(CitizenTool):
    """Create or change an area declaration — the layer that never ends and holds a quota.

    `budget` and `status` cannot be set here: they are the denominator this
    domain is measured against, and the party being measured must not change
    its own denominator. A create is always budget=0 / status=paused;
    activation is a founder edit.
    """

    target = Area
    patch_fields = ("why", "title", "standard", "objects")
    writes = ("storage://oc.object-db#area",)

    async def invoke(self, slug: str, why: str, title: str | None = None,
                     standard: str | None = None, objects: list[str] | None = None,
                     expected_revision: int | None = None) -> dict:
        existing = self.row(slug)
        result = self.write(slug, {
            "title": title or (existing or {}).get("title") or slug,
            "why": why,
            "standard": standard,
            "objects": list(objects) if objects is not None else None,
        }, expected=expected_revision)
        entry = result["entry"]
        return {"ok": True, "file": result["file"], "slug": slug,
                "created": result["created"],
                "budget": entry["budget"], "status": entry["status"]}


class UpdateGoalContext(CitizenTool):
    """Narrow one goal's context configuration under compare-and-set."""

    target = Goal
    patch_fields = ("context",)
    writes = ("storage://oc.object-db#goal",)

    async def invoke(self, slug: str, context: dict, expected_revision: int) -> dict:
        if self.row(slug) is None:
            raise KeyError("no goal named %r" % slug)
        result = self.write(slug, {"context": context}, expected=expected_revision)
        return {"ok": True, "slug": slug, "revision": result["entry"]["revision"]}


class UpdateFocus(DocumentTool):
    """Change the current attention declaration — one per system, founder-only.

    Not given means not touched, not "keep the old value": this operation only
    edits an existing document and never creates, so an omitted argument means
    unmentioned. Clearing an item requires an explicit empty value (`[]` or
    `""`); omitting it will not delete it.

    Stricter than the upserts: with all three omitted the call is rejected, so
    an empty call neither clears the focus nor produces a pointless write.
    """

    target = Focus
    patch_fields = ("main_thread", "week_top", "not_doing")
    writes = ("storage://oc.object-db#focus",)

    async def invoke(self, main_thread: str | None = None,
                     week_top: list[str] | None = None,
                     not_doing: list[str] | None = None) -> dict:
        if main_thread is None and week_top is None and not_doing is None:
            raise CitizenError(
                "focus_update needs at least one field — an empty call changes "
                'nothing; to clear one, pass an explicit empty value ([] or "")')
        return self.patch({"main_thread": main_thread,
                           "week_top": week_top,
                           "not_doing": not_doing})


__all__ = [
    "GetArea", "GetGoal", "ListAreas", "ListGoals",
    "UpdateFocus", "UpdateGoalContext", "UpsertArea", "UpsertGoal",
    "sorted_areas", "sorted_goals",
]
