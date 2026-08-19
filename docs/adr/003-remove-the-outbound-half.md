# ADR 003 — Remove the outbound half

**Status:** accepted, implemented in v0.0.5
**Date:** 2026-08-19

## Context

ADR 001 turned the main arrow around: Contexture became a native MCP server
instead of a compiler that emitted context files. It said the outbound
direction — `MCPBinding` and the client used to call somebody else's server —
was "untouched", and left it in place as a side road.

That was half a decision, and the half that was left produced four visible
symptoms.

**Two of everything.** `Tool` and `MCPTool`; `Resource` and `MCPResource`. Both
pairs sat under `ContextNode`, so they read as siblings when one was a capability
and the other was a description of somebody else's capability. The name was the
worst part: `MCPTool`'s "MCP" never meant *the MCP-facing one*, it meant *parsed
off the MCP wire*, and nothing in the name said so.

**The README contradicted the code.** "Not a new protocol. It speaks MCP, using
the official SDK rather than its own JSON-RPC implementation" — while
`protocol/messages.py` opened with `"""JSON-RPC 2.0 and MCP 2026-07-28 request
construction."""` and 1237 lines of hand-rolled client sat under it, built on
`urllib`.

**`core` knew about the wire.** Its docstring claimed "no I/O, no wire, no SDK",
and `core/constants.py` held `MCP_PROTOCOL_VERSION`, `JSON_RPC_VERSION`, and
three `io.modelcontextprotocol/*` metadata keys.

**The server advertised tools it could not run.** `Role._compile_active()` emitted
`available_mcp_tools` and `available_mcp_resources` from the role's bindings, and
`contexture_get_context` on a role handed those to the agent. Contexture cannot
execute them — it is not in the path — so the payload described capabilities that
were not there.

Measured, the outbound half was 2027 of 5613 lines of `src`, and
`contexture.server` and `contexture.discovery` — the two layers that actually
serve an agent — referenced none of it.

## Decision

The outbound direction is removed, not relocated.

Gone: `MCPTool`, `MCPResource`, `ToolAnnotations`, `MCPServer`,
`ServerConnection` / `StdioConnection` / `HTTPConnection`, `MCPBinding`, the
`contexture.protocol` package, `contexture.execution`, and `core/coercion.py` —
whose validating conversions existed only for the two `from_protocol_dict`
constructors. With them go
`Role.mcp_bindings`, the four `get_mcp_binding*` accessors, the two
`available_mcp_*` keys, the binding branch of `RoleCompiler`, and the
outbound-only exceptions.

`core` keeps four concepts, each subclassed by the business layer and none of
them aware that MCP exists:

```text
ContextNode
└── Role · Skill · Tool · Resource
```

### Why removal rather than an extra

The subsetting `MCPBinding` performed had teeth only while Contexture stood
between an agent and a provider. As a server it does not: a host connects to the
Contexture server *and* to the Kubernetes server, and the host owns the grant.
Keeping the objects would have kept the vocabulary of an enforcement Contexture
no longer performs, which is worse than not offering it.

The one shape that would have restored the teeth is a proxy — re-exporting a
foreign catalog as Contexture's own, and refusing to export what a binding does
not allow. That is a real design, and it is deliberately not this one: it turns a
declaration framework into an infrastructure component with availability,
latency, failure propagation, and credential custody to answer for. The README's
claim is that Contexture is *what those runtimes connect to*, not what they go
through.

### What is genuinely lost

- **Per-role subsetting of a foreign catalog.** The host does this now.
- **`read_only` for foreign tools.** For a role's own tools the classification is
  unchanged and still projects onto `readOnlyHint`; for somebody else's tools
  Contexture never had the execution path to enforce anything.
- **The refresh invariant** — that a rediscovered catalog may not orphan an
  existing grant. It protected a catalog Contexture no longer holds.

## Consequences

- `src` drops from 5613 to 3105 lines, and from 35 framework source files to 22;
  the test suite from thirteen test files to eight, and 36 classes remain in the
  framework.
- One `Tool` concept and one `Resource` concept. The three-way ambiguity that
  made "which Tool do you mean?" a real question is gone.
- `core/constants.py` holds a package name and a version. The layer is finally
  what its docstring says, and `tests/test_layering.py` now asserts that **no**
  module reaches the network rather than naming the one that may.
- `contexture.targets` keeps working, with its capability table pointed at the
  role's own tools and resources. It no longer emits `.mcp.json`,
  `.cursor/mcp.json`, or `.codex/config.toml`: those configured servers
  Contexture does not own, and `server.registration` already emits the one
  pointer a host still needs. A consequence worth naming — the table previously
  rendered *only* foreign tools, so a role's own tools were never in a rendered
  surface at all.
- `ClaudeCodeAdapter` now reports no losses, because with server configuration
  out of scope it has none. The target tests assert that a lossy adapter reports
  and a lossless one stays quiet.
- `RoleCompiler` survives, with `CapabilitySelection` reduced to `skill_names`,
  and it stays. A `ContextNode` knows how to compile *itself*; the compiler is
  what decides **which** node and **at which level**, and it is the seam
  `DisclosureEngine` is built on — `discovery` imports `compiler`, not the
  reverse. Collapsing it into `ContextNode.compile` would push that policy into
  every node and leave nowhere for a compile request to be expressed. It is
  thinner than it was; it is not vestigial.
- Design 01 and Design 02 lost or rewrote nine sections between them, and the
  atlas lost a plate. That is the real cost of having left the decision half
  made in ADR 001: the documentation had already been written around it.

## Not done here

- The per-call context object and the options struct (ADR 002), still proposed.
- Any proxy or gateway capability. If one is ever wanted, it starts from this
  smaller core rather than from the objects removed here.
