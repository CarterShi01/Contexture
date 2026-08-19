# ADR 006 — Errors carry facts, and the contract is one module

**Status:** accepted, implemented in v0.2.0
**Date:** 2026-08-19

## Context

Asking what the `server` layer is *for* produced a better answer than "it
translates the tree into an MCP server". If it were only translation it would
be about eighty lines. What it actually holds is three things with three
different reasons to change:

| | changes when | modules |
| --- | --- | --- |
| what the agent reads | the way an agent is taught to walk the tree changes | — |
| fitting that to a host | Claude Code or Codex ships a release | `instructions` |
| hanging it on the wire | the SDK changes | `projection`, `app` |

The first had no module. Nobody owned "what the agent reads", so it scattered,
and the scattering had consequences.

**Two descriptions per entry point.** Each gateway closure carried a detailed
docstring and each `add_tool` call carried a shorter, differently-worded
`description=`. The explicit argument wins, so the better text — including
`contexture_open`'s "Pass a `ref` taken from a card; never assemble one", which
is the load-bearing rule of the whole navigation model — was the copy that did
not ship.

**Three copies of the ref rule**, in `PREAMBLE`, in a tool description, and in a
docstring, each worded differently.

**And the sentences that mattered most could not be written at all.** When a
lookup failed in `contexture.tree`, the message was baked at the raise site:

    No root role named 'nobody'. This server serves: team.

The useful half is missing — *call `contexture_discover` to see each one with
the ref that opens it* — and it is missing because the tree does not know the
gateway tool names and must not. The layer that hits the failure cannot write
the sentence; the layer that can write it was not in the call.

Underneath that sat a second problem. One string was serving two audiences: a
developer reading a traceback, who wants to know which call site and which
object, and an agent that is expected to read the failure and pick again, which
wants to know what *is* available and what to call next. Those want different
content and change for different reasons. `NodeNotFoundError.__str__` existed
only to fight the consequence — it overrode `KeyError`'s repr, which was
quoting the agent's sentence.

A third thing surfaced while fixing this. `Role` enforces that its members are
uniquely named *across kinds*, and the comment says why: "a member's name is the
last segment of the reference that addresses it." It paid the whole cost of
that invariant and then declined to offer the operation it buys — lookup lived
in `tree._member(role, name)`, a function whose signature contains no tree
concept at all, only a `Role` and a bare name. Meanwhile `Role.get_child` and
`get_skill` had no callers anywhere, and `get_resource` keyed by URI while its
three siblings keyed by name.

## Decision

**Errors carry facts; each audience renders its own sentence.**
`NodeNotFoundError` holds a `LookupFailure` reason and the facts around it —
`ref`, `segment`, `scope`, `kind`, `wanted`, `known` — and no prose. Its
`__str__` is a terse field dump for a traceback.

Exceptions already flow upward, so this needs no injection and no callback: the
exception object is the transport, and `projection._translated` — which was
already the single point where a Contexture failure becomes something an agent
reads — renders it. It was handed a finished string before; now it is handed
the facts.

**`server/contract.py` owns everything the agent reads**: the five entry-point
names, each one's description stated once, `PREAMBLE`, the ref rule, and
`unresolved()` / `wrong_door()`. `projection` registers by looping over that
tuple rather than through five hand-written `add_tool` calls. `instructions`
imports the text and owns only the budgeting.

**`Role` claims the lookup its own invariant enables.** `Role.member(name)` is
cross-kind because the uniqueness rule is cross-kind, and `Role.members()` is
the one definition of "what this role holds" — used by the uniqueness check, by
`member()`, and by anything walking a role. `tree._member` is gone; `find()`
calls `node.member(segment)` and attaches the whole reference on the way back
up, because the path is the one fact only the tree has.

**The four `get_*` accessors are removed** — not because lookup leaves `Role`,
but because they were the wrong lookups.

`contexture.server`'s facade resolves exports lazily, so `contract` and
`registration`, which do not import the SDK, stay importable and testable
without one.

## Consequences

- Every rendering of a failed lookup now ends by naming the call that recovers
  from it, and a test asserts that for every `LookupFailure` member — both that
  a rendering exists and that it names a gateway tool. Neither could have been
  written before: the branch did not exist in one place to test.
- **Breaking change.** `NodeNotFoundError` no longer subclasses `KeyError`.
  It was kept so `except KeyError` would still catch; with the payload now
  structured and `WRONG_KIND` meaning "you asked for a tool and this is a
  resource", the `KeyError` reading had stopped being true. The `__str__`
  override that existed to defeat `KeyError`'s repr goes with it.
- `Role.get_child`, `get_skill`, `get_tool`, `get_resource` are gone, replaced
  by `member()` and `members()`.
- The four member kinds were enumerated by hand in seven places; `members()`
  collapses two of them, including the pairing of the uniqueness check with the
  traversal it constrains.
- `projection.py` drops from 294 to 223 lines and stops holding any text an
  agent reads. `instructions.py` drops to 74 and holds only two numbers with an
  expiry date.
- Tests split along the same seam. `test_tree` asserts the *facts* a failure
  carries and that it carries no prose; `test_contract` asserts the sentences,
  and runs without the SDK installed.
- The framework goes from 15 source files to 16 and from 22 classes to 23. Two
  of the three findings this was reviewed against are closed by construction
  rather than by fixing them one at a time.

## Not done here

- ~~`Projection` still reports a constant.~~ **Removed immediately after, in
  the commit that follows this ADR.** The reasoning here was that changing
  `build_server()`'s signature could not be verified without the SDK; the
  counter-argument that won is that a class whose only assertion compares a
  constant with itself is not made safer by being kept. `project()` now returns
  nothing and `build_server()` returns the server. A caller that wants to know
  what is on the wire asks the server, which is the one answer that cannot go
  stale.
- `Dispatch` still keys its cache by `id(tool)`, but now stores the tool
  alongside the derivation, so the key cannot be recycled while the entry
  lives. The remaining `id()` use is an optimisation, not a correctness
  dependency on somebody else holding a reference.
- ~~`Transport` still offers `"sse"`.~~ **Removed.** HTTP+SSE was the
  2024-11-05 two-endpoint transport, superseded by Streamable HTTP and
  deprecated in every revision this server speaks. Offering it in a `Literal`
  and in two `argparse` choice lists advertised a transport that was never
  tested and should not be chosen. A host that still needs it can put a proxy
  in front.
