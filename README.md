# Role Runtime Starter

A Python reference project for modeling an agent team as a tree of composable
`Role` objects. Each Role can contain child Roles, reusable Skills, restricted
MCP capabilities, and bound Data Sources. A unified compiler progressively
reveals only the context selected for the current LLM turn.

The MCP boundary targets the formal **2026-07-28** protocol revision and uses
**JSON-RPC 2.0** messages.

## What this project demonstrates

- `ContextNode` as the stable progressive-disclosure contract.
- `Role` as a composite responsibility boundary.
- `Skill` as reusable workflow knowledge.
- `MCPTool` as a protocol-compatible callable function descriptor.
- `MCPServer` as infrastructure and a tool-catalog owner.
- `MCPBinding` as the least-privilege relationship between a Role and a Server.
- `DataSource` plus `DataBinding` for explicitly granted contextual data.
- `RoleCompiler` as one compile interface for route and active context.
- `RoleRegistry` for role-path resolution and cycle detection.
- `RoleRuntime` for execution-time authorization, MCP calls, and data access.
- MCP request metadata, required Streamable HTTP routing headers, custom
  `x-mcp-header` extraction, JSON responses, and request-scoped SSE parsing.

## Mental model

```text
Role       = who owns the responsibility
Skill      = how a class of work should be performed
MCPTool    = which external function can be called
MCPServer  = which provider exposes the function
MCPBinding = which subset of that provider a Role may use
DataSource = which data exists
DataBinding= how the Role may access that data
Compiler   = what becomes visible in the current LLM context
Runtime    = what is actually authorized and executed
```

The main object graph is:

```text
Role
├── children: Role[]
├── skills: Skill[]
├── mcp_bindings: MCPBinding[]
│   └── server: MCPServer
│       └── tools: MCPTool[]
└── data_bindings: DataBinding[]
    └── source: DataSource
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
For a Data Source, that means its descriptor and URI, but not the data content.

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

The example builds this team:

```text
k8s-team
├── k8s-troubleshooter
│   ├── Skill: inspect-pod-failure
│   ├── Tool: production-kubernetes/get_pod_logs
│   ├── Tool: production-kubernetes/get_events
│   └── Data: runbook/kubernetes-incidents
└── k8s-operator
    ├── Tool: production-kubernetes/get_pod_logs
    ├── Tool: production-kubernetes/get_events
    └── Tool: production-kubernetes/delete_pod
```

The Troubleshooter cannot see or call `delete_pod`. The Operator can see it, but
the Runtime requires explicit approval because the Host did not classify that
tool as read-only.

## Small construction example

```python
from role_runtime import MCPBinding, MCPServer, MCPTool, Role, Skill

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

server = MCPServer(
    server_id="production-kubernetes",
    name="kubernetes",
    description="Kubernetes cluster operations.",
    tools=[get_pod_logs],
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
        )
    ],
)
```

## Host reference versus MCP protocol name

The Host uses a globally unique reference:

```text
production-kubernetes/get_pod_logs
```

The MCP `tools/call` request still sends the original protocol tool name:

```json
{
  "method": "tools/call",
  "params": {
    "name": "get_pod_logs",
    "arguments": {}
  }
}
```

`tool_ref` is a Host routing construct. It is not an MCP protocol field.

## Security model

The project uses defense in depth:

1. An ungranted Tool is omitted from the Role's LLM routing surface.
2. `MCPBinding` checks the grant again when a Tool is activated.
3. `RoleRuntime` checks the grant again immediately before execution.
4. A Tool not explicitly Host-classified as read-only requires approval.
5. The MCP Server remains responsible for its own authentication and
   authorization.

MCP `ToolAnnotations` are retained for display and planning, but are treated as
untrusted hints. They are never the authorization source of truth.

## MCP 2026-07-28 boundary

The focused client in this project implements the parts needed by the Role
Runtime example:

- JSON-RPC 2.0 request and response validation.
- Required per-request `_meta` fields.
- `tools/list` pagination and catalog refresh.
- `tools/call` requests and result parsing.
- `MCP-Protocol-Version`, `Mcp-Method`, and `Mcp-Name` headers.
- `x-mcp-header` validation, extraction, and Base64 sentinel encoding.
- Streamable HTTP JSON responses and request-scoped SSE responses.

This repository is a terminal-state architecture for the Role model, not a full
replacement for a complete MCP SDK. It does not automatically drive all
optional MCP features such as long-lived subscriptions, Prompts, automatic
multi-round-trip input handling, or every authorization flow. Those features
belong behind the existing `MCPTransport` and `MCPClient` boundaries.

## Project layout

```text
role-runtime-starter/
├── docs/
│   └── 01-role-object-model.md
├── examples/
│   ├── kubernetes_team.py
│   └── run_demo.py
├── src/role_runtime/
│   ├── context.py
│   ├── skill.py
│   ├── role.py
│   ├── data.py
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
