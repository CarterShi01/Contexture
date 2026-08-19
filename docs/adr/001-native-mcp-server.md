# ADR 001 — Contexture serves MCP instead of compiling for it

**Status:** accepted, implemented in v0.0.4
**Date:** 2026-08-19

## Context

Through v0.0.3 the main path ran declaration → compiler → target adapter →
generated files, with `contexture.protocol` holding a hand-written MCP **client**
for calling other people's servers. An agent runtime consumed Contexture by
reading `CLAUDE.md`, `SKILL.md`, `AGENTS.md`, or `.cursor/rules/*.mdc`.

Two problems with that shape:

1. **A generated file is a copy.** It drifts the moment the declaration changes,
   and every new runtime costs another adapter that must re-express the same six
   answers in a fourth syntax.
2. **The arrow pointed the wrong way.** Contexture spoke MCP as a client. The
   thing agent runtimes actually connect to — a server — did not exist.

## Decision

Contexture is a native MCP server. Roles, skills, tools, and resources are
declared once and served; hosts connect to the same process.

Four decisions inside that one:

### The official SDK, as a hard dependency

`mcp>=2.0.0` rather than a hand-written protocol layer. The 2026-07-28 revision
is not small — per-request `_meta` version negotiation instead of an initialize
handshake, a mandatory `server/discover`, `InputRequiredResult` round trips —
and it must be served alongside four older revisions.

This costs the zero-dependency property, which was real and is now gone: the SDK
pulls in 28 packages. It is a hard dependency rather than an extra because the
server *is* the product now, and making the product optional would be
incoherent. `contexture.core` still must not import it, and a layering test
enforces that both statically and at runtime.

### The tree lives in the payload, not on the surface

MCP tool and resource lists are flat, and since 2026-07-28 explicitly stateless:
they may not vary per connection or as a side effect of earlier calls on it.

So the role graph is not the protocol surface. It travels inside the return
values of two framework tools, `contexture_discover` and
`contexture_get_context`, and an agent's position in it is a `ref` the agent
carries — not state the server keeps. `get_context` is a pure function of its
ref.

A consequence worth stating plainly: **one server serves the whole forest.**
Fixing a single root at launch would have meant one process per leaf role, which
is not a price a role tree should extract.

### Disclosure delivers knowledge, not access

On a flat surface, per-role authorization is not achievable — a tool name that
exists can be called by anyone who can see the list. Rather than pretend
otherwise, the split is explicit:

* **Disclosure** decides what an agent *learns*: a skill's procedure exists only
  behind `contexture_get_context`.
* **Authorization** stays with the host, which the specification already makes
  responsible for keeping a human in the loop, informed by the `readOnlyHint`
  annotation Contexture projects from each tool's `read_only`.

`read_only` is therefore never an input parameter. A model that could pass its
own approval flag would be approving its own writes. A test asserts this on the
wire.

### `MCPBinding` is untouched

Its least-privilege model exists because a remote catalog belongs to someone
else and can change underneath a grant. That premise still holds for outbound
use, and nothing in this change touches it. Two of its four jobs — subsetting a
foreign catalog, and validating names against it — have no meaning for locally
owned capabilities, but removing it would have meant editing ~220 references
before the server was proven to work at all.

## Consequences

* `contexture.core` gains `Tool` (executable, schema from `invoke`'s type hints)
  and `Resource` (read on demand) beside `MCPTool` and `MCPResource`, which keep
  describing capabilities somebody else owns.
* `contexture.discovery` is new: refs, the capability graph, and the two-verb
  disclosure engine.
* `contexture.server` is new and is the only layer that imports the SDK.
* `contexture.targets` is demoted from the main path. It still renders context
  files for runtimes that cannot connect, and `contexture.server.registration`
  now emits the only file that is still needed on the main path: the one that
  says how to launch the server.
* `contexture.execution` and `contexture.protocol` are unchanged. They serve the
  outbound direction, which is now a side road rather than the main one.

## Not done here

Real cluster access, OAuth, multi-tenancy, HTTP as the primary transport,
per-connection dynamic tool lists, a gateway surface that virtualizes thousands
of capabilities, and migrating `MCPClient` into an `upstream` package. Each
would have diluted the one claim this version had to establish: that a
declaration becomes a server two different hosts can use.
