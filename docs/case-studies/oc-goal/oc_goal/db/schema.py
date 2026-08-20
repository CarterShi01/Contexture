"""The three tables this demo needs, and how to open them.

The DDL is copied verbatim from one-creator's `brain-mcp/kernel/object_store.py`
— column for column, index for index — because byte-identical schema is the
whole precondition for the two servers sharing one database. Anything
"improved" here stops the comparison from meaning anything.

That file declares thirteen tables at schema version 3. This one declares the
three the Goal domain owns and touches none of the rest.

**`user_version` is deliberately not written.** The original migration stamps it,
which is right for the owner of a thirteen-table schema and wrong for a
three-table subset. Leaving it alone makes both directions safe:

    demo opens one-creator's oc.db   every CREATE is IF NOT EXISTS, so this is
                                     a no-op and the stamp stays at 3
    demo creates its own database    three tables and user_version 0, so if
                                     one-creator is later pointed at it, its own
                                     migration runs and fills in the other ten

Point `OC_OBJECT_DB_PATH` at `$HERMES_HOME/oc.db` to share one-creator's data.
Unset, this lands in a per-user directory, so `contexture demo` works on a
machine that has never heard of one-creator.
"""
from __future__ import annotations

import contextlib
import os
import sqlite3
import threading

#: The version one-creator's schema is at. Recorded so a reader can tell which
#: revision these three tables were copied from; never written to the file.
SOURCE_SCHEMA_VERSION = 3

_BUSY_TIMEOUT_MS = 10000
_INITIALIZED: set[str] = set()
_INIT_LOCK = threading.Lock()


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS area (
  slug        TEXT PRIMARY KEY,
  owner_ref   TEXT NOT NULL,
  status      TEXT NOT NULL,
  revision    INTEGER NOT NULL,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  doc         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_object_area_owner ON area(owner_ref, status);

CREATE TABLE IF NOT EXISTS goal (
  slug         TEXT PRIMARY KEY,
  owner_ref    TEXT NOT NULL,
  area         TEXT NOT NULL,
  status       TEXT NOT NULL,
  revision     INTEGER NOT NULL,
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL,
  context_json TEXT NOT NULL CHECK(json_valid(context_json)),
  doc          TEXT NOT NULL,
  FOREIGN KEY(area) REFERENCES area(slug)
);
CREATE INDEX IF NOT EXISTS ix_object_goal_owner ON goal(owner_ref, status);
CREATE INDEX IF NOT EXISTS ix_object_goal_area ON goal(area, status);

CREATE TABLE IF NOT EXISTS focus (
  id          TEXT PRIMARY KEY CHECK(id = 'current'),
  owner_ref   TEXT NOT NULL,
  revision    INTEGER NOT NULL,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  doc         TEXT NOT NULL
);
"""


def db_path() -> str:
    """Where the database lives.

    One environment variable, and a default that exists so the demo runs
    anywhere. one-creator resolves this through its Storage catalog instead —
    that layer answers "which bytes, under whose custody, recoverable how", and
    reimplementing it here would be copying the wrong thing.
    """

    pinned = os.environ.get("OC_OBJECT_DB_PATH")
    if pinned:
        return os.path.abspath(os.path.expanduser(pinned))
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "oc-goal", "oc.db")


def connect(path: str | None = None) -> sqlite3.Connection:
    """Open the database, creating the three tables once per process per path."""

    target = os.path.abspath(os.path.expanduser(path or db_path()))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    connection = sqlite3.connect(target, timeout=_BUSY_TIMEOUT_MS / 1000.0)
    try:
        connection.row_factory = sqlite3.Row
        connection.isolation_level = None
        connection.execute("PRAGMA busy_timeout=%d" % _BUSY_TIMEOUT_MS)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        resolved = os.path.realpath(target)
        if resolved not in _INITIALIZED:
            with _INIT_LOCK:
                if resolved not in _INITIALIZED:
                    connection.executescript(SCHEMA_SQL)
                    _INITIALIZED.add(resolved)
    except Exception:
        connection.close()
        raise
    return connection


@contextlib.contextmanager
def txn(connection: sqlite3.Connection):
    """Serialize a read-check-write sequence with an immediate transaction.

    This is what makes the compare-and-set one statement's worth of atomic
    rather than check-then-act: the revision comparison and the row replacement
    are inside the same `BEGIN IMMEDIATE`.
    """

    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    connection.commit()


__all__ = ["SCHEMA_SQL", "SOURCE_SCHEMA_VERSION", "connect", "db_path", "txn"]
