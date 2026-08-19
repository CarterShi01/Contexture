# Handoff

**Written:** 2026-08-19, at `fd87f69` + the scaffold commit that follows it.
**Why this file exists:** the machine this work was done on has neither `uv` nor
the `mcp` SDK installed, and no PyPI credentials. Everything below is either
unverifiable here or is a decision nobody has taken yet. Each item says what to
run and how to know it worked.

Delete an item when it is done. Delete the file when it is empty.

---

## 1. Reserve the distribution name on PyPI — do this first

`contexture` is taken on PyPI by an unrelated 2014 project ("Magic Automatic
Logging Context", last release 2014-04-26, ~40 downloads a month). The name
cannot be reclaimed: PEP 541 requires the claimant's project to already meet
notability requirements and to show why a different name will not do, and a
framework with no users meets neither.

So the distribution name is **`contexture-mcp`** and the import name stays
`contexture`. That is already written into `pyproject.toml`, the project
template, and every command in the README.

**Do:**

```bash
# 1. Create a PyPI account, enable 2FA (mandatory — PyPI refuses uploads without it).
# 2. Reserve the name with a real but deliberately pre-release upload:
uv build
uv publish --token <pypi-token>     # publishes contexture-mcp 0.0.5
```

Consider publishing `0.0.5rc1` instead of `0.0.5`: a pre-release is not
installed by `uv add` unless asked for, so the name is held without inviting
anyone to depend on an API that is still moving. **A version number can never be
reused** — PyPI's deletion policy is permanent and irreversible — so do not burn
`0.1.0` on a rehearsal.

Rehearse on TestPyPI first if you like, but note it "occasionally deletes
packages and accounts".

**Then:** set up Trusted Publishing so no long-lived token is stored anywhere —
configure the publisher once on the PyPI project page against this repo's
release workflow, and `uv publish` needs no credentials from CI.

**Done when:** `uvx contexture-mcp new my-context` works on a clean machine.
Until then the README's quick start is aspirational and the "From a checkout"
path below it is the real one.

---

## 2. Run the full test suite with the SDK installed

`tests/test_projection.py` has never run here. It is the only test that fails,
and it fails at import: `ModuleNotFoundError: No module named 'mcp'`.

```bash
uv sync
uv run python run_tests.py
```

**Expect:** 133 tests, all passing.

**Status: done.** Run on this machine at v0.1.0 — `Ran 133 tests ... OK`. The
`test_projection.py` registration assertions this item warned about were
exercised and hold. `cli.py` and `test_scaffold.py` had to be migrated off the
removed `contexture.discovery` in the same pass (see ADR 004), and
`DEMO_TARGET` now points at `KubernetesPlatform`.

---

## 3. Verify the whole server layer actually serves

**Status: done for the SDK client; the two real hosts are still open.**

`contexture.server` has now been executed on this machine, repeatedly. The whole
gateway was rebuilt in v0.1.0 (ADR 004) and driven end to end:
`tests/test_stdio_server.py` launches the demo as a real subprocess and runs the
skeleton, opening a role, opening a skill, a validated read-only invoke, a
refused wrong-door write, an allowed write, and a resource read by URI.
`contexture list` and `contexture demo` were run by hand against the new tree.

What is still unverified is the part that matters most and cannot be checked
here: **whether Claude Code and Codex actually navigate a gateway.** ADR 004
lists this as the one risk with no mitigation — models are trained on native
tool calls, not on a generic dispatch tool, and the suite can prove the
mechanism works but not that a model will choose to use it.
`scripts/verify_claude_code.md` has been updated to the five-tool surface and is
what to run. `docs/verification/hosts.md` records the pre-gateway run and is
labelled as such.

```bash
uv run contexture demo                     # the bundled reference application
uv run python -m contexture.examples.incident.server   # the same thing, directly
```

Then connect a host and walk the trace in
[`src/contexture/examples/incident/README.md`](src/contexture/examples/incident/README.md):

```bash
claude mcp add --scope project contexture-demo -- uv run contexture demo
codex  mcp add                 contexture-demo -- uv run contexture demo
```

**Done when:** [`docs/verification/hosts.md`](docs/verification/hosts.md) has a
recorded run against the *current* code. The run recorded there predates both
the outbound removal and the CLI.

---

## 4. Verify the scaffold against real `uv`

`contexture new` was verified here end to end — generation, rendering, the
generated role importing, its tool executing, `contexture list` finding the
project by its `[tool.contexture]` table — but all of it through
`python -m contexture.cli`, never through `uv`.

Two claims in the generated `pyproject.toml` rest on uv behaviour that was read
from documentation, not observed:

```bash
uvx contexture-mcp new my-context   # or: uv run contexture new my-context
cd my-context
uv sync
uv run contexture list
uv run contexture serve
```

**Claim A — `[tool.uv] package = false`.** uv's docs describe the `--no-package`
*flag* ("disables using a build system … not a package, and will not be
installed into the environment") but do not document that pyproject key. If uv
does not honour it, `uv sync` may try to build the generated project as a
package and fail, since it has no `[build-system]`. If so, the fix is one of:
add the key uv actually wants, or add a minimal `[build-system]` and accept that
the project is installable.

**Claim B — the console script resolves in a non-package project.** `uv run
contexture serve` must find the `contexture` entry point from the dependency,
and `find_project()` must put the project directory on `sys.path` before the
role module is imported. The `sys.path` insertion is tested here; the
interaction with `uv run` is not.

**Done when:** the five commands above run clean, and `contexture serve` in a
generated project answers a host.

---

## 5. Decisions nobody has taken

### 5.1 ADR 002 — the per-call context object and the options struct

[`docs/adr/002-per-call-context-and-options.md`](docs/adr/002-per-call-context-and-options.md)
is **proposed, not accepted**. It predates ADR 003 and needs one revision before
it is actionable: with the outbound half gone, the object it proposes is a pure
communication side channel (progress, host-visible logging, elicitation,
cancellation) and is *not* an authorization object. The brpc `Controller`
parallel that motivates it carries authentication; this one must not.

Also fold in a two-phase shutdown — brpc's `Stop(closewait_ms)` then `Join()` —
which `ContextureApp` has no equivalent of. Irrelevant under stdio, real under
`streamable-http` with a tool call in flight.

The argument for doing it soon is unchanged and is about timing, not features:
the position for a framework-filled argument has to exist before people write
tools, or adding it later changes every signature in every project.

The ADR also records a latent SDK bug found while writing it —
`ToolManager.add_tool` warns and returns the existing tool on a duplicate name,
so a business tool named `contexture_discover` is silently dropped while
`Projection.business_tools` still lists it. That is worth fixing whether or not
the rest of ADR 002 proceeds.

### 5.2 ADR 004 — a lazy role tree behind a gateway surface

[`docs/adr/004-progressive-disclosure-as-a-lazy-role-tree.md`](docs/adr/004-progressive-disclosure-as-a-lazy-role-tree.md)
is **proposed** and landed alongside this work. It argues that disclosure does
not currently defer what it exists to defer — every tool and resource in the
forest is resident on the surface — and proposes a fixed gateway surface
instead of native per-tool registration.

It interacts with the scaffold in one place worth noting: the generated
template's `tools.py` presents a tool as a native MCP tool whose schema comes
from `invoke`. If ADR 004 is accepted, that framing changes, and so does the
comment in the template that explains it. Nothing else in the scaffold is
affected — `new`, `serve`, `list` and the project layout are orthogonal to how
the surface is shaped.

Sequence this against ADR 002: both touch `projection`, and ADR 004's gateway
split changes where a per-call context object would be injected.

### 5.3 Where ownership is written down, once there are many declarations

The business layer is expected to declare *many* Roles, Skills, Tools and
Resources, and that is where the bulk of the work sits. Today a Role enumerates
its members in its own class body, which is explicit and readable at one Role
but costs a line per member and makes that class a merge hotspot.

Three shapes, and this is a semantic decision that will define what every
business project's directory tree looks like, so it should not be settled by
whoever implements it:

1. **Parent enumerates children** (today). Ownership at the Role. `O(n)` wiring.
2. **Child names its parent** (Django's foreign key direction). `O(1)` per unit;
   the Role's surface is no longer readable in one place.
3. **Package position is ownership** (Django app, Scrapy `SPIDER_MODULES`).
   `O(0)`; the directory tree becomes the role tree. The scaffold already lays
   out one-package-per-role, so this is the direction it leans, but nothing
   enforces or uses it yet.

Scrapy, Django, Airflow and Nameko all converged on convention-based discovery
rather than central enumeration — but none of their units has an owner, and a
Tool does. That asymmetry is the whole difficulty.

### 5.4 Cross-graph name collisions surface at startup, not at declaration

Two roles may each declare a tool named `get_logs`. `build_graph` accepts it,
`discover` reports it, and only `projection` raises — that is, only when
something tries to serve. With many declarations across teams this will be a
routine failure at the worst moment.

The check belongs in `CapabilityGraph.__post_init__`, beside the root-name
uniqueness check that is already there, and the message should name both role
paths and both classes. Scrapy's duplicate-spider warning is the model for the
message; raising rather than warning is right here, because a silently dropped
tool is worse than a crash.

Not done because it is object-model work, and the brief was the scaffold.

### 5.5 Whether a per-unit generator is worth it

Deliberately **not** built. Scrapy has `genspider` because a Spider carries
boilerplate that is easy to get wrong; a Contexture `Tool` is six lines and
copying a sibling is faster than recalling CLI flags. The one argument that
survives is house style across a large team. If that turns out to matter, the
mechanism is identical to `contexture new` and the marginal cost is small.

---

## 6. Documentation that is stale or thin

- **`docs/01-role-object-model.md`** and **`docs/02-framework-layers.md`** were
  rewritten around the smaller core, but neither mentions the CLI or the
  scaffold. Design 02 in particular now describes a framework whose delivery
  story is absent.
- **`docs/atlas/index.html`** has nine plates and none of them covers the CLI or
  how a business project is laid out — arguably the plate a newcomer needs
  first. Every number on the page is measured, so adding a plate means
  re-measuring: 22 framework source files and 36 classes were the counts before
  `cli.py` and `templates/` landed.
  After editing, run `node docs/atlas/check.mjs` (needs `npm install jsdom@22`).
  That checker had to be patched to run on Node 22 at all.
- **`README.md`** leads with `uvx contexture-mcp new`, which does not work until
  item 1 is done.

---

## 7. One git wart, deliberately left alone

`fadb6d0` is titled "docs: state the programming model" and does say that — but
it also deletes fifteen files and 2816 lines, because a `git rm` had been staged
before it and `git commit` takes the whole index. The tree does not build at that
commit. The next commit, `c295e0b`, repairs it.

This was raised at the time and the call was to leave history alone. Recorded
here so that whoever bisects across that range knows why it breaks.
