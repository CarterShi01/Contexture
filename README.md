# Contexture

**A context framework for agents.**

Declare your roles, skills, tools, and resources once. Contexture progressively
discloses that declaration and translates it into the skill and MCP surfaces
that Claude Code, Codex, and Cursor each consume.

It does not run an agent loop, choose tools, or talk to a model. It produces
what those runtimes read.

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

Contexture makes those answers a program.

## Declare once

```python
from contexture import MCPBinding, Role, Skill

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

    cluster = MCPBinding(
        server=KUBERNETES,
        allowed_tools=["get_pod_logs", "get_events"],
        read_only_tools=["get_pod_logs", "get_events"],
        allowed_resources=["resource://kubernetes/runbook/incidents"],
    )
```

The class name becomes `k8s-troubleshooter`, the docstring becomes the routing
description, and the declared members become the role's skills and grants.
Nothing here names an agent runtime.

Imperative construction still works exactly as before, and a declared role is
an ordinary `Role`, so anything that accepts one accepts the other.

## Render for every target

```python
from contexture.targets import all_adapters, render_all, write

surfaces = render_all(EngineeringTeam(), all_adapters())

for note in surfaces["codex"].notes:
    print(note)
# Codex has no separate skill artifact; 2 skill(s) were inlined into the main
# context file, so their instructions are always resident.

write(surfaces["claude-code"], root=".")
```

Adapters return artifacts; they never write. A separate writer installs them,
skips files that already match, and can report a plan without touching disk.

**Losses are reported, not hidden.** Agents differ in what they can express. A
target that cannot carry a per-role tool allowlist, or has no nested-role
concept, says so in a note. A generated surface that looks authoritative while
quietly dropping half a declaration is worse than no generation at all.

## Layers

```text
your application          declares roles, skills, tools, resources
        │  inherits / composes
contexture.core           the object model — no I/O, no wire, no targets
        │  compile
contexture.compiler       route / active progressive disclosure
        │  render
contexture.targets        Claude Code · Codex · Cursor artifacts
        ┊
contexture.protocol       optional MCP wire layer, outbound and inbound
contexture.execution      optional authorization and dispatch
        │  consumed by
external agent runtime    LLM loop · planning · tool selection  (not ours)
```

Only `core` is mandatory. Each layer may import the ones below it and never the
reverse, which is why a project that just wants generated context files never
loads a transport.

## Progressive disclosure

Every `ContextNode` — role, skill, tool, resource — answers the same two
questions:

```python
node.compile("route")   # what is this, and when should it be picked?
node.compile("active")  # the detail, now that it has been picked
```

An active role exposes its own instructions plus route cards for its children,
skills, tools, and resources. It never recursively activates its descendants.
Detail arrives only for capabilities a caller explicitly selects:

```python
runtime.compile(
    "engineering-team/k8s-troubleshooter",
    CompileRequest(
        selection=CapabilitySelection(
            skill_names=("inspect-pod-failure",),
            tool_refs=("production-kubernetes/get_pod_logs",),
        )
    ),
)
```

Resources are the exception that proves the rule: their boundary is not route
versus active but **descriptor versus content**. Compiling one at any level
yields metadata. Only `RoleRuntime.read_resource` returns bytes.

## Security model

1. An ungranted tool or resource never reaches the agent's routing surface.
2. `MCPBinding` checks the grant again when a capability is activated.
3. The execution layer checks it again immediately before running.
4. A tool not host-classified as read-only requires explicit approval.
5. Every authorization refusal is one exception type, `CapabilityDeniedError`,
   including the case where the role holds no binding to that server at all.
6. A refreshed server catalog may not orphan an existing grant.

MCP `ToolAnnotations` are kept for display and planning but treated as
untrusted hints. `read_only_tools` on the binding is the host's own
classification and the only thing the runtime trusts.

Resources carry no read-only classification because MCP defines no write path
for them; appearing on `allowed_resources` is the entire grant.

## Serving your own capabilities

`MCPClient` is the outbound half of MCP. `MCPHostPort` is the inbound half —
the boundary an application implements so its declared tools and resources can
be served:

```python
class MCPHostPort(Protocol):
    def register_tool(self, tool: MCPTool, handler: ToolHandler) -> None: ...
    def register_resource(self, resource: MCPResource, provider: ResourceProvider) -> None: ...
```

`InMemoryHost` implements it in process, which is what the example uses. A
deployable server is deliberately absent: the port is what keeps that decision
cheap to make once two real callers have shown what it must do.

## Quick start

Python 3.10 or newer. No runtime dependencies.

```bash
python run_demo.py     # declaration → three surfaces → disclosure → execution
python run_tests.py    # 79 tests
```

The example declares one team across two MCP servers:

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
│                    servers, binding, registry, declarative
├── compiler.py      route/active compilation and capability selection
├── targets/         base, markdown, claude_code, codex, cursor, writer
├── protocol/        messages, transport, client, host
└── execution.py     authorization and dispatch
```

## Design documents

- [`docs/01-role-object-model.md`](docs/01-role-object-model.md) — the object
  model, its invariants, and why each boundary sits where it does.
- [`docs/02-framework-layers.md`](docs/02-framework-layers.md) — the framework
  shape: declaration, compilation, targets, and the optional layers.
- [`docs/atlas/index.html`](docs/atlas/index.html) — an offline visual atlas;
  open it directly in a browser.

## What this is not

- Not an agent runtime. No planner, no agent loop, no tool selection.
- Not a new protocol. It compiles to MCP and to each agent's own formats.
- Not a model client. It never calls an LLM.

## License

Apache-2.0
