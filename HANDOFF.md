# Handoff

**Written:** 2026-08-19, at v0.2.0. **Updated** the same day from a machine that
has the SDK, `uv`, `node`, both host CLIs, and a network — the previous version
of this file was written where none of that existed, and four of its items were
unverifiable there rather than undone.

Delete an item when it is done. Delete the file when it is empty.

---

## A. The standing objective: one mental model a beginner can hold

**Raised:** 2026-08-20, against the second of the two sentences under
"Two models" in the README — *The framework model — how a developer uses it*.

This is not a documentation item. That sentence is the whole of what a business
developer reads before writing their first class, so whatever it gets wrong
they get wrong, and the cost lands again on every project built afterwards.
Everything else in this file is a release gate; this is the thing the releases
are for.

### The question, in the terms it was asked

1. **What does each layer expose to a user?** Read against OOP, and against
   brpc, where every kind of thing has exactly one way to be used and the name
   tells you which: a `Service` is inherited, an `Options` is filled in, a
   `Controller` is handed to you, a built-in service is fixed.
2. **After installing, what can a user see, and how do they write against it?**
3. **Which parts are meant to be subclassed, which are fixed, and which are
   written some other way?** Asked concretely: `core/model` looked like nothing
   but abstract bases; `mcp_interface`'s tool plane looked hardcoded; `Prompt`
   and `Resource` looked like a third thing again.

Question 3 was the tell. The answer at the time was **three different
mechanisms wearing one verb**: the README said business developers "extend"
the abstractions, and a reader who tried to extend a `Resource` got a class the
tree could never hold, in silence. `docs/case-studies/oc-goal` had already made
exactly that mistake and nothing in the suite caught it.

### What is settled, so nobody re-derives it

- **The verb.** [ADR 013](docs/adr/013-a-constructor-is-the-declaration.md)
  converged all five kinds onto one: every plane is a class handing its
  identity to a base constructor. What differs between planes is what they
  *carry*, not how they are written. README's "Three planes, one verb" states
  it, and the table there is the answer to question 3.
- **One import.** `Role`, `Skill`, `Tool`, `Prompt` and `Resource` all arrive
  from `contexture`. Reaching a layer path to publish a document was the last
  place the package's internal layering leaked into a user's first file.
- **One word, one meaning.** `roots` is the way in for a model, `publish` the
  way in for a person or a host. `surface` had meant three things.
- **The tree teaches the same story as the prose.** Six top-level entries, each
  with one audience; no `src/`; a generated project one level deep with each
  root role a top-level package, the way a Django app is.

### What is still open against it

1. **The assembly step has no place in the main path.** ADR 012 gave a
   capability `channels`, built by a `ControllerManager` before anything is
   served. A handle is a live object, so it cannot be named in
   `[tool.contexture]`, and `cli/project.py:resolve_target` accepts only a
   `Role`. So a project that needs a connection pool or a gateway **cannot use
   `contexture serve`** and must write the entry point the README opens by
   promising it will not need. Either the project table grows a way to name a
   factory, or the boundary is stated plainly and stops being a promise. This
   is the one that decides whether the answer to question 2 is one path or two.
2. **The scaffold teaches only the half that has no connections.** It shows
   `roots` and `publish` and says nothing about registration. Whether that is
   right is downstream of item 1.
3. **"Two ends written by hand, everything between them discovered" still opens
   with "The verbs differ because the counts do."** There is one verb now. The
   paragraph carries the principle that `roots` and `publish` are authored and
   the forest is discovered, which is worth keeping; the sentence in front of
   it is left over from before ADR 013.

**Done when:** a reader who has just installed the package can answer, without
opening an ADR — what do I subclass, what do I hand to the framework, and where
does anything that must exist before serving get built.

---

## What has now been verified, and what that closes

| Was | Now |
| --- | --- |
| "the v0.2.0 gateway has never been executed against the real SDK" | **149 tests pass** against the real SDK, `tests/test_stdio_server.py` included — it runs here instead of skipping |
| "`description=` wins over `__doc__`" — reasoned from the API, never observed | **Observed.** `description=` wins; with neither, the description is `""` and there is no docstring fallback, so removing the closures' docstrings is safe *only* while every registration passes `description=` |
| registration-by-loop over `contract.GATEWAY` untested | all five register in contract order, each hint and each description identical to the contract |
| `_translated` renderings "audited by hand, not run" | run, and legible on the wire: a wrong ref returns what the role does hold plus the call that recovers; both wrong-door refusals name the other door; pydantic's argument errors name the field |
| `build_server()` returning one value, unpacking sites rewritten mechanically | executed |
| "whether a model *chooses* to navigate a gateway" — the top risk | **Claude Code did**, first try, zero errors, three runs across two navigation models. Recorded in [`docs/verification/hosts.md`](docs/verification/hosts.md) |
| ADR 007's predicted extra hop, and whether it costs a turn | It does not happen on a small forest: `discover` answers with the roots while the roster keeps listing, so the opening text already carries the ref and the host skips `discover`. Seven calls where the eager skeleton took eight |
| "a host that copes at two levels has not been shown to cope at four" | Shown. 26 roles, four levels, roster cut above the branch that mattered: one `open` per level, seven calls, zero errors, no assembled refs and no guessed siblings |
| the roster under a budget it cannot meet | **Was broken, now fixed.** It stopped inside a sibling group — three of a role's eight sub-roles, with nothing saying the group was cut. Whole groups now, roots cut last and pointed at `contexture_discover`. `RosterTests` holds it |
| scaffold verified only through `python -m contexture.cli` | verified through real `uv`; both claims below held |
| atlas mermaid unchecked | `node docs/atlas/check.mjs` — 9 blocks, all parse |

One defect was found and fixed on the way:
`test_contract.IndependenceTests.test_deciding_what_the_agent_reads_needs_no_wire`
asserted against the *process's* `sys.modules`, so it passed alone and failed in
the suite — the only red test on `master`. The claim it guards is true; it now
asks in a subprocess, the way `test_layering.py` already did.

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

## 0b. v0.5.0: the class-body front end is gone

[ADR 013](docs/adr/013-a-constructor-is-the-declaration.md) has the reasoning.
What a consumer notices:

| Gone | Replaced by |
| --- | --- |
| `core.model.declarative` (whole module) | a constructor: `super().__init__(name=..., description=..., ...)` |
| `Declaration`, `DeclaredMember` | nothing — the class body is not read |
| class name → node name, docstring → description | stated explicitly |
| `attr = SomeTool` in a Role body | `tools=[SomeTool()]` in its constructor |
| `Prompt` / `Resource` refusing a subclass | they are subclassed like everything else |
| `ControllerManager.register` / `register_all` | `register_role` / `register_skill` / `register_tool` |
| `discover` answering `{"roles": [...]}` | `{"roles", "skills", "tools"}` — the same three keys `open` uses |
| `open` answering `sub_roles` | `roles` |

**Three things still need a machine this one is not.** This checkout has no
`mcp`, no `pip`, no `uv`, and no network, so:

1. **The five SDK-backed test modules never ran.** `test_app`, `test_binding`,
   `test_channels`, `test_identity`, `test_inspection` fail to import here, and
   three `test_scaffold.InspectFallbackTests` cases fail for the same reason —
   the same eight as before this work started. Everything the refactor touched
   is covered by the modules that *do* run, and all of those pass; the wire
   itself is unverified. Run `python run_tests.py` where the SDK is installed.
2. **The host verification is against a payload shape that no longer exists.**
   `docs/verification/hosts.md` records Claude Code navigating `sub_roles`;
   `discover` now answers with three keys. Re-run
   `docs/verification/verify_claude_code.md` before trusting that row.
3. **`docs/case-studies/oc-goal` was deliberately left on the old syntax.** Its
   seven subclass points still use class-body declarations, so `check.py` and
   `contexture list` will fail there. The business-contract pattern it relies on
   — `target`, `writes`, `precondition` as plain class attributes on a `Tool`
   subclass — still works and is pinned by a test; only the identity fields and
   the member lists move into constructors.

---

## 0c. v0.6.0: navigation is part of the kernel

[ADR 014](docs/adr/014-navigation-is-part-of-the-kernel.md) has the reasoning.
What a consumer notices:

| Gone | Replaced by |
| --- | --- |
| `contexture.core.disclosure` (package) | `contexture.core.model.tree` |
| `core.mcp_interface.tool.GATEWAY` / `GATEWAY_TOOLS` | `core.model.system_api.GATEWAY` / `GATEWAY_TOOLS` |
| `GatewayTool` | `SystemTool` (in `core.model.system_api`) |
| `server.messages.unresolved` / `wrong_door` / `command_taken_by_a_person` | `core.model.system_api.unresolved` / `wrong_door` / `taken_by_a_person` |
| `ContextTree(roots=..., schema_of=...)` | `ContextTree.of(...)` or `manager.sealed(schema_of=...)`; `roots` is a property |
| `register_root` imported from `tree` | from `core.model.manager` (still re-exported by `tree`) |
| `Role.compile("active")` returning four keys | it now carries `ref` and its members' cards |
| `_compile_active(self)` | `_compile_active(self, view)` — only relevant to a subclass that overrode it |

`contexture.server` still forwards the entry-point names, so a caller that asks
`contexture.server` what is on the wire is unaffected.

**What this buys, and what it retires.** `tests/test_system_api.py` runs the
whole agent trace — discover, open a root, open a specialism, open a skill,
three read-only invokes — plus both wrong-door refusals, wrong refs, signposts,
reserved nodes and statelessness, **importing no `mcp`**. The five SDK-backed
modules still cannot run without the SDK, but they are no longer where the
behaviour lives: what is left in `test_stdio_server.py` is the set of claims
that genuinely need a wire.

## 0d. `tests/channels_fixture.py` never made it through v0.5.0

**Found while verifying v0.6.0, and it predates it.** The fixture still declares
its capabilities in the class-body style ADR 013 deleted:

```python
class NotifySquad(Tool):
    name = "notify_squad"        # a class attribute, not a constructor
    read_only = False
```

So `import tests.channels_fixture` raises `TypeError: Role.__init__() missing 3
required keyword-only arguments`, and `test_channels.py` cannot run **even with
the SDK installed**. It was invisible because the module fails to import for the
SDK's absence first, on every machine that has looked at it so far.

Six declarations to migrate: `NotifySquad`, `WhereAmI`, `Runbook`, `Escalate`,
`Escalation`, `Operations`. Its `manager.register(...)` calls were already
corrected to `register_role` in the v0.6.0 commit; the constructors were not,
because they cannot be verified from a machine without the SDK.

**Done when:** `python run_tests.py` on a machine with the SDK reports no error
from `test_channels`.

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
  **2026-08-21 12:02**. One command after that; see `docs/verification/verify_codex.md`.
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

### 4.1 ADR 002 — the options struct (Decision A is parked)

**Decision A — `ToolContext` — is parked, with the reason recorded in the ADR.**
It was written before the gateway, and the gateway removed its premise: a
business tool that annotates the SDK's `Context` already gets progress,
host-visible logging, elicitation and `request_id`, over real stdio, with the
parameter kept out of the derived schema. What the decision would still buy is
one line of import — business code naming `contexture.server` instead of
`mcp.server.mcpserver` — for code that does not exist yet: no tool in the
examples, the scaffold or the tests takes a `ctx`.

Waiting costs nothing mechanically. A tool annotating the SDK's `Context` keeps
working if Contexture later passes a `ToolContext` subclass, because nothing
type-checks the injected object. The ADR's timing argument was wrong about
that, and the revision note says so, along with the route to take if the
decision is ever taken — subclass in `server/`, built in `_invoke`, about forty
lines. Take it when a tool actually wants progress or elicitation, and the
shape will follow a requirement instead of a guess.

One piece was done because it had a victim already: opening a tool used to
disclose `parameters()`, read off the signature, so a tool taking a `ctx` named
an argument its own schema rejected — and the two ways to reach a tool
disagreed about how to call it. Opening one now answers with the same
`input_schema` its card carries.

**Decision B — `ContextureOptions` — is done**, in v0.5.0 and
[ADR 011](docs/adr/011-identity-is-the-frameworks-permission-is-not.md). All
three claims held: the stdio branch really does discard kwargs, `stateless_http`
is pinned rather than offered, and `host` defaults to loopback. Two checks were
added that the ADR had not anticipated — a non-loopback bind must state its
allowed hosts or origins, because the SDK silently stops protecting one, and it
must state either `auth` or `allow_anonymous`.

### 4.2 Two roles may still declare the same tool name

Uniqueness is enforced *within* one role (`Role._require_unique_members`, which
is what `Role.member()` relies on) and across root names, of every kind
(`ControllerManager._register`). Nothing checks the forest as a whole.

Under the gateway this is no longer a startup crash — capabilities are addressed
by path, so `a/get_logs` and `b/get_logs` coexist correctly — which means the
old framing of this item is obsolete. **What remains is a usability question:**
two identically-named tools in different roles are indistinguishable in a
model's context once it has opened both. Whether to warn, and where, is open.

### 4.3 Whether a per-unit generator is worth it

Deliberately **not** built. Scrapy has `genspider` because a Spider carries
boilerplate that is easy to get wrong; a Contexture `Tool` is six lines and
copying a sibling beats recalling CLI flags. The one surviving argument is house
style across a large team. If that matters, the mechanism is identical to
`contexture new` and the marginal cost is small.

---

## 5. Documentation state

- **[`docs/atlas/index.html`](docs/atlas/index.html)** is current as of v0.5.0:
  ten plates. Plate 04 was **rewritten for ADR 013** — it now shows a
  constructor and the registration-time build rather than the class-body
  collection — and the `model/` file list and the module-dependency graph were
  updated with it. The other numbers on it were re-measured against the v0.5.0
  tree; the ones plate 04 touches were re-measured again after ADR 013.
  It is hand-maintained and does not regenerate. **It carries no changelog** —
  it states the design as it is now, and the history lives in `docs/adr/`,
  which is dated by design where the atlas is not. After editing, run
  `node docs/atlas/check.mjs` (needs `npm install jsdom@22`) — a mermaid syntax
  error is otherwise invisible until someone opens the page, and one was caught
  that way while writing plate 07, and again while redrawing plate 05 for
  ADR 007, and a third time while redrawing plate 04 for ADR 013 — `call` is a
  reserved word in a mermaid flowchart and it has now cost two blocks.
  **Run 2026-08-20: all blocks parse.** ESM ignores `NODE_PATH`, so either install `jsdom` beside
  the script or run a copy of it from wherever `node_modules` is, passing the
  atlas and vendor paths as `argv[2]` and `argv[3]`.
- **[`docs/02-framework-layers.md`](docsit/02-framework-layers.md)** carries a
  supersession banner and keeps its section 5 as a record of the deleted target
  adapters. **Its section 4 was rewritten for ADR 013** and now describes the
  constructor, what is no longer inferred, and why nothing exists until it is
  registered. Its capability matrix is still the clearest statement of what each
  runtime cannot express, which is the fact that motivated serving a declaration
  instead of rendering one.
- **Still thin:** neither design doc mentions the CLI or the scaffold, and no
  atlas plate covers how a business project is laid out — arguably the plate a
  newcomer needs first.
- **Not written yet:** `spec/`, the language-neutral fixtures the README's
  *Three languages, one behaviour* section describes. Until it exists, the
  cross-language contract is prose, and prose is exactly what a port drops
  quietly.
- **`README.md`** leads with `uvx contexture-mcp new`, which does not work until
  item 1 is done.
- **[`docs/verification/hosts.md`](docs/verification/hosts.md)** now holds three
  records, newest first, each naming the navigation model it verified. The
  v0.2.0 one is kept as recorded rather than updated: `discover` answered with
  the whole forest when it was taken. **All three predate ADR 013**, which
  changed the payload keys — see item 0b.

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
