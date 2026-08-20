"""Where a citizen's write contract lives once there is no Manager.

This is the one module importing both object models, and it exists to answer a
single question. `Citizen.upsert` refuses to run outside an operation context::

    operation = current_operation()
    if operation is None or operation.kind != "write" or operation.target is not cls:
        raise CitizenError(...)
    unknown = set(changes) - set(operation.patch_fields)

In one-creator that context is established by `Manager.invoke`, and the spec it
carries comes from a `@write(target=..., fields=..., precondition=...)`
decorator. Neither survives the move: Contexture's Role is the operation
surface, so a second one would be running alongside it.

But the guard checks the **spec**, never who established it — `operation_context`
is one line, `_CURRENT.set(spec)`. So the contract moves onto the Tool that
performs the write, as class attributes sitting beside the `invoke` whose
signature they constrain:

    @write(target=Goal, fields=("why", ...))     →     target = Goal
    def goal_upsert(self, slug, why, ...)              patch_fields = ("why", ...)
                                                       async def invoke(self, slug, why, ...)

Every structural guarantee is unchanged, because all of them are read off the
spec inside `Citizen.upsert`: the patch-field allowlist, compare-and-set, the
write-locked field merge, post-write validation, whole-file rollback.

**`invoke` is written by each subclass rather than generated here.** Its
signature *is* the input schema an agent is handed — the MCP layer derives one
from the type hints. A base class that wrapped a `mutate()` behind `**kwargs`
would erase the schema; one that rebuilt the signature by reflection would put
a second, drifting copy of it in the framework. That drift is exactly what
one-creator spends 134 lines of `Manager._validate_operations` detecting, and
writing `invoke` by hand is what makes those lines unnecessary rather than
ported.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar

from contexture import Tool

from .citizens import CitizenError, OperationSpec, ValidatorSpec, cas, operation_context


def utc_now() -> str:
    """The server clock, in the format every citizen's timestamps use."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class CitizenTool(Tool):
    """A Tool that performs one managed write against one citizen.

    `read_only` stays False, inherited from `Tool`. Being a `CitizenTool` and
    being behind the gateway's writing door are the same fact, and the gateway
    refuses a write sent through the read-only entry point — so it is declared
    once, here, rather than restated by every subclass.
    """

    #: The citizen this operation writes. `Citizen.upsert` compares it against
    #: itself, so naming the wrong class fails at the write rather than
    #: quietly touching another table.
    target: ClassVar[type]

    #: Exactly the fields this operation may change. Anything else in the
    #: changes mapping is refused — this is the allowlist that keeps a write
    #: away from a founder-only or server-managed field.
    patch_fields: ClassVar[tuple[str, ...]] = ()

    #: Post-write gates, run inside the citizen's lock; a failure restores the
    #: snapshot before the exception leaves `upsert`.
    #:
    #: Empty in this demo. One-creator points these at two scripts —
    #: `goal/goal-ops/validate_goal_objects.py` and project's cross-table
    #: check — and neither travels: the second belongs to a domain this demo
    #: does not have. What they guarded is not all lost, because the invariants
    #: that matter most are on the objects themselves (`Area`'s active budgets
    #: summing to 100 runs in `probe.check()` *before* the row is written).
    #: Porting them is Phase 2 work.
    validators: ClassVar[tuple[ValidatorSpec, ...]] = ()

    #: The storage addresses this operation writes, for an audit surface.
    #: Declarative only — the write goes through the citizen's own store.
    writes: ClassVar[tuple[str, ...]] = ()

    #: Compare-and-set. The default guards `revision`; the store pushes the
    #: comparison down into one SQL statement.
    precondition: ClassVar[Any] = cas()

    #: Which member of the write family this is. `Citizen.upsert` and
    #: `Document.patch` each check for their own, so the kind is what routes a
    #: spec to the right guard rather than a label on it.
    operation_kind: ClassVar[str] = "write"

    @classmethod
    def spec(cls) -> OperationSpec:
        """This tool's contract, in the shape the citizen's guard reads."""

        return OperationSpec(
            kind=cls.operation_kind,
            target=cls.target,
            patch_fields=tuple(cls.patch_fields),
            validators=tuple(cls.validators),
            writes=tuple(cls.writes),
            precondition=cls.precondition,
        )

    # ── helpers a write body needs ───────────────────────────────────────
    def row(self, key: str) -> dict | None:
        """One raw row of the target, undereferenced.

        The write path merges against the old value and has no use for an
        object: `Citizen.get` would resolve references and coerce data this
        operation is about to replace.
        """

        target = self.target
        return next((r for r in target.rows() if r.get(target.__key__) == key), None)

    def server_fields(self, existing: dict | None, expected: int | None) -> dict:
        """The `server_managed` values for this write.

        The body supplies the values and never the right to set them: these four
        fields are write-locked, so `Citizen._merge` takes them from here and
        ignores anything a caller put in `changes`.
        """

        if existing is not None and expected is None:
            raise CitizenError("expected_revision is required for an existing object")
        now = utc_now()
        current = existing or {}
        return {
            "owner_ref": current.get("owner_ref") or "principal://founder",
            "revision": 1 if existing is None else expected + 1,
            "created_at": current.get("created_at") or now,
            "updated_at": now,
        }

    def write(self, key: str, changes: dict, *, expected: int | None = None) -> dict:
        """Perform the managed write under this tool's own operation context."""

        existing = self.row(key)
        with operation_context(self.spec()):
            return self.target.upsert(
                key,
                changes,
                expected=expected,
                server=self.server_fields(existing, expected),
            )


class DocumentTool(CitizenTool):
    """A Tool that writes the one instance of a `Document`.

    A singleton has no primary key, so there is no key to pass and no revision
    for a caller to have read — `Document.patch` reads the current one and
    increments it. Everything else, including the operation context, is
    identical.
    """

    precondition: ClassVar[Any] = None
    operation_kind: ClassVar[str] = "document"

    def patch(self, changes: dict) -> dict:
        with operation_context(self.spec()):
            return self.target.patch(changes)


__all__ = ["CitizenTool", "DocumentTool", "utc_now"]
