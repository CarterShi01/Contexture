# oc-goal — design

One real domain from [one-creator](https://github.com/CarterShi01/one-creator),
rebuilt on Contexture's four objects, sharing the same database as the original.

The point is not the Goal domain. It is that a domain with real persistence,
real constraints and a real cross-object invariant can be stated against
`Role` / `Skill` / `Tool` / `Resource` — and that doing so removes a whole layer
rather than renaming one.

---

## 1. Why this exists

Contexture's other reference application, `incident`, keeps its data in a
124-line fixtures module. That is the right shape for demonstrating disclosure
and the wrong shape for answering the question a business developer actually
has: *what happens to my model layer?*

one-creator has eleven first-class citizens behind an MCP server with 130 tools
resident in every session. Moving one of them here answers three things at
once:

- **Does the object model hold?** A domain with a primary key, compare-and-set,
  write-locked fields and a global invariant is a harder test than a fixture.
- **What does the gateway actually save?** The layer that disappears is
  measurable, not rhetorical — see §5.
- **What is missing?** Two things, named in §7, and both are framework gaps
  rather than porting mistakes.

---

## 2. The domain in one paragraph

An **Area** is attention that never ends: it holds a *budget* — a share of
attention — and a maintenance standard. A **Goal** ends: it holds a *horizon*,
which forces a review when it arrives, and criteria for success. Every goal
names exactly one area. **Focus** is a singleton: the current main thread and
not-doing list.

One entry carrying both shapes would mean "entrepreneurship expires in
2026-Q4", which is a distorted data model no presentation layer can fix. The
budgets of active areas must total 100 — a global invariant, checked across all
rows before any write lands.

---

## 3. Four layers, and the empty one

```
serve         contexture serve            reads pyproject, builds the server
disclosure    the five gateway tools      the framework's — nothing written here
domain        goal/     role, tools, skills, resources, model
              citizens/ what makes an object first-class
storage       db/       three sqlite tables, schema identical to oc.db
```

**The empty layer is the finding.** In one-creator it is:

| what | where | size |
| --- | --- | ---: |
| `@read(address=…, name=…, listing=…, priority=…)` | `goal/manager.py` | 5 methods' worth of decorator arguments |
| Manager → DomainSurface reflection | `domain/compiler/reflect.py` | 254 lines |
| surface → MCP registration | `brain-mcp/` | a registry, a persona gate, a validator |
| signature-vs-contract drift check | `domain/manager.py` | 134 lines |

Here a reference is a path through the role tree, and the surface is five tools
whatever the declaration contains. None of the above has an equivalent — not a
smaller version of it, none.

---

## 4. Three object models, and how they relate

The thing to get right before writing any code was what `Citizen`, `Role` and
one-creator's `GoalContext` are to each other. They are not layers of one
hierarchy; they sit at different **meta-levels**.

| | class/instance split | instances |
| --- | --- | --- |
| `Citizen` | real | `Area` has as many as there are areas |
| `Role` | degenerate | class and instance are one-to-one |

That is why `Citizen` does not and must not inherit `Role`: a row of data is not
a responsibility boundary, and making every area a node would put the size of
the data into the routing surface, which is precisely what the gateway exists
to keep out.

So the relationship is **projection, not inheritance**:

```
Citizen  ──── read three times ────▶  never subclassed
   │  shapes    → ObjectShapes resource
   │  written   → CitizenTool.target
   │  queried   → the tools' bodies
   ▼
oc.db
```

`Citizen` is one-creator's `domain/citizen.py`, ported without a line changed
except one `isinstance` check that referred to store classes this demo does not
carry. It is the debt-free part of that codebase and there was nothing to
improve by rewriting it.

### Where the write contract went

`Citizen.upsert` refuses to run outside an operation context:

```python
operation = current_operation()
if operation is None or operation.kind != "write" or operation.target is not cls:
    raise CitizenError(...)
unknown = set(changes) - set(operation.patch_fields)
```

In one-creator that context is established by `Manager.invoke`, and the spec it
carries comes from a `@write(...)` decorator. Neither survives: Contexture's
Role *is* the operation surface, and running a second one alongside it was the
thing to avoid.

But the guard checks the **spec**, never who established it. So the contract
moved onto the Tool, as class attributes beside the `invoke` they constrain:

```python
class UpsertGoal(CitizenTool):
    target       = Goal
    patch_fields = ("why", "area", "title", "horizon", "success")
    writes       = ("storage://oc.object-db#goal",)

    async def invoke(self, slug: str, why: str, ...) -> dict: ...
```

`invoke` is written by each subclass rather than generated by the base class,
because **its signature is the input schema**. Wrapping a `mutate()` behind
`**kwargs` would erase the schema; rebuilding the signature by reflection would
create a second copy of it that can drift. Detecting that drift is what
one-creator spends 134 lines on — writing `invoke` by hand makes those lines
unnecessary rather than ported.

---

## 5. Which node is which, and why

The four questions, applied to this domain:

| | question | here |
| --- | --- | --- |
| **child role** | a branch entered *instead of* its siblings? | none — changing a goal and reviewing one need the same tools |
| **skill** | a method, performed by the model, using the role's tools? | `review-the-attention-chain` |
| **tool** | computable deterministically? | the other eight |
| **resource** | already there, no arguments, stable URI? | `goal://focus`, `goal://objects` |

Two of those are worth their own note.

**`review` was a Tool that could not be written.** In one-creator it is a
`@compile` operation with `status="planned"` and a body that raises
`NotImplementedError`, and its docstring explains why: *"Material only, never a
conclusion: the join is deterministic and happens on the server, the judgement
is the model's job."* A capability whose judgement is the model's job is not a
Tool. As a Skill it works today, because every tool its procedure calls already
exists. Nothing was implemented to make that true; it was classified correctly.

**`goal://objects` did not exist at all.** one-creator publishes each domain as
three things — objects, operations, resources — and the object half never
reached an agent: field constraints lived only inside each write tool's input
schema, so nothing could answer "what is an Area" without first deciding to
change one. Contexture has no node type for a schema either, so it lands as a
Resource, where listing it costs one sentence and reading it costs the schema.

---

## 6. What was ported, and what was not

| from one-creator | lines | here |
| --- | ---: | --- |
| `domain/citizen.py` | 867 | verbatim |
| `domain/field.py` | 371 | verbatim |
| `domain/operation.py` | 268 | verbatim |
| `domain/document.py` | 161 | verbatim |
| `domain/schema.py` | 255 | verbatim |
| `domain/store.py` | 731 | the two injected shapes only |
| `domain/context.py` | 495 | the persisted half only — see below |
| `kernel/object_store.py` | 439 | three tables' DDL |
| `kernel/object_repository.py` | 239 | three tables' adapter |
| `goal/model.py` | 120 | verbatim |
| `goal/manager.py` | 288 | **dissolved** into tools + role |
| `domain/manager.py` | 471 | **not ported** |
| `domain/compiler/`, `surface.py`, `definition.py`, `refs.py` | ~600 | **not ported** |

Nothing was "improved" on the way across. The one place this demo is
deliberately not a copy is §7.

### The context split

`domain/context.py` holds two things with different reasons to change:

- **data** — what a Goal row stores in its `context` column: memory scopes,
  inheritance, explicit refs. Persisted, versioned, edited under CAS. **Ported**,
  as `citizens/context_config.py`.
- **compiler** — `ContextSource` / `ContextInventory` / `ContextPack` and
  `compile_context`, which turn one Goal *instance* plus a receiver and a budget
  into a trimmed pack. **Not ported**, because it is not a duplicate of anything
  here: it is a second disclosure axis Contexture does not have, and copying it
  in would settle a design question that should be answered deliberately.

---

## 7. Two known gaps

**Egress trimming is absent.** one-creator passes every record through an egress
port before it leaves the process — a cross-cutting boundary belonging to no
single citizen, injected by the host at registration. There is no host here to
inject one, so the tools return the row. Defensible for a single-principal demo;
not defensible the moment anything multi-tenant reads it. **This is the only
guarantee weaker here than in the original.**

**Post-write validators are empty.** one-creator points these at two scripts,
and the second belongs to a domain this demo does not have. What they guarded is
not all lost: the invariants that matter most are on the objects themselves, and
`Area`'s active budgets summing to 100 runs in `probe.check()` *before* the row
is written. Porting the rest is Phase 2.

---

## 8. Two things Contexture does not have

Found by doing this, not by reasoning about it. Both are framework gaps.

**Instance-level disclosure.** Contexture splits by structure — `ROUTE` and
`ACTIVE`. one-creator's context layer splits by *receiver and budget*:
`required` sources are kept, optional ones are cut to fit `environment.budget`,
and what was dropped is reported as `omitted` / `truncated`. Those are
orthogonal axes, and Contexture has no equivalent of the second. A `ContextPack`
is structurally a Role — guide → description, instructions → instructions,
sources → resources, sinks → tools — minus any way to say "this view is
trimmed".

**A live closed set in a schema.** `area: Area` in one-creator puts the current
active areas into the tool's schema as an enum, so a model cannot syntactically
name one that does not exist. Contexture derives schemas from type hints, which
cannot consult a store. The check survives here as a runtime rejection in
`UpsertGoal.invoke` — correct, but it costs a round trip where the original cost
nothing.

---

## 9. Sharing a database with one-creator

The three tables' DDL is copied column for column, and `user_version` is
deliberately never written — the original stamps it, which is right for the
owner of a thirteen-table schema and wrong for a three-table subset. Both
directions are therefore safe:

```
demo opens one-creator's oc.db    every CREATE is IF NOT EXISTS: a no-op,
                                  and the stamp stays at 3
demo creates its own database     three tables, user_version 0 — one-creator's
                                  own migration fills in the other ten
```

Concurrent writes are safe because compare-and-set is pushed into one
`BEGIN IMMEDIATE` transaction in `db/rows.py`, exactly as the original does.
Two servers writing the same row means the second one gets a `ConflictError`,
which is the intended behaviour rather than a race.

`OC_OBJECT_DB_PATH` points this at a real `oc.db`. Unset, it lands in a per-user
directory, so `python check.py` works on a machine that has never heard of
one-creator.
