"""Adapt the three tables to the injected-store contract.

Ported from one-creator's `brain-mcp/kernel/object_repository.py`, dropping the
`workitem` and `project` branches — those two carry indexed columns and a join
table this demo has no citizens for, and keeping them would mean keeping the
special cases without the objects that justify them.

The division of labour is the original's and is worth restating, because it is
what lets the citizen kernel stay free of SQL: **the database owns transactions
and compare-and-set; the model owns fields and invariants.** A repository only
projects indexed columns out of a JSON document and back.

Every row is stored twice over: once as `doc`, the whole declaration as JSON,
and once as the handful of columns that have to be queryable. `_decode` puts
them back together with the columns winning, so an index can never drift from
the document it was derived from.
"""
from __future__ import annotations

import contextlib
import json
from datetime import datetime, timezone

from ..citizens import ConflictError
from . import schema as db


#: Per table: the primary key, whether it carries a `context` object in its own
#: column, and which fields are lifted out of the document into columns.
TABLES = {
    "area": {
        "key": "slug",
        "context": False,
        "indexed": ("owner_ref", "status", "revision", "created_at", "updated_at"),
    },
    "goal": {
        "key": "slug",
        "context": True,
        "indexed": ("owner_ref", "area", "status", "revision", "created_at", "updated_at"),
    },
    "focus": {
        "key": "id",
        "context": False,
        "indexed": ("owner_ref", "revision", "created_at", "updated_at"),
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _principal_ref(value) -> str:
    text = str(value or "")
    return text if text.startswith("principal://") else "principal://%s" % text


class ObjectRows:
    """One table, behind the five operations an injected store calls."""

    def __init__(self, table: str, *, path: str | None = None):
        if table not in TABLES:
            raise ValueError("unsupported object table: %s" % table)
        self.table = table
        self.meta = TABLES[table]
        self.path = path
        #: What the citizen reports as the `file` a write landed in. A database
        #: has no file, so it gets the address one-creator's Storage catalog
        #: uses for the same bytes.
        self.label = "storage://oc.object-db#%s" % table

    def _connect(self):
        return db.connect(self.path)

    # ── Read ─────────────────────────────────────────────────────────────
    def rows(self):
        with contextlib.closing(self._connect()) as connection:
            found = connection.execute(
                "SELECT * FROM %s ORDER BY %s" % (self.table, self.meta["key"])
            ).fetchall()
            return [self._decode(row) for row in found]

    def get_row(self, key):
        with contextlib.closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM %s WHERE %s=?" % (self.table, self.meta["key"]),
                (key,),
            ).fetchone()
            return self._decode(row) if row is not None else None

    # ── Write ────────────────────────────────────────────────────────────
    def put_row(self, key, entry, expected=None):
        """Insert or replace one row under compare-and-set. Returns whether it inserted.

        The revision rules are the citizen's contract expressed in SQL: a create
        must be revision 1 and must not carry an expectation, a replacement must
        carry one and must increment by exactly one. Both comparisons happen
        inside the transaction, and the UPDATE repeats the expectation in its
        WHERE clause — so two concurrent writers cannot both pass the check.
        """

        if entry is None:
            with contextlib.closing(self._connect()) as connection, db.txn(connection):
                connection.execute(
                    "DELETE FROM %s WHERE %s=?" % (self.table, self.meta["key"]), (key,))
            return False

        values = self._columns(key, entry)

        with contextlib.closing(self._connect()) as connection, db.txn(connection):
            current = connection.execute(
                "SELECT revision FROM %s WHERE %s=?" % (self.table, self.meta["key"]),
                (key,),
            ).fetchone()
            created = current is None
            actual = int(current[0]) if current is not None else None

            if created:
                if expected is not None:
                    raise ConflictError("%s revision is %r, expected %r" % (key, actual, expected))
                if int(values["revision"]) != 1:
                    raise ConflictError("new %s revision must be 1" % key)
            else:
                if expected is None:
                    raise ConflictError("expected revision is required for %s" % key)
                if actual != expected:
                    raise ConflictError("%s revision is %r, expected %r" % (key, actual, expected))
                if int(values["revision"]) != actual + 1:
                    raise ConflictError("%s replacement revision must increment by one" % key)

            if created:
                columns = list(values)
                connection.execute(
                    "INSERT INTO %s(%s) VALUES(%s)"
                    % (self.table, ",".join(columns), ",".join("?" for _ in columns)),
                    tuple(values[column] for column in columns),
                )
            else:
                columns = [name for name in values if name != self.meta["key"]]
                sql = "UPDATE %s SET %s WHERE %s=?" % (
                    self.table,
                    ",".join("%s=?" % name for name in columns),
                    self.meta["key"],
                )
                parameters = [values[name] for name in columns] + [key]
                if expected is not None:
                    sql += " AND revision=?"
                    parameters.append(expected)
                if connection.execute(sql, parameters).rowcount != 1:
                    raise ConflictError("%s changed during update" % key)
        return created

    def restore_row(self, key, value):
        """Put a row back after a post-write validator failed.

        Deliberately not `put_row`: a rollback has to reinstate whatever
        revision was there before, which every rule in the normal write path
        exists to forbid. Keeping it as its own method means the bypass is
        named rather than available.
        """

        with contextlib.closing(self._connect()) as connection, db.txn(connection):
            connection.execute(
                "DELETE FROM %s WHERE %s=?" % (self.table, self.meta["key"]), (key,))
            if value is None:
                return
            values = self._columns(key, value)
            columns = list(values)
            connection.execute(
                "INSERT INTO %s(%s) VALUES(%s)"
                % (self.table, ",".join(columns), ",".join("?" for _ in columns)),
                tuple(values[column] for column in columns),
            )

    # ── Store-contract odds and ends ─────────────────────────────────────
    def lock(self, key=None):
        """No lock of our own: exclusion comes from `BEGIN IMMEDIATE` in `put_row`."""
        del key
        return _NOOP

    def invalidate(self):
        return None

    # ── Encoding ─────────────────────────────────────────────────────────
    def _columns(self, key, entry):
        """One entry → the column values for this table."""

        document = dict(entry)
        document.pop(self.meta["key"], None)
        context = document.pop("context", None)
        values = self._indexed(document)
        values[self.meta["key"]] = key
        values["doc"] = json.dumps(document, ensure_ascii=False, sort_keys=True)
        if self.meta["context"]:
            if not isinstance(context, dict):
                raise ValueError("%s.context must be an object" % self.table)
            values["context_json"] = json.dumps(context, ensure_ascii=False, sort_keys=True)
        return values

    def _indexed(self, document):
        values = {}
        for name in self.meta["indexed"]:
            value = document.get(name)
            if name == "owner_ref":
                value = _principal_ref(value or "founder")
            elif name == "revision":
                value = int(value or 1)
            elif name in ("created_at", "updated_at"):
                value = value or _now()
            elif value is None:
                raise ValueError("%s.%s is required" % (self.table, name))
            values[name] = value
        return values

    def _decode(self, row):
        document = json.loads(row["doc"])
        document[self.meta["key"]] = row[self.meta["key"]]
        for name in self.meta["indexed"]:
            document[name] = row[name]
        if self.meta["context"]:
            document["context"] = json.loads(row["context_json"])
        return document


class _Noop:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


_NOOP = _Noop()


__all__ = ["ObjectRows", "TABLES"]
