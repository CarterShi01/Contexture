# Design 01 — Progressive Role Object Model

> Scope note: this document covers the **object model** — what a Role is, what
> it may reach, and how much becomes visible at each disclosure level. The
> framework built around it (class-syntax declaration, target adapters, the
> layer boundaries, the inbound host port) is
> [Design 02](02-framework-layers.md).

## 1. Purpose

This document records the design reasoning behind the object model at the
center of Contexture. It begins with the members introduced during the
incremental design sequence and then shows how those members fit into the
terminal architecture.

The design targets Python and uses the Model Context Protocol revision
`2026-07-28`, whose wire messages use JSON-RPC 2.0.

The most important architectural separation is:

```text
MCP defines how a Host communicates with capability providers.
This project defines how a Host organizes those capabilities into Roles.
```

`Role`, `Skill`, `ContextNode`, `MCPBinding`, `tool_ref`, `resource_ref`, and the
compile levels are Host-layer concepts. They are not additions to the MCP wire
protocol.

Tools and Resources are the two capability kinds a Server exposes, and this
model deliberately has no third, host-private kind beside them — see §4.1.

## 2. Design goals

The model should satisfy six goals.

1. A Role must be an ordinary Python object.
2. A Role may contain child Roles through object composition.
3. A Role may reuse Skills without copying their implementation knowledge.
4. A Role may use only an explicitly granted subset of an MCP Server.
5. The Host must progressively expose context instead of loading the complete
   team, every Skill, and every Tool schema at once.
6. One compile interface should work across different context-node types.

The model should remain understandable before adding registries, transports,
policy engines, persistence, or distributed execution.

## 3. Protocol baseline

The formal MCP `2026-07-28` revision is stateless at the protocol core. Every
request is self-contained and carries its protocol version and client
capabilities. MCP messages use JSON-RPC 2.0.

For Tools, the protocol defines concepts such as:

- `tools/list`
- `tools/call`
- Tool `name`
- optional Tool `description`
- required Tool `inputSchema`
- optional Tool `outputSchema`
- optional Tool annotations

The Role model does not redefine these fields. `MCPTool` wraps them so that a
protocol Tool can participate in the Host's progressive context lifecycle.

## 4. The vocabulary

| Type | Question answered | Primary responsibility |
|---|---|---|
| `Role` | Who owns this responsibility? | Coordinate a bounded area of work. |
| `Skill` | How should this class of work be performed? | Supply reusable workflow knowledge. |
| `MCPTool` | Which external function can be invoked? | Describe one protocol-callable operation. |
| `MCPResource` | Which contextual data can be read? | Describe addressable content without loading it. |
| `MCPServer` | Which provider owns these catalogs? | Own and refresh Tool and Resource catalogs. |
| `MCPBinding` | Which Server capabilities may this Role use? | Project a least-privilege Tool and Resource subset. |
| `RoleCompiler` | What should enter the current LLM context? | Produce a progressive context representation. |
| `RoleRuntime` | What may actually execute? | Recheck grants and invoke MCP operations. |

A useful shorthand is:

```text
Role        = who
Skill       = how
MCPTool     = executable operation
MCPResource = readable context
MCPServer   = capability provider
MCPBinding  = granted provider view
Compiler    = context disclosure
Runtime     = execution enforcement
```

### 4.1 Why there is no separate Data type

An earlier revision of this model carried its own `DataSource`, `DataBinding`,
and `DataProvider` types beside the MCP ones. That produced two parallel
least-privilege systems answering the same question — which external thing may
this Role touch — with two grant formats, two runtime paths, and two places to
audit.

MCP already defines Resources for exactly this purpose. The host-layer Data
types were therefore removed and every form of contextual information —
documents, configuration, knowledge, runbooks — is now addressed as an
`MCPResource` behind the same `MCPBinding` that grants Tools.

A data source that no MCP server exposes is reached by putting a small local
MCP server in front of it, not by reintroducing a second abstraction.

## 5. Step 1: Role as a recursive composite

The first model required only three members:

```python
@dataclass
class Role:
    name: str
    description: str
    children: list["Role"]
```

`children` is the key object-oriented decision. A child Role is a member object,
not necessarily a Python subclass.

```text
engineering-team
├── k8s-troubleshooter
├── k8s-operator
└── github-liaison
```

This is composition. It models an operational team structure directly and
allows the same Role type to represent every level of the tree.

Python inheritance would answer a different question:

```text
Is FinancialResearcher a specialized kind of Researcher?
```

Composition answers the team question:

```text
Does ResearchLead contain and coordinate Researcher Roles?
```

The team model primarily needs composition.

## 6. Step 2: routing description versus active instructions

A single prompt field is insufficient because routing and execution have
opposite context requirements.

- `description` should be small and broadly visible.
- `instructions` may be detailed and should become visible only after the Role
  is selected.

```text
description  = when should the Host or model select this Role?
instructions = how should the selected Role behave?
```

This distinction is the foundation of progressive disclosure.

## 7. Step 3: Skill as reusable workflow knowledge

A Role owns a responsibility, but a Skill contains a reusable method.

For example:

```text
Role:  k8s-troubleshooter
Skill: inspect-pod-failure
```

The Skill can explain a sequence such as:

1. Inspect Pod status.
2. Read current logs.
3. Read previous logs after a restart.
4. Inspect Events.
5. Correlate the evidence.

The Skill does not need to own the external functions that perform those steps.
It can guide the model to use several MCP Tools, possibly from several Servers.

This separation prevents workflow knowledge from being copied into every Role
or hard-coded into Tool implementations.

## 8. Step 4: ContextNode and the uniform lifecycle

Once both Role and Skill needed the same route-versus-active lifecycle, the
model introduced `ContextNode`.

```python
class ContextNode(ABC):
    name: str
    description: str

    def compile(self, level): ...
    def _compile_route(self): ...
    @abstractmethod
    def _compile_active(self): ...
```

The base class deliberately does not own every field that happens to appear in
current subclasses.

For example:

- Role active context contains `instructions` plus child routes.
- Skill active context contains `instructions`.
- MCP Tool active context contains `inputSchema`, not instructions.
- MCP Resource active context contains a URI and media type, never content.

The stable abstraction is the lifecycle, not a forced universal payload.

This supports polymorphism:

```python
node.compile("route")
node.compile("active")
```

The caller does not need a growing `isinstance` chain for Role, Skill, Tool, and
Resource.

## 9. The two compile levels

### 9.1 Route level

The route level is intentionally small:

```json
{
  "kind": "mcp_tool",
  "name": "get_pod_logs",
  "description": "Read logs from a Kubernetes Pod container."
}
```

Its purpose is selection, not execution.

### 9.2 Active level

The active level reveals type-specific details. An active MCP Tool exposes its
schema:

```json
{
  "kind": "mcp_tool",
  "name": "get_pod_logs",
  "description": "Read logs from a Kubernetes Pod container.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "namespace": { "type": "string" },
      "pod": { "type": "string" }
    }
  }
}
```

An active Role does not recursively activate all descendants. It exposes:

- its own instructions;
- direct child Role route cards;
- Skill route cards;
- granted MCP Tool route cards;
- granted MCP Resource route cards.

This invariant prevents an accidental full-tree context expansion.

## 10. Why `kind` belongs in the route card

Before Tools existed, a route card containing only `name` and `description` was
sufficient. Once a Role could expose child Roles, Skills, Tools, and Resources,
the Host needed to know how the selected item should be activated.

```json
{
  "kind": "skill",
  "name": "inspect-pod-failure",
  "description": "Diagnose a failing Pod."
}
```

`kind` is a Host routing field. It is not an MCP Tool field added to the wire
protocol.

## 11. Step 5: MCPTool as a ContextNode

`MCPTool` represents the protocol Tool declaration needed by the Host and LLM.
Its central fields are:

```python
MCPTool(
    name=...,
    description=...,
    input_schema=...,
    output_schema=...,
    annotations=...,
)
```

The Tool is a descriptor. It is not the network connection and does not own the
transport.

```text
MCPTool describes what can be called.
MCPClient and MCPTransport perform the call.
```

A Tool's route surface omits `inputSchema`. Its active surface includes the full
schema only after selection.

The model validates the MCP invariant that Tool arguments are JSON objects, so
the root of `inputSchema` must use `type: "object"`.

## 11.1 MCPResource as a ContextNode

`MCPResource` describes one readable address exposed by a Server:

```python
MCPResource(
    name="kubernetes-incident-runbook",
    description="Operational guidance for common Kubernetes incidents.",
    uri="resource://kubernetes/runbook/incidents",
    mime_type="text/markdown",
)
```

The disclosure boundary that matters for a Resource is not route versus active
but **descriptor versus content**. Its route card carries the routing name and
description; its active surface adds the URI, media type, and size. Neither
level ever carries bytes. Content is fetched by `MCPClient.read_resource`
after `RoleRuntime` authorizes the read.

```text
Compiling a Resource yields metadata.
Reading a Resource yields content.
```

Resources need no read-only classification. MCP defines no write operation on a
Resource, so appearing on `allowed_resources` is the entire grant.

## 12. Step 6: MCPServer is infrastructure, not ContextNode

An MCP Server owns both catalogs and provides the execution destination.

```python
MCPServer(
    server_id="production-kubernetes",
    name="kubernetes",
    tools=[...],
    resources=[...],
)
```

The Server does not inherit `ContextNode` because the LLM normally selects a
business operation or a document, not an infrastructure endpoint.

```text
The LLM selects get_pod_logs.
The Host routes that selection to production-kubernetes.
```

Keeping `MCPServer` outside the context-node hierarchy prevents transport and
connection details from leaking into the LLM-facing abstraction.

## 13. Host references versus protocol names

MCP Tool names and Resource URIs are scoped to one Server. Two Servers may both
expose `search`, `get_logs`, or `resource://repo/README.md`.

The Host therefore creates unique references:

```text
production-kubernetes/get_pod_logs
production-kubernetes/resource://kubernetes/runbook/incidents
```

Both use the same shape, `<server_id>/<protocol identifier>`, and both are
parsed by splitting on the **first** separator only. Because a Server id may not
contain `/`, a Resource URI keeps working as the remainder even though it
contains slashes and a scheme.

The names serve different purposes:

```text
tool_ref      = Host-side routing and disambiguation
Tool.name     = value sent in MCP tools/call params.name
resource_ref  = Host-side routing and disambiguation
Resource.uri  = value sent in MCP resources/read params.uri
```

The Host must not accidentally send a full host reference as the protocol name
or URI.

## 14. Step 7: MCPBinding as the relationship object

A direct Role-to-Server reference grants too much. If a Server exposes read,
write, and destructive Tools, a read-only Role should not automatically receive
the entire catalog.

`MCPBinding` sits between Role and Server:

```python
MCPBinding(
    server=kubernetes_server,
    allowed_tools=["get_pod_logs", "get_events"],
    read_only_tools=["get_pod_logs", "get_events"],
    allowed_resources=["resource://kubernetes/runbook/incidents"],
)
```

The object graph becomes:

```text
Role
└── MCPBinding
    ├── server: MCPServer
    ├── allowed_tools
    ├── read_only_tools
    └── allowed_resources
```

`allowed_tools` and `allowed_resources` are both deny-by-default. An empty list
grants nothing.

`read_only_tools` is a trusted Host classification and must be a subset of
`allowed_tools`. Any allowed Tool not on the trusted read-only list requires
explicit approval in the Runtime.

There is deliberately no `read_only_resources`. MCP Resources are read-only at
the protocol level, so the allowlist alone is the complete grant.

Every refusal that reaches a Host through `get_mcp_binding_for_tool_ref` or
`get_mcp_binding_for_resource_ref` is a `CapabilityDeniedError`, including the
case where the Role holds no binding to the named Server at all. A Host
catching authorization failures therefore needs one exception type, not two.

## 15. Why protocol ToolAnnotations are not authorization

MCP Tool annotations such as `readOnlyHint` and `destructiveHint` are hints. A
remote Server controls them, so a Host cannot safely treat them as the source of
truth for authorization.

The project keeps annotations for display, planning, and diagnostics, but the
execution policy uses the Host-owned Binding.

```text
Remote annotation = untrusted hint
Host Binding       = trusted grant and classification
```

## 16. Current object graph

```mermaid
classDiagram
    class ContextNode {
        +name: str
        +description: str
        +compile(level)
    }

    class Role {
        +instructions: str
        +children: Role[]
        +skills: Skill[]
        +mcp_bindings: MCPBinding[]
    }

    class Skill {
        +instructions: str
    }

    class MCPTool {
        +input_schema
        +output_schema
        +annotations
    }

    class MCPResource {
        +uri: str
        +mime_type: str
        +size: int
    }

    class MCPServer {
        +server_id: str
        +tools: MCPTool[]
        +resources: MCPResource[]
    }

    class MCPBinding {
        +allowed_tools: str[]
        +read_only_tools: str[]
        +allowed_resources: str[]
    }

    ContextNode <|-- Role
    ContextNode <|-- Skill
    ContextNode <|-- MCPTool
    ContextNode <|-- MCPResource
    Role *-- Role : children
    Role *-- Skill : skills
    Role *-- MCPBinding : grants
    MCPBinding --> MCPServer : server
    MCPServer *-- MCPTool : tool catalog
    MCPServer *-- MCPResource : resource catalog
```

## 17. Terminal-state additions

The project includes the natural next layers so the current model does not need
to be redesigned later.

### 17.1 Resource grants

Resources travel through the same `MCPBinding` that grants Tools. A Role that
should read a runbook lists its URI in `allowed_resources`; a Role that should
not simply omits it and never sees the route card.

`RoleRuntime.read_resource` rechecks the grant and calls `resources/read`. The
compiler is not involved in loading content at any point.

### 17.2 RoleCompiler

The compiler receives a `CompileRequest` and optional `CapabilitySelection`.

```python
CompileRequest(
    selection=CapabilitySelection(
        skill_names=("inspect-pod-failure",),
        tool_refs=("production-kubernetes/get_pod_logs",),
        resource_refs=(
            "production-kubernetes/resource://kubernetes/runbook/incidents",
        ),
    )
)
```

The result contains:

- the active Role surface;
- only the selected active Skill details;
- only the selected active Tool schemas;
- only the selected active Resource descriptors.

The compiler never executes a Tool and never reads a Resource. It produces
context.

### 17.3 RoleRegistry

The registry resolves explicit paths such as:

```text
engineering-team/k8s-troubleshooter
```

It also detects recursive object-composition cycles. Shared Role objects may be
reachable through multiple paths, but a Role cannot eventually contain itself.

### 17.4 RoleRuntime

The Runtime is the execution boundary.

For a Tool call, it performs this sequence:

```text
Resolve active Role path
        ↓
Resolve Role's MCPBinding from tool_ref
        ↓
Verify the Tool is explicitly allowed
        ↓
Check the Host read-only classification
        ↓
Require approval when necessary
        ↓
Select MCPClient by server_id
        ↓
Send tools/call with the original Tool.name
```

For a Resource read, the approval step is absent because the protocol has no
write path:

```text
Resolve active Role path
        ↓
Resolve Role's MCPBinding from resource_ref
        ↓
Verify the Resource is explicitly allowed
        ↓
Select MCPClient by server_id
        ↓
Send resources/read with the original Resource.uri
```

The Runtime checks the Binding again even though ungranted capabilities were
already hidden from the LLM context. Context omission improves behavior;
Runtime checks provide the actual Host boundary.

`refresh_server_catalog` rediscovers both catalogs and validates both against
existing grants **before replacing either**, so a resource catalog that would
orphan a grant cannot leave the Server holding half-refreshed state.

### 17.5 MCPClient and MCPTransport

`MCPClient` builds self-contained requests with:

- `jsonrpc: "2.0"`;
- a non-null request id;
- the MCP method;
- required per-request `_meta` values;
- the protocol version `2026-07-28`;
- client implementation information;
- per-request client capabilities.

For Streamable HTTP, it builds the required routing headers:

- `MCP-Protocol-Version`;
- `Mcp-Method`;
- `Mcp-Name` where required;
- `Mcp-Param-*` values derived from valid `x-mcp-header` annotations.

The transport interface is separate so an application can use HTTP, stdio, a
mock transport, or another implementation without changing the Role model.

## 18. Complete progressive flow

A typical request follows this sequence:

```text
1. Compile engineering-team as active.
   - Root instructions are visible.
   - Child Role descriptions are visible.
   - Child instructions remain hidden.

2. Select k8s-troubleshooter.

3. Compile k8s-troubleshooter as active.
   - Troubleshooter instructions are visible.
   - Skill descriptions are visible.
   - Granted Tool descriptions are visible.
   - Granted Resource descriptions are visible.
   - Skill instructions, Tool schemas, and Resource URIs remain hidden.

4. Select inspect-pod-failure, get_pod_logs, and the runbook Resource.

5. Compile selected capabilities as active.
   - Skill instructions enter context.
   - get_pod_logs inputSchema enters context.
   - The runbook URI and media type enter context; its content does not.
   - Unrelated Tool schemas remain hidden.

6. The LLM produces Tool arguments, or asks to read the Resource.

7. RoleRuntime checks the MCPBinding again.

8. MCPClient sends tools/call using Tool.name, or resources/read using
   Resource.uri, to the bound Server.

9. The result is returned to the Host and can be added to the next LLM turn.
```

## 19. Core invariants

The implementation protects these invariants.

### Progressive-disclosure invariants

1. `route` never contains type-specific detailed execution content.
2. An active Role does not recursively activate descendants.
3. A selected capability is activated explicitly by the compiler.
4. Compiling a Resource yields a descriptor; only the Runtime yields content.

### Object-model invariants

1. Direct child Role names are unique within one Role.
2. Skill names are unique within one Role.
3. One Role has at most one Binding for a given Server id.
4. Role composition cannot contain cycles.

### MCP invariants

1. Tool names are unique within one Server catalog.
2. Resource URIs are unique within one Server catalog.
3. Tool `inputSchema` has an object root.
4. A Binding cannot grant a Tool or Resource absent from the Server catalog.
5. `read_only_tools` is a subset of `allowed_tools`.
6. `tool_ref` and `resource_ref` are used for Host routing only.
7. A refreshed catalog may not orphan an existing grant.
8. Every MCP request carries protocol metadata for `2026-07-28`.

### Security invariants

1. Hidden is not the same as unauthorized.
2. The Runtime rechecks grants immediately before execution.
3. Remote Tool annotations are not trusted authorization facts.
4. Non-read-only Tools require explicit approval in the reference Runtime.
5. Every authorization refusal is one exception type, `CapabilityDeniedError`.
6. The Server must still enforce its own authentication and authorization.

## 20. Why direct objects are retained

The current model stores direct Python objects:

```python
Role(children=[child_role])
MCPBinding(server=server)
MCPServer(tools=[tool], resources=[resource])
```

This is intentional because the goal is to make the object relationships easy
to understand.

A persisted or distributed system will likely split declaration and runtime:

```text
RoleSpec with stable references
        ↓ resolve/link
Role runtime objects with live clients and providers
```

The included Registry, Client map, and Provider map already establish the
boundaries needed for that future split. The core Role API does not need to
change when serialization is introduced.

## 21. Extension points

The terminal structure supports the following additions without changing the
core object hierarchy:

- persisted `RoleSpec` documents and versioned references;
- Skill packages loaded from local directories or registries;
- MCP Prompts and resource subscriptions;
- automatic multi-round-trip request handling;
- stdio transport;
- token-budget-aware context compilation;
- richer confirmation and organization policy engines;
- observability, audit events, and deterministic fingerprints;
- parallel child Role execution;
- team-level scheduling and shared workspaces.

Each belongs behind an existing boundary rather than inside the base Role class.

## 22. Deliberate non-goals

Contexture does not attempt to be a full MCP SDK or a complete multi-agent
orchestrator. In particular, it does not automatically implement every optional
MCP feature, LLM provider adapter, persistence backend, distributed scheduler,
or authorization system.

Its purpose is narrower and architectural:

```text
Provide a coherent, runnable object model that can grow from a simple Role tree
into a secure progressive Agent Host without invalidating the early concepts.
```

## 23. Code map

| Design concept | Source file |
|---|---|
| Context lifecycle | `src/contexture/core/context.py` |
| Skill | `src/contexture/core/skill.py` |
| Role | `src/contexture/core/role.py` |
| Class-syntax declaration | `src/contexture/core/declarative.py` |
| MCP Tool | `src/contexture/core/tools.py` |
| MCP Resource | `src/contexture/core/resources.py` |
| MCP Server and connections | `src/contexture/core/servers.py` |
| MCP Binding | `src/contexture/core/binding.py` |
| Role path registry | `src/contexture/core/registry.py` |
| Unified compiler | `src/contexture/compiler.py` |
| Target adapters | `src/contexture/targets/` |
| JSON-RPC and request metadata | `src/contexture/protocol/messages.py` |
| MCP transport | `src/contexture/protocol/transport.py` |
| MCP client | `src/contexture/protocol/client.py` |
| MCP host port | `src/contexture/protocol/host.py` |
| Execution runtime | `src/contexture/execution.py` |
| Complete example | `examples/engineering_team.py` |

## 24. Official references

- MCP specification: https://modelcontextprotocol.io/specification/2026-07-28
- Architecture: https://modelcontextprotocol.io/specification/2026-07-28/architecture
- Tools: https://modelcontextprotocol.io/specification/2026-07-28/server/tools
- Streamable HTTP: https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http
- Schema reference: https://modelcontextprotocol.io/specification/2026-07-28/schema
