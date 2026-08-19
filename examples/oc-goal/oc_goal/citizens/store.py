"""Persistence contracts for citizens whose truth lives in a database.

Ported from one-creator `domain/store.py`, keeping only the two shapes this
demo needs. The original carries four more — `YamlList` (one list in one file,
written by text surgery so the comments around it survive), `YamlDir`,
`YamlDoc` and `BodyFile` — for citizens whose truth is checked into git.

Area, Goal and Focus are none of those. Their truth is `oc.db`, so all three
declare an injected store and the implementation arrives at composition time.
The criterion the original states, unchanged:

    Is the truth in the repo?  Yes → the store carries its own implementation.
                               No  → declare the contract only, inject the rest.

This file is the second half of that split; `oc_goal/db/rows.py` is what gets
injected into it.
"""
import os

from . import atomic_file as _atomic

#: Where a relative script path is resolved from — the project root, three
#: levels up from this file. `ValidatorSpec` names its scripts relative to it,
#: the same way one-creator names them relative to the repository root. This
#: demo declares no validators yet, so nothing resolves against it today; it is
#: here because the two functions that would use it were ported whole rather
#: than hollowed out.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class StoreError(RuntimeError):
    """Write failed, or the stored document has the wrong shape. Never degrade
    silently: if it cannot be written, say so loudly."""


class InjectedStore:
    """A store whose implementation is injected at runtime.

    It reuses the same store interface `Citizen` expects, so the citizen needs
    no change. The five operations mean the same thing for a file and for a
    database; only "snapshot" differs, from file text to that one row:

        YamlList      snapshot(key) → the whole file's text   restore → write text
        InjectedStore snapshot(key) → that row's dict          restore → write row

    CAS is pushed down to the database rather than done here:
    `write_entry(key, entry, expected=)` passes the expected version down so the
    implementation compares it in one SQL statement. Comparing only in
    `_begin_write` is check-then-act, and two concurrent writes would both pass.
    """

    def __init__(self, name, key="ref"):
        self.name = name
        self.key = key
        self._impl = None

    # ── Injection ────────────────────────────────────────────────────────
    def bind(self, impl):
        """The composition root injects the implementation.

        `impl` must provide `rows()`, `get_row(key)`,
        `put_row(key, entry, expected)` and optionally `lock(key)`; without the
        last one an in-process lock is used.
        """
        self._impl = impl
        return self

    @property
    def impl(self):
        if self._impl is None:
            raise StoreError(
                "%s has no store implementation bound — a citizen whose truth is "
                "not in the repo gets one at composition time (see oc_goal/db/)"
                % self.name)
        return self._impl

    @property
    def path(self):
        """For the `file` field in return values. A database has no file, so give a
        readable identifier."""
        return getattr(self._impl, "label", None) or ("store://%s" % self.name)

    # ── Read ─────────────────────────────────────────────────────────────
    def read(self):
        return list(self.impl.rows())

    def document_errors(self):
        """Container contract: the database enforces its own schema, so there is no
        document shape to validate here."""
        return []

    def invalidate(self):
        invalidate = getattr(self._impl, "invalidate", None)
        if invalidate:
            invalidate()

    # ── Write ────────────────────────────────────────────────────────────
    def lock(self, key=None):
        own = getattr(self._impl, "lock", None)
        if own:
            return own(key)
        # No lock from the implementation: fall back to an in-process lock. This
        # is not cross-process exclusion — real exclusion comes from the
        # implementation's transactions; this only prevents in-process interleaving.
        return _atomic.file_lock(os.path.join(
            os.path.expanduser("~"), ".oc-injected-%s.lock" % self.name))

    def snapshot(self, key=None):
        """The rollback baseline is that row; None when absent."""
        return self.impl.get_row(key)

    def restore(self, value, key=None):
        restore = getattr(self.impl, "restore_row", None)
        if restore:
            return restore(key, value)
        self.impl.put_row(key, value, expected=None)

    def write_entry(self, name, entry, expected=None):
        """Returns whether it inserted. `expected` is the CAS expectation, compared by
        the implementation in one statement."""
        return self.impl.put_row(name, entry, expected=expected)


class InjectedDocumentStore:
    """Adapt one fixed row to the singleton Document store contract."""

    def __init__(self, name, key="current"):
        self.name = name
        self.key = key
        self._rows = InjectedStore(name, key="id")

    def bind(self, impl):
        self._rows.bind(impl)
        return self

    @property
    def path(self):
        return self._rows.path

    def read(self):
        row = self._rows.impl.get_row(self.key)
        if row is None:
            raise StoreError("%s singleton is missing" % self.name)
        return {key: value for key, value in row.items()
                if key not in ("id", "owner_ref", "revision", "created_at", "updated_at")}

    def document_errors(self):
        return []

    def invalidate(self):
        self._rows.invalidate()

    def lock(self, key=None):
        return self._rows.lock(self.key)

    def snapshot(self, key=None):
        return self._rows.impl.get_row(self.key)

    def restore(self, value, key=None):
        return self._rows.impl.restore_row(self.key, value)

    def patch(self, changes, order=()):
        old = self._rows.impl.get_row(self.key)
        if old is None:
            raise StoreError("%s singleton is missing" % self.name)
        document = dict(old)
        document.update({key: value for key, value in changes.items() if value is not None})
        document["revision"] = int(old["revision"]) + 1
        from datetime import datetime, timezone
        document["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self._rows.impl.put_row(self.key, document, expected=int(old["revision"]))
        return self.read()


__all__ = ["InjectedDocumentStore", "InjectedStore", "REPO", "StoreError"]
