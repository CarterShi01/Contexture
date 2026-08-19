# Handoff

**Written:** 2026-08-19, at v0.2.0. **Updated** the same day from a machine that
has the SDK, `uv`, `node`, both host CLIs, and a network — the previous version
of this file was written where none of that existed, and four of its items were
unverifiable there rather than undone.

Delete an item when it is done. Delete the file when it is empty.

---

## What has now been verified, and what that closes

| Was | Now |
| --- | --- |
| "the v0.2.0 gateway has never been executed against the real SDK" | **142 tests pass** against the real SDK, `tests/test_stdio_server.py` included — it runs here instead of skipping |
| "`description=` wins over `__doc__`" — reasoned from the API, never observed | **Observed.** `description=` wins; with neither, the description is `""` and there is no docstring fallback, so removing the closures' docstrings is safe *only* while every registration passes `description=` |
| registration-by-loop over `contract.GATEWAY` untested | all five register in contract order, each hint and each description identical to the contract |
| `_translated` renderings "audited by hand, not run" | run, and legible on the wire: a wrong ref returns what the role does hold plus the call that recovers; both wrong-door refusals name the other door; pydantic's argument errors name the field |
| `build_server()` returning one value, unpacking sites rewritten mechanically | executed |
| "whether a model *chooses* to navigate a gateway" — the top risk | **Claude Code did**, first try, zero errors. Recorded in [`docs/verification/hosts.md`](docs/verification/hosts.md) |
| scaffold verified only through `python -m contexture.cli` | verified through real `uv`; both claims below held |
| atlas mermaid unchecked | `node docs/atlas/check.mjs` — 8 blocks, all parse |

One defect was found and fixed on the way:
`test_contract.IndependenceTests.test_deciding_what_the_agent_reads_needs_no_wire`
asserted against the *process's* `sys.modules`, so it passed alone and failed in
the suite — the only red test on `master`. The claim it guards is true; it now
asks in a subprocess, the way `test_layering.py` already did.

---

## What ADR 007 has put back into question

Everything above was verified against the tree as it stood at `0920b5a`.
[ADR 007](docs/adr/007-the-role-axis-is-lazy-too.md) landed after it and changes
the first step of exactly the thing that run proved.

**The Claude Code result is the one to re-take.** It walked
`discover → open(role) → open(skill)`, because `discover` then returned every
role in the forest and the specialism was on that first list. It now returns the
roots only, so the same walk is `discover → open(root) → open(role) →
open(skill)` — one more hop before any work. The observation that the host
"declined to assert anything about a role whose card it had seen and not opened"
also refers to a card that now arrives one call later than it did.

None of this makes the recorded run wrong. It makes it a record of a different
navigation model, and `docs/verification/hosts.md` should say which one it is.

**Re-run and record:**

1. The same prompt as the recorded run. Does the host open the root and read its
   sub-roles, or does it stop at the roots and guess?
2. Whether the extra hop costs a turn or is folded into one.
3. The demo is only two levels deep. A host that copes there has not been shown
   to cope at four, which is the shape ADR 007 exists for.

Everything else above still holds: the SDK observations, the scaffold under
`uv`, the wire renderings, and the registration loop are untouched by ADR 007.

Two counts moved with it: the suite is **144** tests (was 142), and the atlas is
**9** mermaid blocks (was 8) — plate 05 was redrawn and gained a chart.

---

## 0. What changed in v0.2.0, and what it breaks

Read the ADRs for the reasoning; this is what a consumer notices.

| Gone | Replaced by | ADR |
| --- | --- | --- |
| `contexture.targets` (whole package) | nothing — it had no caller and no CLI entry point | [005](docs/adr/005-remove-the-target-adapters.md) |
| `TargetRenderError` (top-level export) | nothing | 005 |
| `Role.get_child` / `get_skill` / `get_tool` / `get_resource` | `Role.member(name)`, `Role.members()` | [006](docs/adr/006-errors-carry-facts-and-the-contract-is-one-module.md) |
| `NodeNotFoundError` subclassing `KeyError` | catch `NodeNotFoundError` or `ContextureError` | 006 |
| prose inside `NodeNotFoundError` | `.reason` (a `LookupFailure`) plus `.ref` / `.segment` / `.scope` / `.kind` / `.wanted` / `.known` | 006 |
| `Projection`, and `build_server()` returning a tuple | `build_server()` returns the `MCPServer`; ask it what it registered | 006 |
| `contexture_discover` returning the whole forest | it returns the roots; sub-roles arrive from `contexture_open`, one level per call | [007](docs/adr/007-the-role-axis-is-lazy-too.md) |
| `Transport` accepting `"sse"` | `"stdio"` or `"streamable-http"` | 006 |

`server/` gained `contract.py`, which owns every string an agent reads. The
version was bumped to `0.2.0` in `pyproject.toml` and `core/constants.py` so
that the ADRs, the atlas and the code agree.

---

## 1. Reserve the distribution name on PyPI

`contexture` is taken on PyPI by an unrelated 2014 project ("Magic Automatic
Logging Context", last release 2014-04-26, ~40 downloads a month). The name
cannot be reclaimed: PEP 541 requires the claimant's project to already meet
notability requirements and to show why a different name will not do, and a
framework with no users meets neither.

So the distribution name is **`contexture-mcp`** and the import name stays
`contexture`. That is already in `pyproject.toml`, the project template, and
every command in the README.

```bash
# 1. Create a PyPI account, enable 2FA (mandatory — PyPI refuses uploads without it).
# 2. Reserve the name with a real but deliberately pre-release upload:
uv build
uv publish --token <pypi-token>
```

Publish `0.2.0rc1` rather than `0.2.0`: a pre-release is not installed by
`uv add` unless asked for, so the name is held without inviting anyone to
depend on an API that has now had two breaking releases in a row. **A version
number can never be reused** — PyPI's deletion policy is permanent — so do not
burn `0.2.0` on a rehearsal.

**Done when:** `uv add contexture-mcp` resolves from a clean environment.

---

## 2. Finish the Codex row

**The risk this item existed for is retired.** Claude Code navigated the
gateway on the first attempt: `discover`, open the role, open the skill, three
read-only invokes through the right door with arguments taken off the cards,
then the runbook read by its own URI. Nine turns, zero errors. It also passed an
optional parameter nothing in the prompt suggested, obeyed a constraint that
exists only inside the skill, and refused to assert anything about a role whose
card it had seen and not opened. The full trace and the numbers are in
[`docs/verification/hosts.md`](docs/verification/hosts.md).

Two things that item asked are still open, and neither blocks anything:

- **Codex has never completed a run.** It registers against v0.2.0 with no
  Codex-specific artifact and is left registered on this machine, but the
  account limit that blocked it at v0.0.4 still blocks it — it resets
  **2026-08-21 12:02**. One command after that; see `scripts/verify_codex.md`.
- **`contract.unresolved()` has no field evidence.** The recovery sentence was
  written so a model that takes a wrong turn is told how to correct. The model
  never took one, so the sentence was never read by a model in anger. It is
  confirmed legible on the wire, which is not the same claim. Watch for it in
  the Codex run rather than manufacturing a wrong ref to watch it.

**Done when:** `docs/verification/hosts.md` has a Codex row that is not
⚠️ blocked.

---

## 3. Re-run the scaffold once the name is on PyPI

Verified through real `uv` on this machine, with one substitution: the
generated project depends on `contexture-mcp`, which item 1 has not published,
so a `[tool.uv.sources]` entry pointed that dependency at the local checkout.
Everything downstream of resolution is therefore proven; resolution from PyPI
is not.

Both claims the previous version of this item flagged **held**:

- **Claim A — `[tool.uv] package = false`.** uv honours the pyproject key, not
  just the `--no-package` flag. `uv sync` never attempted to build the project
  despite its having no `[build-system]`, and nothing named `my_context`
  appears in the resulting `site-packages`.
- **Claim B — the console script resolves in a non-package project.** `uv run
  contexture list` found the entry point from the dependency, and
  `find_project()` put the project directory on `sys.path` in time for the role
  module to import. `uv run contexture serve` was then driven by the official
  SDK client over real stdio: handshake at 2026-07-28, five tools listed, the
  generated role's skeleton, its skill, and its `ping` tool executing with a
  schema-derived argument. Server stderr was empty, so stdout carried protocol
  and nothing else.

**Done when:** the same five commands run with `uvx contexture-mcp new` at the
front and no `[tool.uv.sources]` substitution.

---

## 4. Decisions nobody has taken

### 4.1 ADR 002 — the per-call context object and the options struct

[`docs/adr/002-per-call-context-and-options.md`](docs/adr/002-per-call-context-and-options.md)
is **proposed, not accepted**, and needs one revision before it is actionable:
with the outbound half gone (ADR 003), the object it proposes is a pure
communication side channel — progress, host-visible logging, elicitation,
cancellation — and is *not* an authorization object. The brpc `Controller`
parallel that motivates it carries authentication; this one must not.

Fold in a two-phase shutdown — brpc's `Stop(closewait_ms)` then `Join()` — which
`ContextureApp` has no equivalent of. Irrelevant under stdio, real under
`streamable-http` with a tool call in flight.

The argument for doing it soon is about timing, not features: the position for a
framework-filled argument has to exist before people write tools, or adding it
later changes every signature in every project.

The ADR also records a latent SDK bug found while writing it —
`ToolManager.add_tool` warns and returns the existing tool on a duplicate name.
**Re-checked 2026-08-19 against the real SDK: the behaviour is unchanged, and
under the gateway it is unreachable.** Registering a second tool under a name
already taken still logs `WARNING Tool already exists` through `logging` — not
`warnings`, so it will not surface in a test that only captures those — keeps
the first implementation, and discards the second without raising. But the only
names ever registered are the five in `contract.GATEWAY`, they are distinct,
they come from one tuple, and no business tool reaches `add_tool` at all. Drop
this from the ADR's motivation; it argued for a defence the gateway already
provides structurally.

### 4.2 Where ownership is written down, once there are many declarations

Today a Role enumerates its members in its own class body: explicit and readable
at one Role, a line per member and a merge hotspot at fifty. Three shapes, and
this defines what every business project's directory tree looks like, so it
should not be settled by whoever implements it:

1. **Parent enumerates children** (today). Ownership at the Role. `O(n)` wiring.
2. **Child names its parent** (Django's foreign-key direction). `O(1)` per unit;
   the Role's surface is no longer readable in one place.
3. **Package position is ownership** (Django app, Scrapy `SPIDER_MODULES`).
   `O(0)`; the directory tree becomes the role tree. The scaffold already lays
   out one-package-per-role, so this is the direction it leans, but nothing
   enforces or uses it.

Scrapy, Django, Airflow and Nameko all converged on convention-based discovery
rather than central enumeration — but none of their units has an owner, and a
Tool does. That asymmetry is the whole difficulty.

### 4.3 Two roles may still declare the same tool name

Uniqueness is enforced *within* one role (`Role._require_unique_members`, which
is what `Role.member()` relies on) and across root names
(`ContextTree.__post_init__`). Nothing checks the forest as a whole.

Under the gateway this is no longer a startup crash — capabilities are addressed
by path, so `a/get_logs` and `b/get_logs` coexist correctly — which means the
old framing of this item is obsolete. **What remains is a usability question:**
two identically-named tools in different roles are indistinguishable in a
model's context once it has opened both. Whether to warn, and where, is open.

### 4.4 Whether a per-unit generator is worth it

Deliberately **not** built. Scrapy has `genspider` because a Spider carries
boilerplate that is easy to get wrong; a Contexture `Tool` is six lines and
copying a sibling beats recalling CLI flags. The one surviving argument is house
style across a large team. If that matters, the mechanism is identical to
`contexture new` and the marginal cost is small.

---

## 5. Documentation state

- **[`docs/atlas/index.html`](docs/atlas/index.html)** is current as of v0.2.0:
  nine plates, and **every number on it was re-measured against this commit**.
  It is hand-maintained and does not regenerate. After editing, run
  `node docs/atlas/check.mjs` (needs `npm install jsdom@22`) — a mermaid syntax
  error is otherwise invisible until someone opens the page, and one was caught
  that way while writing plate 07, and again while redrawing plate 05 for
  ADR 007 (`call` is a reserved word in a mermaid flowchart). **Run 2026-08-19:
  eight blocks all parsed at `0920b5a`; nine parse now.** ESM ignores `NODE_PATH`, so either install `jsdom` beside
  the script or run a copy of it from wherever `node_modules` is, passing the
  atlas and vendor paths as `argv[2]` and `argv[3]`.
- **[`docs/02-framework-layers.md`](docs/02-framework-layers.md)** carries a
  supersession banner and keeps its section 5 as a record of the deleted target
  adapters. Its capability matrix is still the clearest statement of what each
  runtime cannot express, which is the fact that motivated serving a declaration
  instead of rendering one.
- **Still thin:** neither design doc mentions the CLI or the scaffold, and no
  atlas plate covers how a business project is laid out — arguably the plate a
  newcomer needs first.
- **`README.md`** leads with `uvx contexture-mcp new`, which does not work until
  item 1 is done.
- **[`docs/verification/hosts.md`](docs/verification/hosts.md)** records a run
  against the pre-ADR-007 navigation model and does not yet say so. See
  "What ADR 007 has put back into question" above.

---

## 6. Two git warts, deliberately left alone

`fadb6d0` is titled "docs: state the programming model" and does say that — but
it also deletes fifteen files and 2816 lines, because a `git rm` had been staged
before it and `git commit` takes the whole index. The tree does not build at that
commit; `c295e0b` repairs it. Raised at the time, and the call was to leave
history alone. Recorded so a bisect across that range is not a mystery.

Second, smaller: **git does not track empty directories**, so deleting a package
leaves the directory behind on every machine that had checked out the old
version — and an empty directory is still importable as a namespace package.
`src/contexture/protocol/` survived ADR 003 that way and was found and removed
during ADR 005; `src/contexture/targets/` did the same thing minutes after being
`git rm`-ed. If a clone of this repo predates v0.2.0, check for both.
