"""Persistence boundary for the Goal domain.

Contexture owns no business state.  This repository owns the small amount of
SQLite-specific work the application needs: row projection, transactions and
compare-and-set.  Models own validation; tools own use-case policy.
"""

from __future__ import annotations

import contextlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .db import schema as database
from .models import Area, ContextConfig, Focus, Goal, default_goal_context


class GoalDomainError(ValueError):
    """A requested Goal-domain operation violates its contract."""


class NotFoundError(GoalDomainError):
    """A requested declaration does not exist."""


class ConflictError(GoalDomainError):
    """A compare-and-set expectation no longer matches stored state."""


_TABLES = {
    "area": {
        "key": "slug",
        "context": False,
        "indexed": ("owner_ref", "status", "revision", "created_at", "updated_at"),
    },
    "goal": {
        "key": "slug",
        "context": True,
        "indexed": (
            "owner_ref",
            "area",
            "status",
            "revision",
            "created_at",
            "updated_at",
        ),
    },
    "focus": {
        "key": "id",
        "context": False,
        "indexed": ("owner_ref", "revision", "created_at", "updated_at"),
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class GoalRepository:
    """Read and atomically change Area, Goal, and Focus declarations."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path

    # -- queries ---------------------------------------------------------

    def areas(self) -> list[Area]:
        return [Area.model_validate(row) for row in self._all("area")]

    def goals(self) -> list[Goal]:
        return [Goal.model_validate(row) for row in self._all("goal")]

    def area(self, slug: str) -> Area:
        row = self._one("area", slug)
        if row is None:
            raise NotFoundError(f"no area named {slug!r}")
        return Area.model_validate(row)

    def goal(self, slug: str) -> Goal:
        row = self._one("goal", slug)
        if row is None:
            raise NotFoundError(f"no goal named {slug!r}")
        return Goal.model_validate(row)

    def focus(self) -> Focus:
        row = self._one("focus", "current")
        if row is None:
            raise NotFoundError("the current focus has not been declared")
        return Focus.model_validate(row)

    def sorted_areas(self) -> list[Area]:
        return sorted(self.areas(), key=lambda area: (-area.budget, area.slug))

    def sorted_goals(self) -> list[Goal]:
        return sorted(self.goals(), key=lambda goal: (goal.area, goal.slug))

    # -- commands --------------------------------------------------------

    def upsert_area(
        self,
        *,
        slug: str,
        why: str,
        title: str | None = None,
        standard: str | None = None,
        objects: list[str] | None = None,
        expected_revision: int | None = None,
    ) -> tuple[Area, bool]:
        current_row = self._one("area", slug)
        current = Area.model_validate(current_row) if current_row else None
        values = current.model_dump(mode="json") if current else {
            "slug": slug,
            "title": title or slug,
            "why": why,
            "budget": 0,
            "standard": "TODO(founder): define what healthy means",
            "status": "paused",
            "objects": ["Note"],
        }
        values.update(self._managed(current, expected_revision))
        values["why"] = why
        if title is not None:
            values["title"] = title
        if standard is not None:
            values["standard"] = standard
        if objects is not None:
            values["objects"] = objects

        candidate = Area.model_validate(values)
        other = [area for area in self.areas() if area.slug != slug]
        self._require_budget_total([*other, candidate])
        created = self._put(
            "area",
            slug,
            candidate.model_dump(mode="json"),
            expected_revision,
        )
        return candidate, created

    def upsert_goal(
        self,
        *,
        slug: str,
        why: str,
        area: str | None = None,
        title: str | None = None,
        horizon: str | None = None,
        success: list[str] | None = None,
        expected_revision: int | None = None,
    ) -> tuple[Goal, bool]:
        current_row = self._one("goal", slug)
        current = Goal.model_validate(current_row) if current_row else None
        resolved_area = area or (current.area if current else None)
        active = {item.slug for item in self.areas() if item.status == "active"}
        if not resolved_area:
            raise GoalDomainError(
                f"a goal needs an area (active areas: {sorted(active)})"
            )
        if resolved_area not in active:
            raise GoalDomainError(
                f"area {resolved_area!r} is not active (allowed: {sorted(active)})"
            )

        values = current.model_dump(mode="json") if current else {
            "slug": slug,
            "area": resolved_area,
            "title": title or slug,
            "why": why,
            "horizon": "2099-Q4",
            "success": ["TODO(founder): define what success means"],
            "status": "active",
            "context": default_goal_context().model_dump(mode="json"),
        }
        values.update(self._managed(current, expected_revision))
        values.update({"why": why, "area": resolved_area})
        if title is not None:
            values["title"] = title
        if horizon is not None:
            values["horizon"] = horizon
        if success is not None:
            values["success"] = success

        candidate = Goal.model_validate(values)
        created = self._put(
            "goal",
            slug,
            candidate.model_dump(mode="json"),
            expected_revision,
        )
        return candidate, created

    def update_goal_context(
        self,
        *,
        slug: str,
        context: ContextConfig | Mapping[str, Any],
        expected_revision: int,
    ) -> Goal:
        current = self.goal(slug)
        values = current.model_dump(mode="json")
        values.update(self._managed(current, expected_revision))
        values["context"] = ContextConfig.model_validate(context).model_dump(mode="json")
        candidate = Goal.model_validate(values)
        self._put(
            "goal",
            slug,
            candidate.model_dump(mode="json"),
            expected_revision,
        )
        return candidate

    def update_focus(
        self,
        *,
        main_thread: str | None = None,
        week_top: list[str] | None = None,
        not_doing: list[str] | None = None,
    ) -> Focus:
        if main_thread is None and week_top is None and not_doing is None:
            raise GoalDomainError(
                "update-focus needs at least one field; pass an explicit empty "
                "list to clear a list"
            )
        current = self.focus()
        values = current.model_dump(mode="json")
        values.update(self._managed(current, current.revision))
        for name, value in {
            "main_thread": main_thread,
            "week_top": week_top,
            "not_doing": not_doing,
        }.items():
            if value is not None:
                values[name] = value
        candidate = Focus.model_validate(values)
        self._put(
            "focus",
            "current",
            candidate.model_dump(mode="json"),
            current.revision,
        )
        return candidate

    def seed(
        self,
        *,
        areas: Iterable[Mapping[str, Any]],
        goals: Iterable[Mapping[str, Any]],
        focus: Mapping[str, Any],
    ) -> int:
        """Insert a complete sample allocation, but never touch existing areas."""

        if self._all("area"):
            return 0
        now = utc_now()
        managed = {
            "owner_ref": "principal://founder",
            "revision": 1,
            "created_at": now,
            "updated_at": now,
        }
        area_values = [Area.model_validate({**row, **managed}) for row in areas]
        self._require_budget_total(area_values)
        goal_values = [
            Goal.model_validate(
                {
                    **row,
                    "context": default_goal_context().model_dump(mode="json"),
                    **managed,
                }
            )
            for row in goals
        ]
        active = {area.slug for area in area_values if area.status == "active"}
        unknown = sorted({goal.area for goal in goal_values} - active)
        if unknown:
            raise GoalDomainError(f"seed goals name inactive areas: {unknown}")

        written = 0
        for area in area_values:
            self._put("area", area.slug, area.model_dump(mode="json"), None)
            written += 1
        for goal in goal_values:
            self._put("goal", goal.slug, goal.model_dump(mode="json"), None)
            written += 1
        if self._one("focus", "current") is None:
            current = Focus.model_validate({**focus, **managed})
            self._put("focus", "current", current.model_dump(mode="json"), None)
            written += 1
        return written

    # -- storage mechanics ----------------------------------------------

    @staticmethod
    def _managed(
        current: Area | Goal | Focus | None,
        expected_revision: int | None,
    ) -> dict[str, Any]:
        if current is not None and expected_revision is None:
            raise ConflictError("expected_revision is required for an existing object")
        now = utc_now()
        return {
            "owner_ref": current.owner_ref if current else "principal://founder",
            "revision": 1 if current is None else expected_revision + 1,
            "created_at": current.created_at if current else now,
            "updated_at": now,
        }

    @staticmethod
    def _require_budget_total(areas: Iterable[Area]) -> None:
        total = sum(area.budget for area in areas if area.status == "active")
        if total != 100:
            raise GoalDomainError(f"active area budgets total {total}, expected 100")

    def _connect(self):
        return database.connect(self.path)

    def _all(self, table: str) -> list[dict[str, Any]]:
        meta = _TABLES[table]
        with contextlib.closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT * FROM {table} ORDER BY {meta['key']}"
            ).fetchall()
        return [self._decode(table, row) for row in rows]

    def _one(self, table: str, key: str) -> dict[str, Any] | None:
        meta = _TABLES[table]
        with contextlib.closing(self._connect()) as connection:
            row = connection.execute(
                f"SELECT * FROM {table} WHERE {meta['key']}=?", (key,)
            ).fetchone()
        return self._decode(table, row) if row is not None else None

    def _put(
        self,
        table: str,
        key: str,
        value: Mapping[str, Any],
        expected_revision: int | None,
    ) -> bool:
        meta = _TABLES[table]
        columns = self._encode(table, key, value)
        with contextlib.closing(self._connect()) as connection, database.txn(connection):
            current = connection.execute(
                f"SELECT revision FROM {table} WHERE {meta['key']}=?", (key,)
            ).fetchone()
            actual = int(current[0]) if current is not None else None
            created = current is None
            if created:
                if expected_revision is not None:
                    raise ConflictError(
                        f"{key} revision is absent, expected {expected_revision}"
                    )
                names = list(columns)
                connection.execute(
                    f"INSERT INTO {table}({','.join(names)}) "
                    f"VALUES({','.join('?' for _ in names)})",
                    tuple(columns[name] for name in names),
                )
                return True

            if expected_revision is None:
                raise ConflictError(f"expected_revision is required for {key}")
            if actual != expected_revision:
                raise ConflictError(
                    f"{key} revision is {actual}, expected {expected_revision}"
                )
            if int(columns["revision"]) != actual + 1:
                raise ConflictError(f"{key} revision must increment by one")

            names = [name for name in columns if name != meta["key"]]
            parameters = [columns[name] for name in names]
            parameters.extend((key, expected_revision))
            changed = connection.execute(
                f"UPDATE {table} SET "
                f"{','.join(f'{name}=?' for name in names)} "
                f"WHERE {meta['key']}=? AND revision=?",
                parameters,
            ).rowcount
            if changed != 1:
                raise ConflictError(f"{key} changed during update")
            return False

    @staticmethod
    def _encode(
        table: str, key: str, value: Mapping[str, Any]
    ) -> dict[str, Any]:
        meta = _TABLES[table]
        document = dict(value)
        document.pop(meta["key"], None)
        context = document.pop("context", None)
        columns = {name: document.pop(name) for name in meta["indexed"]}
        columns[meta["key"]] = key
        columns["doc"] = json.dumps(
            document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if meta["context"]:
            columns["context_json"] = json.dumps(
                context, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        return columns

    @staticmethod
    def _decode(table: str, row: Any) -> dict[str, Any]:
        meta = _TABLES[table]
        document = json.loads(row["doc"])
        if table != "focus":
            document[meta["key"]] = row[meta["key"]]
        for name in meta["indexed"]:
            document[name] = row[name]
        if meta["context"]:
            document["context"] = json.loads(row["context_json"])
        return document


__all__ = [
    "ConflictError",
    "GoalDomainError",
    "GoalRepository",
    "NotFoundError",
    "utc_now",
]
