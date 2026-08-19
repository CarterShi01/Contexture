# oc-goal — plan

Phase 1 is done and is deliberately a **port, not a redesign**: the point of
copying `domain/` across without improving it is that every later change has an
equivalence test behind it. Optimising first would have meant optimising against
nothing.

---

## Phase 1 — parity (done)

| | |
| --- | --- |
| scaffold | `contexture new oc-goal`, `assistant/` renamed to the role it holds |
| kernel | `citizens/` — citizen, field, operation, document, schema, store, context_config |
| storage | `db/` — three tables, DDL identical to `oc.db` |
| model | `goal/model.py` verbatim |
| nodes | `goal/{role,tools,skills,resources}.py`, `surface.py` |
| seed | `python -m oc_goal.seed`, refuses a database that already holds areas |
| check | `python check.py` — 34 assertions |

**Verified.** `contexture list` renders the role: 1 skill, 8 tools (4 read-only,
4 behind the writing door), 2 resources. `check.py` drives every node and
asserts the five guarantees that had to survive the contract moving off
`@write` and onto the Tool class: compare-and-set rejects a stale revision, the
closed-set check rejects an unknown area, a field constraint rejects a
too-short value, a created area is budget 0 / paused, an empty focus update is
refused.

**Not verified.** Anything needing the MCP SDK, which cannot be installed on the
machine this was built on: schema derivation from `invoke`'s type hints, the
gateway refusing a write sent through the read-only door, stdio framing. That
is the first item below and it is first for a reason.

---

## Phase 2 — the questions this demo exists to answer

### 2.1 Run it against a real host

`contexture serve`, connected to Claude Code, driven through
`discover → open goal → open the skill → invoke`. Three things are untested
until then, and one of them is load-bearing: **the writing door**. `check.py`
calls `invoke` directly, so nothing has yet refused a write sent through
`contexture_invoke_read_only`.

### 2.2 How much of the kernel was the stdlib constraint?

`field.py` (371) and `schema.py` (255) exist for one stated reason:

> Hand-written rather than pydantic: the declaration layer's dependency surface
> is a hard constraint (stdlib + PyYAML), and its gates run under a bare
> `python3`.

**That constraint does not exist here** — pydantic arrives with the MCP SDK. So:
re-express the fields as `Annotated[..., pydantic.Field(...)]` and measure what
is left. Six of `schema.py`'s seven reflection rules are things pydantic does
natively; the seventh is the live closed set, which needs framework support
either way (§2.4).

**This is the number that decides how the other ten domains migrate.** If 626
lines compress to under a hundred, rewriting one-creator's declaration layer
moves from "not worth it" to "the obvious next step". `check.py` is what makes
the experiment safe to run.

### 2.3 Instance-level disclosure

Port `domain/context.py`'s compiler half and answer the design question it
raises: a `ContextPack` is structurally a Role, so `open("goal/<slug>")` could
return one goal's compiled working context — its own facts, its area, related
work, trimmed to the receiver's budget.

Mechanically this is `Role.member()` resolving a slug that is not a static
member, and the instance never enters the skeleton, so it costs nothing until
someone opens it. What it needs first is where `receiver` and `budget` come
from. Three options, in order of preference:

1. process environment, as `principal` already is in one-creator
2. the SDK's `Context`, which a tool may annotate — costs this file its
   stdlib-only property
3. arguments — **rejected**: a model that can set its own budget has no budget

### 2.4 Feed the closed set into the schema

`Area.keys(status="active")` is a live set, and one-creator puts it into the
tool schema as an enum so a model cannot name an area that does not exist. Here
it is a runtime rejection, which costs a round trip.

Contexture derives schemas from type hints and cannot consult a store. Making
this work is a framework change, and it is general rather than one-creator's:
*a parameter whose valid values come from a callable, evaluated when the card is
built.* `ContextTree._tool_card` already calls `schema_of(tool)` on every open,
so the evaluation point exists; what does not is a way to declare it.

### 2.5 Egress trimming

The one guarantee weaker here than in the original (DESIGN §7). Needs a decision
before this demo is ever pointed at data belonging to more than one person.

---

## Phase 3 — what this says about the other ten domains

Not to be started before 2.2 produces its number, because that number changes
the answer. The shape is already visible, though:

- `Manager` dissolves into a Role plus one class per operation
- `Citizen` moves unchanged, or mostly unchanged if 2.2 goes well
- `Storage` does not move at all — it answers "which bytes, under whose custody"
  and Contexture holds none of your state
- `project` / `project-intent` / `workitem` are the first case where **child
  roles** are the right answer, because they are three authorities behind one
  line of work rather than three separate jobs

---

## Ground rules that held through Phase 1, and should keep holding

1. **One write path.** Everything goes through `Citizen.upsert`; tools shape
   arguments and nothing else. The moment a second path exists, the invariants
   are decoration.
2. **The DDL is copied, not designed.** Byte-identical schema is the entire
   basis for sharing a database, and sharing a database is what makes
   "equivalent" checkable.
3. **`src/contexture/` stays untouched by this demo.** Framework gaps get
   written down (DESIGN §8) and raised on their own, not patched from inside an
   example.
