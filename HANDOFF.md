# Handoff

**Written:** 2026-08-19, at v0.2.0 — after the three commits described below.

**Why this file exists:** the machine this work was done on has **no way to
install anything**. There is no `pip`, no `ensurepip`, no `uv`, no `pipx`; the
`mcp` SDK is not importable and cannot be made importable here. There are also
no PyPI credentials and no agent host to connect. Everything below is either
unverifiable on this machine or is a decision nobody has taken.

Delete an item when it is done. Delete the file when it is empty.

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

`server/` gained `contract.py`, which owns every string an agent reads. The
version was bumped to `0.2.0` in `pyproject.toml` and `core/constants.py` so
that the ADRs, the atlas and the code agree.

---

## 1. Run the two tests that have never seen this code — do this first

`tests/test_projection.py` fails at import here, and
`tests/test_stdio_server.py` skips itself, both because `mcp` is absent. **The
v0.2.0 rewrite of `contexture/server/projection.py` has therefore never been
executed against the real SDK.**

```bash
uv sync
uv run python run_tests.py
```

**Expect: 130 tests, all passing.** (112 run here, of which 10 skip without the
SDK; `test_projection.py` adds 19 that cannot even be collected here.)

What was verified here instead, and what that does and does not prove: a
throwaway stub of the SDK was written and the whole gateway driven through it —
registration order, all five `read_only_hint` values, that each description is
the one in `contract.GATEWAY`, four kinds of failed lookup, both wrong-door
refusals, and a resource read by URI. That proves the *wiring*. It proves
nothing about SDK compatibility, because the stub is not the SDK.

The specific things to watch, since they are the changed ones:

- **Registration is now a loop** over `contract.GATEWAY` rather than five
  `server.add_tool(...)` calls. If `add_tool`'s signature or its handling of
  `annotations` differs from what the old call sites relied on, all five break
  at once instead of one at a time.
- **The gateway closures no longer carry docstrings.** They previously had rich
  ones which the explicit `description=` overrode anyway. If the SDK does
  anything else with `__doc__` — validation, or a fallback path — that is now
  visible. *Confirming the old behaviour would be useful in itself:* the reason
  the docstrings were removed is the belief that `description=` wins, and that
  belief was reasoned from the API, never observed here.
- **`_translated` composes the message** from the exception's facts. Every
  assertion in `test_projection.py` that reads a `ToolError` message was audited
  by hand against the new renderings and should hold, but audited is not run.
- **`build_server()` returns one value, not a tuple.** All sixteen unpacking
  sites in `test_projection.py` were rewritten mechanically and checked by
  walking the file's AST for any remaining tuple target — but nothing there has
  been executed. This is the change most likely to fail loudly and least likely
  to fail subtly.

**Done when:** `run_tests.py` reports 130 passing with the SDK installed.

---

## 2. Reserve the distribution name on PyPI

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

## 3. Whether a model actually navigates a gateway

**This is the one open risk with no mitigation, and it outranks everything else
in this file.**

The mechanism is proven: `tests/test_stdio_server.py` launches the demo as a
real subprocess and walks the skeleton, opens a role, opens a skill, runs a
validated read-only invoke, gets a wrong-door write refused, runs an allowed
write, and reads a resource by URI. What that cannot prove is that a model will
*choose* to use it. Models are trained on native tool calls, not on a generic
dispatch tool behind which everything is hidden.

v0.2.0 makes this more testable than v0.1.0 did, and that is most of its point:
every failed lookup now ends by naming the call that recovers from it, so a
model that takes a wrong turn is told exactly how to correct. Whether it *does*
correct is the observation to make.

```bash
uv run contexture demo
claude mcp add --scope project contexture-demo -- uv run contexture demo
codex  mcp add                 contexture-demo -- uv run contexture demo
```

Walk the trace in
[`src/contexture/examples/incident/README.md`](src/contexture/examples/incident/README.md)
and `scripts/verify_claude_code.md`.

**Watch for, specifically:**

1. Does the host open a role before reaching for a tool, or does it try to
   invoke something it has not opened?
2. When it passes a ref that does not resolve, does the new sentence get it back
   on track in one turn? Record the actual exchange — this is the evidence
   `contract.unresolved()` was written for.
3. Does either host truncate the instructions? The preamble is 465 characters
   against Codex's 512-character self-contained window, and the roster is
   budgeted to 1200 more against Claude Code's 2KB — both numbers are read from
   documentation, not measured against a running host.

**Done when:** [`docs/verification/hosts.md`](docs/verification/hosts.md) has a
recorded run against v0.2.0. What is there now predates the gateway entirely.

---

## 4. Verify the scaffold against real `uv`

`contexture new` was verified here end to end — generation, rendering, the
generated role importing, its tool executing, `contexture list` finding the
project by its `[tool.contexture]` table — but all of it through
`python -m contexture.cli`, never through `uv`.

```bash
uvx contexture-mcp new my-context
cd my-context
uv sync
uv run contexture list
uv run contexture serve
```

**Claim A — `[tool.uv] package = false`.** uv documents the `--no-package`
*flag* but not that pyproject key. If uv does not honour it, `uv sync` may try
to build the generated project as a package and fail, since it has no
`[build-system]`. Fix is either the key uv actually wants, or a minimal
`[build-system]` plus accepting that the project is installable.

**Claim B — the console script resolves in a non-package project.** `uv run
contexture serve` must find the `contexture` entry point from the dependency,
and `find_project()` must put the project directory on `sys.path` before the
role module is imported. The `sys.path` insertion is tested here; the
interaction with `uv run` is not.

**Done when:** all five commands run clean and `contexture serve` in a generated
project answers a host.

---

## 5. Decisions nobody has taken

### 5.1 ADR 002 — the per-call context object and the options struct

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
**Re-check whether this still matters.** It was written when business tools were
registered natively; under the gateway only five names are ever registered, and
they are registered from one tuple. The failure it describes may no longer be
reachable.

### 5.2 Where ownership is written down, once there are many declarations

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

### 5.3 Two roles may still declare the same tool name

Uniqueness is enforced *within* one role (`Role._require_unique_members`, which
is what `Role.member()` relies on) and across root names
(`ContextTree.__post_init__`). Nothing checks the forest as a whole.

Under the gateway this is no longer a startup crash — capabilities are addressed
by path, so `a/get_logs` and `b/get_logs` coexist correctly — which means the
old framing of this item is obsolete. **What remains is a usability question:**
two identically-named tools in different roles are indistinguishable in a
model's context once it has opened both. Whether to warn, and where, is open.

### 5.4 Whether a per-unit generator is worth it

Deliberately **not** built. Scrapy has `genspider` because a Spider carries
boilerplate that is easy to get wrong; a Contexture `Tool` is six lines and
copying a sibling beats recalling CLI flags. The one surviving argument is house
style across a large team. If that matters, the mechanism is identical to
`contexture new` and the marginal cost is small.

---

## 6. Documentation state

- **[`docs/atlas/index.html`](docs/atlas/index.html)** is current as of v0.2.0:
  nine plates, and **every number on it was re-measured against this commit**.
  It is hand-maintained and does not regenerate. After editing, run
  `node docs/atlas/check.mjs` (needs `npm install jsdom@22`) — a mermaid syntax
  error is otherwise invisible until someone opens the page, and one was caught
  that way while writing plate 07.
- **[`docs/02-framework-layers.md`](docs/02-framework-layers.md)** carries a
  supersession banner and keeps its section 5 as a record of the deleted target
  adapters. Its capability matrix is still the clearest statement of what each
  runtime cannot express, which is the fact that motivated serving a declaration
  instead of rendering one.
- **Still thin:** neither design doc mentions the CLI or the scaffold, and no
  atlas plate covers how a business project is laid out — arguably the plate a
  newcomer needs first.
- **`README.md`** leads with `uvx contexture-mcp new`, which does not work until
  item 2 is done.

---

## 7. Two git warts, deliberately left alone

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
