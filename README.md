# Role Runtime Starter

A Python reference project for modeling an agent team as a tree of composable
`Role` objects. Each Role can contain child Roles, reusable Skills, and a
restricted subset of the Tools and Resources exposed by MCP servers. A unified
compiler progressively reveals only the context selected for the current LLM
turn.

The MCP boundary targets the formal **2026-07-28** protocol revision and uses
**JSON-RPC 2.0** messages.

## What this project demonstrates

- `ContextNode` as the stable progressive-disclosure contract.
- `Role` as a composite responsibility boundary.
- `Skill` as reusable workflow knowledge.
- `MCPTool` as a protocol-compatible callable function descriptor.
- `MCPResource` as a readable context descriptor that never carries content.
- `MCPServer` as infrastructure owning both a tool and a resource catalog.
- `MCPBinding` as the least-privilege relationship between a Role and a Server.
- `RoleCompiler` as one compile interface for route and active context.
- `RoleRegistry` for role-path resolution and cycle detection.
- `RoleRuntime` for execution-time authorization, tool calls, and resource reads.
- MCP request metadata, required Streamable HTTP routing headers, custom
  `x-mcp-header` extraction, JSON responses, and request-scoped SSE parsing.

There is deliberately **no separate Data abstraction**. Every form of contextual
information — documents, configuration, knowledge, runbooks — is an MCP Resource
behind the same binding that grants Tools, so one grant format and one runtime
path cover everything a Role may touch.

## Mental model

```text
Role        = who owns the responsibility
Skill       = how a class of work should be performed
MCPTool     = which external function can be called
MCPResource = which external content can be read
MCPServer   = which provider exposes them
MCPBinding  = which subset of that provider a Role may use
Compiler    = what becomes visible in the current LLM context
Runtime     = what is actually authorized and executed
```

The main object graph is:

```text
Role
├── children: Role[]
├── skills: Skill[]
└── mcp_bindings: MCPBinding[]
    ├── allowed_tools / read_only_tools
    ├── allowed_resources
    └── server: MCPServer
        ├── tools: MCPTool[]
        └── resources: MCPResource[]
```

## Progressive disclosure

Every `ContextNode` supports the same two-level interface:

```python
node.compile("route")
node.compile("active")
```

`route` exposes only the small routing card:

```json
{
  "kind": "skill",
  "name": "inspect-pod-failure",
  "description": "Diagnose why a Kubernetes Pod is failing."
}
```

`active` exposes the detailed representation for the selected node. For a Skill,
that means its instructions. For an MCP Tool, that means its full `inputSchema`.
For an MCP Resource, that means its URI and media type — never the content,
which only `RoleRuntime.read_resource` can fetch.

An active Role still exposes its direct child Roles and capabilities only as
route cards. The compiler activates detailed capability content only when those
capabilities are explicitly selected.

## Quick start

Python 3.11 or newer is required. The source checkout has no runtime
dependencies, so it can run immediately without installation:

```bash
python run_demo.py
python run_tests.py
```

An editable installation is also supported:

```bash
python -m venv .venv

# Linux or macOS
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

python -m pip install -e .
python -m examples.run_demo
python -m unittest discover -s tests -v
```

The example builds this team across two independent MCP servers:

```text
engineering-team
├── k8s-troubleshooter        → production-kubernetes
│   ├── Skill: inspect-pod-failure
│   ├── Tool: get_pod_logs, get_events          (read-only)
│   └── Resource: runbook/incidents, deployment/payments-api
├── k8s-operator              → production-kubernetes
│   ├── Tool: get_pod_logs, get_events          (read-only)
│   ├── Tool: delete_pod                        (needs approval)
│   └── Resource: deployment/payments-api
└── github-liaison            → github-cloud
    ├── Skill: report-incident
    ├── Tool: create_issue                      (needs approval)
    └── Resource: payments-api/README.md
```

The demo walks every boundary this produces:

- The Troubleshooter cannot see or call `delete_pod`.
- The Operator can see it, but the Runtime requires explicit approval because
  the Host did not classify that tool as read-only.
- The Troubleshooter holds no GitHub binding at all, so both the GitHub tool and
  the GitHub resource are denied — with the same `CapabilityDeniedError` a
  within-server denial raises.
- Reading a granted resource returns content only from the Runtime; the compiled
  context carried the descriptor alone.

## Small construction example

```python
from role_runtime import MCPBinding, MCPResource, MCPServer, MCPTool, Role, Skill

get_pod_logs = MCPTool(
    name="get_pod_logs",
    description="Read logs from a Kubernetes Pod container.",
    input_schema={
        "type": "object",
        "properties": {
            "namespace": {"type": "string"},
            "pod": {"type": "string"},
            "container": {"type": "string"},
        },
        "required": ["namespace", "pod", "container"],
        "additionalProperties": False,
    },
)

runbook = MCPResource(
    name="kubernetes-incident-runbook",
    description="Operational guidance for common Kubernetes incidents.",
    uri="resource://kubernetes/runbook/incidents",
    mime_type="text/markdown",
)

server = MCPServer(
    server_id="production-kubernetes",
    name="kubernetes",
    description="Kubernetes cluster operations.",
    tools=[get_pod_logs],
    resources=[runbook],
)

inspect_failure = Skill(
    name="inspect-pod-failure",
    description="Diagnose a failing Kubernetes Pod.",
    instructions="Inspect status, current logs, previous logs, and events.",
)

troubleshooter = Role(
    name="k8s-troubleshooter",
    description="Diagnose Kubernetes runtime failures.",
    instructions="Start with read-only evidence collection.",
    skills=[inspect_failure],
    mcp_bindings=[
        MCPBinding(
            server=server,
            allowed_tools=["get_pod_logs"],
            read_only_tools=["get_pod_logs"],
            allowed_resources=["resource://kubernetes/runbook/incidents"],
        )
    ],
)
```

## Host references versus MCP protocol names

The Host uses globally unique references for both capability kinds:

```text
production-kubernetes/get_pod_logs
production-kubernetes/resource://kubernetes/runbook/incidents
```

Both are `<server_id>/<protocol identifier>` and both are split on the **first**
separator only, so a resource URI keeps its own slashes and scheme intact. A
server id may not contain `/`, which is what makes that parse unambiguous.

The MCP requests still send the original protocol identifiers:

```json
{
  "method": "tools/call",
  "params": { "name": "get_pod_logs", "arguments": {} }
}
```

```json
{
  "method": "resources/read",
  "params": { "uri": "resource://kubernetes/runbook/incidents" }
}
```

`tool_ref` and `resource_ref` are Host routing constructs. They are not MCP
protocol fields.

## Security model

The project uses defense in depth:

1. An ungranted Tool or Resource is omitted from the Role's LLM routing surface.
2. `MCPBinding` checks the grant again when a capability is activated.
3. `RoleRuntime` checks the grant again immediately before execution.
4. A Tool not explicitly Host-classified as read-only requires approval.
5. Every authorization refusal is a `CapabilityDeniedError`, including the case
   where the Role holds no binding to the named server at all.
6. A refreshed server catalog may not orphan an existing grant, and both
   catalogs are validated before either is replaced.
7. The MCP Server remains responsible for its own authentication and
   authorization.

MCP `ToolAnnotations` are retained for display and planning, but are treated as
untrusted hints. They are never the authorization source of truth.

Resources carry no read-only classification because MCP defines no write path
for them; appearing on `allowed_resources` is the entire grant.

## MCP 2026-07-28 boundary

The focused client in this project implements the parts needed by the Role
Runtime example:

- JSON-RPC 2.0 request and response validation.
- Required per-request `_meta` fields.
- `tools/list` and `resources/list` pagination and catalog refresh.
- `tools/call` requests and result parsing.
- `resources/read` requests and content-block parsing.
- `MCP-Protocol-Version`, `Mcp-Method`, and `Mcp-Name` headers.
- `x-mcp-header` validation, extraction, and Base64 sentinel encoding.
- Streamable HTTP JSON responses and request-scoped SSE responses.

This repository is a terminal-state architecture for the Role model, not a full
replacement for a complete MCP SDK. It does not automatically drive all
optional MCP features such as long-lived subscriptions, resource subscriptions,
Prompts, automatic multi-round-trip input handling, or every authorization flow.
Those features belong behind the existing `MCPTransport` and `MCPClient`
boundaries.

## Project layout

```text
role-runtime-starter/
├── docs/
│   ├── 01-role-object-model.md
│   └── atlas/index.html          offline architecture atlas
├── examples/
│   ├── engineering_team.py
│   └── run_demo.py
├── src/role_runtime/
│   ├── context.py
│   ├── skill.py
│   ├── role.py
│   ├── compiler.py
│   ├── registry.py
│   ├── runtime.py
│   └── mcp/
│       ├── models.py
│       ├── binding.py
│       ├── protocol.py
│       ├── transport.py
│       └── client.py
└── tests/
```

## Design document

Read [`docs/01-role-object-model.md`](docs/01-role-object-model.md) for the
step-by-step architecture decisions, invariants, protocol boundaries, and the
terminal-state extension map.

## Protocol references

- https://modelcontextprotocol.io/specification/2026-07-28
- https://modelcontextprotocol.io/specification/2026-07-28/architecture
- https://modelcontextprotocol.io/specification/2026-07-28/server/tools
- https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http
- https://modelcontextprotocol.io/specification/2026-07-28/schema
