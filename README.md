# Contexture

**An object model for agent context.**

Contexture is a compiler. You declare a role as a class — what it knows, what it can do,
what it may see — and it compiles that declaration into bounded, receiver-specific
surfaces: for an agent runtime, for another agent, or for a person.

It does not run your agents.

> **Status: pre-alpha. No code yet.** This README states the shape so it can be argued
> with before it is built.

## Mission

An agent's behaviour is decided by what it was handed: its instructions, its tools, its
memory, the slice of the system it is allowed to see.

That bundle is assembled by hand. Prose in a `CLAUDE.md`, a folder of skills, a list of
MCP tools, a prompt template per role — copied and forked per runtime. It is the least
structured, least verified, and most consequential part of the stack, and it stops being
true the moment the code changes. Silently, because nothing checks.

**Contexture makes it a program.**

A role is a class. What it knows, what it can do, and what it may see are declared
members of that class. Context is not a string you assemble before a call — it is the
class's declared state, compiled per receiver.

Two things follow, and they are why this is a compiler rather than a convention:

- **Progressive disclosure becomes a compile step.** Every member declares a bounded
  *handle* — what you can ask — separately from its unbounded *body* — the answer. Only
  handles stay resident. A receiver has a budget; what fits is computed, not curated.
- **Distribution becomes projection.** One class compiles to Claude Code, to Codex, to a
  raw MCP surface, or to a status line for a human. Nothing is written twice, and no
  target is dragged down to the weakest common denominator.

Underneath both, one invariant: **recompile, byte-compare, fail the build on drift.** A
generated interface that is allowed to go stale is worse than a hand-written one,
because it looks authoritative.

## The shape

```
Truth ──closure gate──▶ Surface ──approval gate──▶ Projection ──capability gate──▶ Receiver
declared truth          receiver-neutral IR        what this receiver actually gets
```

- A **declaration** states what a domain owns — and explicitly what it does not.
- A **surface** is the compiled, receiver-neutral IR. Deterministic bytes, content digest.
- A **projection** is that surface fitted to one receiver, reporting what it dropped and why.

A **receiver** is an identity with a capability matrix and a budget. **A person and an
agent runtime are the same kind of thing here** — that unification is the point of the
whole design.

A sketch of a declaration, so the claim is concrete:

```python
class Notes(Domain, ref="notes", truth=FileTree("storage://notes")):

    @read("notes://index")
    def index(self):
        """List note slugs and titles.          ← the handle: bounded, always resident

        Cheap. Prefer this over reading entries ← the body: unbounded, loaded on demand
        when deciding what to open.
        """

    @write(approval=HUMAN_CONFIRMATION)
    def save(self, slug, body): ...
```

Nothing in that class names a runtime, a budget, or a person. **A declaration does not
know who reads it** — which is exactly why it can be projected onto anyone.

Skills and MCP are the substrate, not our invention. Contexture compiles *to* MCP, Agent
Skills and AGENTS.md rather than competing with them.

## Where it sits

```
  your application
  agent runtime      LangGraph · CrewAI · ADK · Claude Code · Codex
▶ Contexture ◀       declaration → IR → per-receiver artifacts
  protocol           MCP · Agent Skills · AGENTS.md · A2A
  model
```

Structurally it is a compiler in the LLVM sense: many front-ends, one IR, many back-ends.
Its disclosure pass is a bundler's — tree-shaking and code-splitting under a budget. Its
installer is Terraform-shaped — a semantic plan, a transactional apply, an ownership
manifest, drift detection.

It is **not** an agent framework. No planner, no agent loop, no orchestration. It
produces what those consume.

## Non-goals

- **No execution loop.** That layer is crowded and well served.
- **No new protocol.** The standards exist and are governed; we compile to them.
- **No storage engine.** A store port and address closure checks, nothing more.
- **No business nouns in the kernel.** Ever.

## How this repo grows

A framework designed in the abstract encodes its author's guesses. This one is extracted
from practice: nothing lands here because it seemed like a good idea — it lands because
it already had to work somewhere, and then survived a second, unrelated shape.

**Two-caller rule:** no primitive becomes public API until two independent callers need it.

## Roadmap

- [ ] `v0.1` — kernel: declaration, member, receiver, selector, projection funnel. Pure
      functions, no I/O.
- [ ] `v0.2` — IR and CLI: `build`, `project`, `check`.
- [ ] `v0.3` — targets: Claude Code and Codex, with honest capability matrices and
      transactional install.
- [ ] `v0.4` — service mode: serve the compiled surface over MCP.
- [ ] `v1.0` — when two independent systems have shipped on it.

## The name

A *contexture* is the way parts are interwoven into a structure — not a pile of context,
but its construction. A class declares one; a projection is what a single receiver
receives of it.

## License

Apache-2.0
