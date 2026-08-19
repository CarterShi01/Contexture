# Contexture

**A context framework for agents.**

MCP lets an agent *call* your system. Contexture lets an agent *understand* it.

The official SDK turns a Python function into a tool. Contexture turns a domain
into a capability graph an agent can navigate — one with responsibility
boundaries, procedural knowledge, and a context bill you pay only for what gets
selected.

Declare your roles, skills, tools, and resources once. Contexture serves them as
a native MCP server that Claude Code, Codex, and anything else speaking MCP
connect to directly.

It does not run an agent loop, choose tools, or talk to a model. It is what
those runtimes connect to.

## Two models

Everything in this repository follows from two sentences.

**The runtime model — what Contexture *is* while it runs.**

> Contexture organizes Role, Skill, Tool, and Resource into a single MCP server
> surface, and discloses them progressively over the course of the interaction.

**The framework model — how a developer *uses* it.**

> Contexture provides the abstractions, the lifecycle, the inversion of control,
> and the MCP runtime. Business developers extend those abstractions to define
> capabilities; the framework turns them into a native, progressively disclosed
> MCP server.

The first answers *what is running*. The second answers *what do I write*.

They meet in exactly one place — `contexture.server` — which is why that is the
only layer permitted to import the MCP SDK, and why `contexture.core` is
forbidden from it.

The two are also the admission test for every new concept. Before a compiler, a
registry, a resolver, a descriptor, or a request object earns a place here, it
answers one question:

> Does this help a business developer **define** a capability, or help the
> framework **run** one?

A concept that does neither is a spare part, however well made.

## The programming model: Object-Oriented Programming

The programming model is **Object-Oriented Programming (OOP)**. Not a decorator
registry, not a manifest, not a DSL. The framework ships an object model; the
business layer extends it by subclassing. There is no registration call, no
manifest to keep in step with the code, and no decorator that can drift away
from the class it decorates:

```python
class GetPodLogs(Tool):            # a capability you own
class DiagnoseCrashLoop(Skill):    # a procedure you own
class CrashLoopRunbook(Resource):  # content you own
class IncidentResponder(Role):     # the boundary that holds them
```

Four OOP mechanisms carry weight here, and each does a job the alternatives
cannot.

**Inheritance is the extension point.** `class GetPodLogs(Tool)` *is* the
registration — there is no second act. `__init_subclass__` reads the class body
at class-creation time, so a malformed declaration fails on import rather than
on the first request that happens to touch it.

**Encapsulation keeps the disclosure decision local.** Every node decides for
itself what its routing card says and what its opened form says. Nothing central
holds a table of node kinds, so adding a kind does not edit a renderer.

**Polymorphism is what makes progressive disclosure uniform.** Role, Skill,
Tool, and Resource have nothing else in common, yet discovery calls
`node.compile(level)` on all four and never asks what it is holding.

**Composition, not inheritance, models the team.** Subclassing states what one
node *is*; it never states containment. A role that coordinates other roles
holds them in `children`, whether it was declared or assembled at runtime.

Each base class states one contract and derives the rest from what the subclass
already says. The class name becomes the node name, the docstring becomes the
routing description, and a tool's input schema is read off the type hints on
`invoke`. Nothing is written twice, so nothing can fall out of sync.

Inversion of control runs the other way from a library: you never construct a
server, dispatch a request, parse arguments, or serialize a result. You declare
what you own and hand the roots to `ContextureApp`; the framework calls your
code, not the reverse.

## The problem

A system that wants to work with several agents ends up maintaining the same
context several times:

```text
Claude Code   CLAUDE.md · .claude/skills/**/SKILL.md · .mcp.json
Codex         AGENTS.md · ~/.codex/config.toml
Cursor        .cursor/rules/*.mdc · .cursor/mcp.json
```

Every one of those files answers the same six questions: who is this role, what
does it know, what may it run, what may it read, what is visible by default,
and what appears only after something is selected. The answers are identical.
Only the file formats differ — and they drift apart the moment anyone edits one
of them.

A generated file is a copy. Contexture serves the answer instead, so there is
nothing to drift:

```text
Claude Code ─┐
Codex ───────┼──── MCP ────►  one Contexture server  ────►  your declaration
Cursor ──────┘
```

## Declare once

```python
from contexture import Resource, Role, Skill, Tool

class InspectPodFailure(Skill):
    """Diagnose why a Pod is crashing, restarting, or failing to become ready."""

    instructions = """
    1. Inspect the Pod status and restart count.
    2. Read current logs, then previous logs after a restart.
    3. Correlate status, logs, and events before proposing remediation.
    """

class K8sTroubleshooter(Role):
    """Diagnose unhealthy Pods, failed Deployments, and scheduling failures."""

    instructions = "Start with read-only inspection. Do not modify the cluster."

    inspect_failures = InspectPodFailure

    pod_logs = GetPodLogs
    events = GetEvents
    runbook = CrashLoopRunbook
```

The class name becomes `k8s-troubleshooter`, the docstring becomes the routing
description, and the declared members become the role's skills, tools, and
resources. Nothing here names an agent runtime.

Imperative construction still works exactly as before, and a declared role is
an ordinary `Role`, so anything that accepts one accepts the other.

## Implement what it can do

A tool is a typed Python method. Nothing writes a JSON Schema — the one in
`tools/list` is derived from this signature:

```python
from contexture import Resource, Tool

class GetPodLogs(Tool):
    """Return recent container logs for one Pod."""

    name = "get_pod_logs"
    read_only = True

    async def invoke(self, namespace: str, pod: str) -> str:
        return await kubernetes.logs(namespace, pod)

class CrashLoopRunbook(Resource):
    """How to diagnose a container that keeps restarting."""

    uri = "contexture://runbooks/crash-loop-backoff"
    mime_type = "text/markdown"

    async def read(self) -> str:
        return RUNBOOK
```

`read_only` is a host classification, not an argument. It is projected onto the
protocol's `readOnlyHint` so a host can ask a human first, and it never appears
in an input schema — a model that could pass its own approval flag would be
approving its own writes.

## Serve it

```python
from contexture.server import ContextureApp

app = ContextureApp(roots=KubernetesIncidentResponder())

if __name__ == "__main__":
    app.run(transport="stdio")
```

Then point any host at it — the same command for each:

```bash
claude mcp add contexture -- uv run my-server
codex mcp add contexture -- uv run my-server
```

Nothing above imports `mcp`, writes JSON-RPC, or names an agent runtime.

## Still rendering files, when you need to

`contexture.targets` remains for runtimes that cannot connect, and reports what
each one cannot express rather than dropping it silently:

```python
from contexture.targets import all_adapters, render_all, write

surfaces = render_all(KubernetesIncidentResponder(), all_adapters())
print(surfaces["codex"].notes[0])
# Codex has no separate skill artifact; 2 skill(s) were inlined into the main
# context file, so their instructions are always resident.
```

This is a side road now. On the main path the only file a host still needs is
the one naming the launch command, which `contexture.server.registration`
emits.

## Layers

```text
your application          declares roles, skills, tools, resources
        │  inherits / composes
contexture.core           the object model — no I/O, no wire, no SDK
        │  compile
contexture.compiler       route / active disclosure of one node
        │  navigate
contexture.discovery      refs, the capability graph, discover / get_context
        │  project
contexture.server         the native MCP server — the only layer importing mcp
        │  MCP
Claude Code · Codex · Cursor · any MCP host

        ┊ side road
contexture.targets        rendered context files, for runtimes that cannot connect
```

Each layer may import the ones below it and never the reverse. `core` in
particular must not import `mcp`: an object model that reaches for a wire
protocol has stopped being an object model. `tests/test_layering.py` enforces
this in the AST and again at runtime, in a subprocess, so a convenient import
fails rather than quietly reshaping the package.

## Progressive disclosure

Every `ContextNode` — role, skill, tool, resource — answers the same two
questions:

```python
node.compile("route")   # what is this, and when should it be picked?
node.compile("active")  # the detail, now that it has been picked
```

Over MCP those become two tools, and an agent navigates with them:

```text
contexture_discover()               → every root, one card each
contexture_discover(role:…)         → what is under it, still only cards
contexture_get_context(skill:…#…)   → the full procedure, here and nowhere else
```

Each card carries the `ref` that opens it. **That ref is the agent's position,
and the server does not remember it** — which is what makes traversal legal:
since the 2026-07-28 revision, MCP has no protocol session, and a server may not
vary its tool list per connection or as a side effect of earlier calls.
`get_context` is a pure function of its ref.

So the role tree is not the protocol surface. The surface is flat; the tree
travels inside these payloads. One server therefore serves a whole forest of
roots, instead of forcing one process per leaf role.

Resources are the exception that proves the rule: their boundary is not route
versus active but **descriptor versus content**. Discovering one, or opening it
with `get_context`, yields metadata. Only reading it returns bytes.

## Disclosure is not authorization

These are separate, and conflating them is the trap this design is built to
avoid.

On a flat surface, per-role authorization is not achievable: a tool name that
exists can be called by anyone who can see the list. Nothing stops an agent from
skipping discovery and calling a tool directly, and nothing should pretend to.

**What disclosure controls is knowledge.** The procedure, its ordering, and its
constraints live behind `contexture_get_context`. An agent that skips ahead can
run a tool; it cannot know what the runbook says about exit code 137, or that
restarting first repairs nothing.

**Authorization stays with the host**, which the specification already makes
responsible for keeping a human in the loop. Contexture informs that decision by
projecting each tool's `read_only` onto `readOnlyHint`, and by never letting
that classification become an argument a model can fill in.

## Quick start

Python 3.10 or newer.

```bash
uv sync
uv run contexture-incident-demo   # an MCP server over stdio
uv run python run_tests.py        # the full suite
```

See [`src/contexture/examples/incident/`](src/contexture/examples/incident/) for
a server two hosts can connect to, and
[`docs/verification/hosts.md`](docs/verification/hosts.md) for a recorded run.

The `targets` example declares one team across two external MCP servers:

```text
engineering-team
├── k8s-troubleshooter      → production-kubernetes (stdio)
│   ├── Skill: inspect-pod-failure
│   ├── get_pod_logs, get_events            read-only
│   └── runbook, deployment manifest        resources
├── k8s-operator            → production-kubernetes
│   ├── + delete_pod                        needs approval
│   └── deployment manifest                 resource
└── github-liaison          → github-cloud (http)
    ├── Skill: report-incident
    ├── create_issue                        needs approval
    └── repository README                   resource
```

## Project layout

```text
src/contexture/
├── core/            object model: context, role, skill, tools, resources,
│                    registry, declarative
├── compiler.py      route/active compilation and capability selection
├── discovery.py     refs, the capability graph, discover / get_context
├── server/          the MCP server: app, projection, instructions, registration
├── examples/        reference applications built on the public API only
└── targets/         base, markdown, claude_code, codex, cursor, writer
```

## Design documents

- [`docs/01-role-object-model.md`](docs/01-role-object-model.md) — the object
  model, its invariants, and why each boundary sits where it does.
- [`docs/02-framework-layers.md`](docs/02-framework-layers.md) — the framework
  shape: declaration, compilation, the server, and the one side road.
- [`docs/adr/001-native-mcp-server.md`](docs/adr/001-native-mcp-server.md) — why
  the main path became a server, what it cost, and what was deliberately left
  alone.
- [`docs/adr/003-remove-the-outbound-half.md`](docs/adr/003-remove-the-outbound-half.md)
  — why the client half ADR 001 left alone was removed instead, and what that
  gave up.
- [`docs/atlas/index.html`](docs/atlas/index.html) — an offline visual atlas;
  open it directly in a browser. After editing it, run
  `npm install jsdom@22 && node docs/atlas/check.mjs` to confirm every diagram
  still parses; a mermaid syntax error otherwise stays invisible until someone
  opens the page.

## What Contexture does not do

Three things sit next to Contexture and are easy to confuse with it. Each
boundary is deliberate, and each one is what keeps this codebase small.

### Not the MCP SDK — it sits on top of one

The official `MCPServer` is a protocol implementation: it turns a Python
function into a legal MCP tool, derives JSON Schema from type hints, frames
stdio, and negotiates protocol versions. Contexture does none of that and never
will.

| | `mcp.server.mcpserver.MCPServer` | Contexture |
| --- | --- | --- |
| Audience | protocol implementers | business developers |
| Question it answers | how does this function become a legal MCP tool? | how does this domain become a graph an agent can navigate? |
| Unit | a flat list of tools, resources, prompts | a forest of roles with boundaries |
| Scale it assumes | a dozen tools, all resident | hundreds of capabilities, most of them out of context |
| Context budget | not its problem | a first-class constraint |
| Wire format, schema, transport | owns it | never touches it |

The entire dependency is five imports inside `contexture/server/` and four SDK
calls: the constructor, `add_tool`, `add_resource`, `run`. `ContextureApp`
composes an `MCPServer` rather than subclassing one, so an SDK upgrade cannot
reach into the object model, and `tests/test_layering.py` fails if any other
layer imports `mcp`.

Two things the SDK offers and Contexture deliberately declines:

- **`add_prompt`, never called.** MCP prompts are user-triggered templates. A
  Skill is agent-selected procedural knowledge. Mapping one onto the other hands
  the selection back to a human, which is the opposite of the point.
- **The decorator style (`@server.tool()`).** Capabilities are runtime objects
  walked out of a graph, not functions known at import time in one module.

### Not the agent runtime — Claude Code and Codex stay in charge

Contexture has no planner, no agent loop, no tool selection, and never calls a
model. It does not decide which skill fits a task. It makes that decision
cheaper by putting a one-line routing card in front of the model where a full
procedure would otherwise sit.

The division is sharpest around authorization. **Disclosure is not
authorization**: Contexture governs what an agent *knows*, the host governs what
an agent may *run*. A tool's `read_only` classification is projected onto
`readOnlyHint` so the host can ask a human first — Contexture itself never asks,
never blocks, and never lets that flag become an argument a model can fill in.

Host configuration is not Contexture's either. It emits the launch command
through `contexture.server.registration` and stops there; what the host does
with sampling, permissions, or its own memory files is outside the boundary.

### Not your business system — it describes one, it does not become one

Contexture holds none of your state. No database, no cache, no queue, no
scheduler, no retry policy, no transactions, and no domain logic of its own. A
`Tool` is a typed Python method whose body is *your* code calling *your*
system; Contexture decides when the description of that method becomes visible,
and hands the call through.

These stay yours:

- **Business logic and persistence.** `invoke` and `read` are your call sites,
  and the framework never inspects what happens inside them.
- **Credentials for your own backends.** Contexture stores none.
- **What a procedure actually says.** A Skill's `instructions` are domain
  knowledge the framework never authors, validates, or rewrites.
- **Calling somebody else's MCP server.** Contexture is the inbound half. Use
  the SDK's client for outbound work; the hand-written client that once lived in
  `contexture.protocol` was removed rather than maintained against a moving
  specification, for the reasons in
  [`docs/adr/003-remove-the-outbound-half.md`](docs/adr/003-remove-the-outbound-half.md).

### Also true

- Not a new protocol. It speaks MCP through the official SDK rather than its own
  JSON-RPC implementation.
- Not zero-dependency any more. Serving MCP means depending on `mcp`, and that
  is a deliberate trade recorded in ADR 001.

## License

Apache-2.0
