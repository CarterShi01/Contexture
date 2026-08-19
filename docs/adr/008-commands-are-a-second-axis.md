# ADR 008 — Commands are a second axis, not a branch of the tree

**Status:** proposed — nothing here is implemented, and two decisions are still open
**Date:** 2026-08-20

**Extends:** [ADR 004](004-progressive-disclosure-as-a-lazy-role-tree.md) and
[ADR 007](007-the-role-axis-is-lazy-too.md). Neither is contradicted. Both
describe how a *model* reaches a capability; this one is about how a *person*
does, which is a plane those ADRs never had to name.

## Context

### The surface today is entirely model-controlled

Everything Contexture serves sits behind five gateway tools, and a model
chooses among them. That was the claim under test in `docs/verification/hosts.md`
and it held across three runs: the host navigates rather than giving up, one
`open` per level, no assembled refs, no guessed siblings.

Two things that surface cannot do:

**A person who already knows the destination still pays for the walk.** In
run 2 of the v0.2.0 + ADR 007 record, reaching a level-four tool took
`discover` plus four `open` calls before the first invoke. When the operator
already knows the answer is `payments/ledger/settlement/reconciliation`, those
five calls are the model rediscovering something a human could have typed.

**A workflow that spans unrelated branches has no home in the object model.**
`Skill` holds nothing — `declarative.collect(cls, member_types=())`, and its
docstring settles the matter: *"A method that needs its own tools to be kept
away from its siblings' tools is a child Role, not a Skill."* That answer is
containment, and containment is exclusive here because a ref **is** a path and
a node has exactly one. A procedure that names `assets/image-gen/generate_cover`
and `distribution/newsletter/send_draft` cannot own either, because each
already belongs somewhere else. The model can express **ownership** and it can
express **a procedure inside one role**. It cannot express **reference**.

A related smell already visible in the demo: skill procedures name sibling
tools by bare name (`Call get_pod_status`). That works only because those
cards arrive from the same `open(role)`. It stops working the moment a
procedure names anything outside its own parent.

### MCP has a control plane we have never used

The three primitives are split by *who decides*: tools are model-controlled,
resources are application-controlled, **prompts are user-controlled**.
Contexture occupies the first two and leaves the third empty.

Verified against the installed SDK (`mcp 2.0.0`, revision `2026-07-28`) rather
than from documentation:

| Mechanism | Shape |
| --- | --- |
| `prompts/list` | `ListPromptsResult{prompts, nextCursor, cacheScope}` — paginated |
| `prompts/get` | `GetPromptRequestParams{name, arguments: dict[str,str]}` |
| result | `GetPromptResult{messages: list[PromptMessage], description}` |
| message | `PromptMessage{role, content}`, `TextContent{type:"text", text}` |
| completion | `completion/complete`, `ref: PromptReference \| ResourceTemplateReference`, `argument:{name,value}`, optional `context.arguments` |
| completion result | `Completion{values: list[str] (max 100), total, hasMore}` |
| list-changed | `PromptListChangedNotification` — **only** delivered on a `subscriptions/listen` stream the client opted into via `promptsListChanged` |

Host-local command files (`.claude/commands/*.md`, `~/.codex/prompts/*.md`,
`.cursor/commands/*.md`) are the obvious alternative and are rejected: they are
generated artifacts in the user's repository, which is precisely what
`docs/verification/hosts.md` records this project as not needing.

### What the numbers say

Measured this session against the demo and against a synthetic forest, JSON
characters, not tokens.

**A direct hit is the cheapest path, not the most expensive one.**

| | demo (4 levels, fat nodes) | synthetic (4 levels, thin nodes) |
| --- | ---: | ---: |
| walking down (`discover` + `open`×4) | 3656 | 2696 |
| direct hit + signpost ancestry | 1352 | 511 |
| | **−63%** | **−81%** |

**Ancestry rendering, against the payload it decorates:**

| | demo | synthetic |
| --- | ---: | ---: |
| full ancestry (replay `open` at each level) | +206% | +724% |
| signpost (path + sibling counts, names only) | **+13%** | **+56%** |
| nothing | +0% | +0% |

Full ancestry is disqualified: it re-buys every level the direct hit just
saved. The signpost cost scales with **depth** (one line per level), never
with breadth — eight siblings and three siblings render the same line.

**Round trips are the larger saving, and were nearly missed.** Each navigation
call is a full model round trip that resends the conversation. Five navigation
calls become zero: completion and retrieval happen between the person and the
server, and the model first wakes up already at the destination.

**Memory is not a constraint at this scale.** A 300-role multi-headed forest
with distinct strings is 184 KB resident; `find()` on the deepest ref is ~23µs.
Server memory is cheap and unshared; model context is expensive and is the
bottleneck. The framework should keep making the expensive one lazy and carry
the cheap one itself.

**One defect surfaced on the way.** `ContextTree.skeleton()` — what
`contexture_discover` returns — has no budget and no truncation:

```python
return {"roles": [_card(root, root.name) for root in self.roots]}
```

`instructions.build()` cuts at `ROSTER_BUDGET` and points at `discover` as the
complete answer, but `discover` itself is uncapped. Invisible on a two-headed
demo; on a wide multi-headed forest it is the fixed cost of entering the
server, paid every time. Independent of everything else here.

## Decisions

### 1. The human-entry plane is MCP prompts

Nothing is generated into the user's repository. The server declares prompts;
every host that speaks MCP renders them into its own command menu.

### 2. The command surface must not scale with the tree

This is the requirement, and it is stronger than "keep the prompt count low".
`core/role.py` records that since the 2026-07-28 revision a server **may not
vary its surface as a consequence of an earlier call**. A surface that grows
with the forest eventually invites dynamic prompt registration, which is the
thing that revision forbids. Decoupling surface size from tree size means the
question never arises.

This also rules out one-prompt-per-role: 300 roles would mean 300 menu
entries, and `PromptListChangedNotification` cannot rescue it, since delivery
requires a subscription the client may never open.

### 3. `goto` — one parameterized prompt, with server-side completion

A single prompt taking a `ref`, with `completion/complete` doing prefix and
segment matching over the tree. The person types three characters and lands on
a level-four node; the menu stays one entry wide regardless of forest size.

Completion truncation follows the roster's rule — report the count and name
what recovers it — with one deliberate exemption: the roster cuts in whole
sibling groups because a *model* reading three of eight will take three for
the whole choice. Completion's consumer is a **person**, who will simply keep
typing. Completion therefore cuts by relevance, and this difference is to be
written down where the next reader will find it.

### 4. A direct hit carries a signpost ancestry

Path segments above the target, one line each, with sibling counts and no
names, plus explicit text that these are signposts and **not disclosed**: they
may be opened, nothing about their contents may be asserted. Same pattern as
the roster's truncation line — report the count, name the call that recovers
it, never the content.

This keeps ADR 004's rule intact on the new entrance. The direct-hit payload
is otherwise **field-for-field identical** to `contexture_open`, per the rule
`ContextTree.open` already states: *"Reaching a capability two ways and being
told two different things about how to call it is worse than either answer
alone."*

### 5. Composition across branches is reference, never containment

Making orchestrated roles into children of an orchestrating role **fails
silently**, which is worse than failing loudly. `_reject_cycles` walks only the
ancestor stack:

```python
if id(role) in stack:      # stack holds ancestors on the current path only
```

The same object under two different parents is a DAG, not a cycle, and passes.
The result is one node with two refs, which breaks three things at once: the
model sees two cards for one capability; "you have not opened X" stops meaning
anything when X has two doors; and the behaviour `hosts.md` values most — the
model declining to assert anything about `deployment-ops` because it never
opened it — depends on one capability having one location.

Note what is **already supported and needs nothing**: a role coordinating its
own subtree. `core/role.py` says so directly — *"A role that coordinates others
owns no tools at all, so every word here is orchestration."* Hierarchical
orchestration is containment and works today. Only cross-cutting orchestration
needs new machinery.

### 6. `Command` — a `ContextNode` that holds only refs and is not in the tree

`core/context.py` requires exactly three things of a `ContextNode`: `name`,
`description`, `_compile_active()`. It says nothing about membership, refs, or
belonging to a tree — *"The base class deliberately owns only the stable common
contract."* A `Command` fits without touching the base class.

It must **not** be a node in the forest. A command placed in the tree acquires
a path, a parent, and a slot in `discover`'s root cards, and the question of
where an orchestration belongs comes straight back. Instead the tree grows a
second field:

```
ContextTree:
  roots:    tuple[Role, ...]        # the capability graph — the model navigates it
  commands: tuple[Command, ...]     # the entry set    — a person triggers it
```

Commands reference the forest; the forest does not know commands exist. That
one-way dependency is the same discipline that keeps `core` unaware of refs and
unaware of the MCP SDK, applied a third time.

Consequences that follow rather than being designed in:

- **"Unconstrained by hierarchy or a common parent" is automatic**, because a
  command is not in the hierarchy.
- **A command cannot create a cycle**, because nothing references a command.
  Validation reduces to "every ref resolves", checked in
  `ContextTree.__post_init__` beside `_reject_cycles` and
  `_reject_ambiguous_names`. A workflow naming a node that does not exist must
  fail at startup, not when someone presses the key.
- **The question that dominated the discussion — where does an orchestration
  hang: nearest common ancestor, primary branch, or its own root — disappears.**
  A good abstraction dissolves the question rather than answering it better.

### 7. The two axes are the two MCP control planes

| Contexture | MCP | Triggered by |
| --- | --- | --- |
| forest (Role / Skill / Tool / Resource) | `tools` + `resources` | the model |
| commands | `prompts` | a person |

Not a coincidence. MCP's primitives are split by who decides; splitting by who
triggers lands on the same line.

### 8. One prompt per `Command`, plus `goto` as the generic escape hatch

This **reverses an earlier position in this discussion**, and the reason it
reverses is the point. The objection to per-workflow prompts was that 300 roles
would flood the menu. That objection assumed the prompt count was derived from
the tree. `Command` breaks that coupling: **the number of commands is authored,
not derived**. Eight commands is eight menu entries whether the forest holds
thirty roles or three hundred.

Named entries are also better for the person: the command name appears in the
menu and is discoverable, where `goto` requires knowing what to type first.

`goto` stays as the one generic entrance covering every node that no command
names. Adding a command is a code change and a restart — a new server version,
not a surface varying under a live connection, so decision 2 holds.

### 9. `Command` and `Skill` stay separate classes

They will look alike: `name`, `description`, `instructions`. The difference is
**who triggers it and where it lives** — a skill is navigated to by a model and
lives in the tree; a command is triggered by a person and lives outside it.
That difference must be stated in the docstring, or a later reader merges them
and pulls `Command` back into the tree, undoing decision 6.

## Consequences

- `core/context.py`, `core/role.py`: untouched.
- `core/`: gains `Command`. It holds ref **strings**, never object references —
  object references would turn the forest into a graph and make
  `_reject_cycles` meaningless.
- `tree.py`: gains a `commands` field, ref validation for it, a signpost
  renderer, and a full-ref enumerator (`roles_with_refs`'s sibling, reusing one
  walk) so completion can reach skills, tools and resources rather than roles
  alone.
- `server/contract.py`: owns every string these prompts put in front of a
  person or a model, beside `GATEWAY` — *"Two copies of a control's label is
  how the worse one ends up being the one that ships."*
- `server/projection.py`: registers prompts and the completion handler. Still
  the only module importing the SDK.
- `server/instructions.py`: unchanged. `PREAMBLE` is bound by Codex's
  512-character self-contained window, and commands are for people; a model
  cannot press them, so naming them there is pure cost.
- Card rendering for a command's refs likely belongs in `tree.py`, not in
  `Command._compile_active`, because a card needs a ref and a schema and `core`
  is not permitted to know either — the same line ADR 004 drew.
- **A command can cross a responsibility boundary, and that is allowed.**
  ADR 004's rule governs a model guessing, not a person composing. The reason
  to make `Command` a declared object rather than prose in a host-side template
  is exactly this: crossings become reviewable, testable and lintable. A
  command's compiled output should name the root branches it spans, so a
  crossing is visible rather than silent.

## Open questions

1. **How a command's refs expand.** Tools resolve to cards (a tool card
   already carries `input_schema` and `read_only`, so it is callable as-is) and
   roles must resolve to cards (expanding one would inline a whole branch).
   **Skills are genuinely undecided**: a card costs an extra `open` on a step
   the person has already committed to, while full text pays for branches the
   procedure may not take. A per-ref annotation distinguishing "certain" from
   "conditional" would express it, since the author knows which is which and
   the framework cannot — but it may be complexity bought too early.
2. **`skeleton()` truncation.** Agreed as a defect, unscheduled. Independent of
   the rest of this ADR.

## Not done here

- No code. No `Command` class exists.
- **Codex support is unverified.** `docs/verification/hosts.md` records its
  `mcp list` column as `Unsupported`, and its diagnosis run was blocked by an
  account limit through 2026-08-21. Whether Codex renders MCP prompts or
  services `completion/complete` is unknown; Claude Code is verified to render
  prompts as slash commands.
- **Multi-tenancy is out of scope, and would break the memory model.** The
  object graph is built at *import* time — `Role.__init_subclass__` runs
  `declarative.collect`, whose `_materialize` calls `value()` on each declared
  member class and shares the instance across every instance of the declaring
  class. `declaration` is a `ClassVar`, so the graph is process-wide, immutable
  and shared. That is what makes `Dispatch._derived`'s `id()` key safe and what
  makes the server lock-free. A per-connection tree cannot be added to this
  model; it would require a process per tenant. Confirmed out of scope: the
  forest is one multi-headed tree, identical for every connection.
- No decision on which commands `examples/oc-goal` should declare. Its
  `GoalDomain` is currently flat — eight tools, one skill, two resources, no
  child roles — so it does not yet exercise cross-branch composition. It will
  when `project` / `workitem` land, which its own comment already anticipates.
