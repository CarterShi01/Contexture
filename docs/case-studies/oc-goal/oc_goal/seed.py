"""Put a believable attention allocation in an empty database.

    python -m oc_goal.seed

Seeding is explicit rather than automatic, and it refuses to touch a database
that already holds areas. Pointed at one-creator's `oc.db` this does nothing at
all, which is the behaviour that matters: the demo has to be runnable on a
machine that has never heard of one-creator, without ever being a thing that
writes into a real one.

The rows go in through the repository rather than through the tools, because two of
these fields cannot be set by any tool — `budget` and `status` are founder
judgements, and a created area is always budget 0, paused. A seed that could
only produce paused areas summing to zero would violate the invariant it is
supposed to demonstrate.
"""
from __future__ import annotations

import sys

from .db.schema import db_path
from .repository import GoalRepository


AREAS = [
    {
        "slug": "product",
        "title": "Product",
        "why": "The thing people actually use. Everything else is upstream of it.",
        "budget": 55,
        "standard": "Someone outside the team used it this week and did not need help.",
        "status": "active",
        "objects": ["Note", "Release"],
    },
    {
        "slug": "craft",
        "title": "Craft",
        "why": "Capability compounds; skipping it is borrowing against next year.",
        "budget": 30,
        "standard": "One thing done this month that would have been out of reach last quarter.",
        "status": "active",
        "objects": ["Note"],
    },
    {
        "slug": "health",
        "title": "Health",
        "why": "The only input with no substitute. It never ends and never gets urgent in time.",
        "budget": 15,
        "standard": "Sleep and movement held through a bad week, not just a good one.",
        "status": "active",
        "objects": ["Note"],
    },
]

GOALS = [
    {
        "slug": "ship-first-release",
        "area": "product",
        "title": "Ship the first release",
        "why": "Nothing is validated until somebody who is not us depends on it.",
        "horizon": "2026-Q4",
        "success": [
            "Three people outside the team install it without being walked through it",
            "A bug reported by one of them is fixed and released inside a week",
        ],
        "status": "active",
    },
    {
        "slug": "own-the-storage-layer",
        "area": "craft",
        "title": "Own the storage layer",
        "why": "It is the part currently trusted rather than understood.",
        "horizon": "2026-12-31",
        "success": ["Can explain every table and why it is shaped that way, without reading first"],
        "status": "active",
    },
    {
        "slug": "sustainable-week",
        "area": "health",
        "title": "A week that repeats",
        "why": "A pace that only works when nothing goes wrong is not a pace.",
        "horizon": "2026-Q4",
        "success": ["TODO(founder): what counts as sustainable here"],
        "status": "active",
    },
]

FOCUS = {
    "main_thread": "Get the first release into someone else's hands.",
    "week_top": ["Cut the release branch", "Write the install path someone can follow"],
    "not_doing": ["Anything that starts with a rewrite", "New areas until these three are honest"],
}


def seed(path: str | None = None) -> int:
    """Write the sample rows. Returns how many were inserted."""

    return GoalRepository(path).seed(areas=AREAS, goals=GOALS, focus=FOCUS)


def main() -> int:
    target = db_path()
    written = seed()
    if written:
        print("seeded %d rows into %s" % (written, target))
    else:
        print("%s already holds areas; nothing written" % target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
