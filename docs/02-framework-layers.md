# Design 02 — Framework Layers

> **Partly superseded by [ADR 001](adr/001-native-mcp-server.md) as of v0.0.4.**
>
> Everything below about the object model, the declarative front end, and the
> route/active split still holds. What changed is the **main path**. This
> document describes rendering a declaration into per-runtime context files as
> the primary route to an agent; in v0.0.4 that became a side road, and the
> primary route is a native MCP server the runtimes connect to.
>
> Read this for the layer boundaries and the reasoning behind them; read ADR 001
> for what replaced the target adapters at the centre, and why.

## 1. Purpose

Design 01 records the object model: what a Role is, what it may reach, and how
much becomes visible at each disclosure level. This document records the shape
built around that model in `0.0.3` — how a business project states its context,
how one statement reaches several agent runtimes, and which parts of the
package are optional.

The one-sentence definition the rest of this document serves — accurate for
0.0.3, and revised in v0.0.4 as noted above:

```text
Contexture is a context framework. An application declares roles, skills,
tools, and resources once; the framework progressively discloses them and
translates them into the skill and MCP surfaces different agent runtimes
consume.
```

The v0.0.4 revision replaces the second clause: the framework progressively
discloses them and **serves** them over MCP, rather than translating them into
what each runtime reads.

It is not an agent runtime, not a protocol, and not a file generator that
serializes one class into one file.

## 2. The problem this shape solves

Connecting one system to several agents means maintaining the same context
several times:

| Runtime | Context | Skills | MCP |
|---|---|---|---|
| Claude Code | `CLAUDE.md` | `.claude/skills/**/SKILL.md` | `.mcp.json` |
| Codex | `AGENTS.md` | — inlined | `~/.codex/config.toml` |
| Cursor | `.cursor/rules/*.mdc` | `.cursor/rules/*.mdc` | `.cursor/mcp.json` |

Each file answers the same questions. Only the formats differ, and they drift
apart on the first independent edit. The framework's job is to make the answers
a single program and the formats a rendering concern.

## 3. Layers

```text
Business Layer            declares roles, skills, tools, resources
        │  inherits / composes
contexture.core           object model, registry, validation, disclosure rules
        │  compile
contexture.compiler       route / active selection over the model
        │  navigate
contexture.discovery      refs, the capability graph, discover / get_context
        │  project
contexture.server         the native MCP server — the only layer importing mcp
        │  MCP
External Agent Runtime    LLM loop, planning, tool selection  (out of scope)

        ┊  side road
contexture.targets        Claude Code · Codex · Cursor artifacts
```

The dependency rule is one-directional and enforced by the package layout: a
layer may import the ones below it and never the reverse. Importing
`contexture.core` pulls in no transport, no adapter, and no runtime.

`0.0.2` had this layering as an idea and a flat package. `0.0.3` makes the
package structure state it, because a layering that only exists in prose stops
being true the first time somebody adds a convenient import.

### 3.1 Why `role_runtime` was renamed

The package was called `role_runtime` while the runtime was the whole product.
Under this shape the runtime is the optional layer and the model is the
product, so the name pointed at the least essential part. It is now
`contexture`, matching both the project and the definition above.

## 4. Declaration

### 4.1 Two doors onto one object

A Role can be built two ways, and both produce the same object:

```python
# imperative — for context assembled at runtime
Role(name="k8s-operator", description="...", instructions="...")

# declarative — for context a project owns and edits
class K8sOperator(Role):
    """Operate and diagnose Kubernetes workloads."""

    instructions = "Inspect before changing the cluster."

    diagnose = DiagnoseDeployment
    get_pods = GetPods
    runbook = RolloutRunbook
```

A declared Role *is* a `Role`, so every consumer — compiler, registry, adapter,
server — accepts either without knowing which door was used. Declaration adds
a second way to state the same thing; it never becomes a parallel type.

### 4.2 Why this does not contradict "composition over inheritance"

Design 01 §5 argues that a team is modeled by composition, not inheritance.
That still holds. The two mechanisms answer different questions:

```text
class K8sOperator(Role)      what this node IS      — a kind of context node
children=[troubleshooter]    what this node HOLDS   — the team structure
```

Subclassing never expresses containment. A declared role that coordinates other
roles holds them in `children`, exactly as an imperatively built one does; the
class body simply lists them.

### 4.3 What a class body contributes

| Class body | Becomes |
|---|---|
| class name | the node name, kebab-cased (`K8sOperator` → `k8s-operator`) |
| docstring, first paragraph | the routing description |
| `instructions` | the active-level instructions |
| `name` / `description` | explicit overrides for the two derivations |
| a `Skill` class or instance | an entry in `skills` |
| a `Role` class or instance | an entry in `children` |
| a `Tool` class or instance | an entry in `tools` |
| a `Resource` class or instance | an entry in `resources` |

Members are collected across the whole MRO, base classes first, so a subclass
inherits what its parent declared and may replace any member by rebinding its
attribute. Declaration order is preserved, which keeps rendered surfaces stable
across runs.

Only a class's *own* docstring counts as its description. Python hands an
undocumented subclass its parent's `__doc__`, and routing agents on a sentence
that describes a different role is worse than refusing to guess.

### 4.4 Failing at class creation

Contradictions a reader cannot see by looking at one attribute are rejected
while the class is being created, not at first use:

- a Role or Skill with no `instructions`;
- a class with no description and no docstring;
- two skills, two children, or two bindings that collide on name or server id;
- a scalar declared as something other than a string.

This is the payoff of declaration: import the module and the shape is checked.

### 4.5 Two implementation constraints worth recording

Both come from `@dataclass(slots=True)`, which **rebuilds the class object**
rather than decorating it in place.

1. A zero-argument `super()` inside `__init_subclass__` raises `TypeError`. The
   method's `__class__` cell still points at the discarded original class, so
   the implicit lookup fails. Every such call names its class explicitly.
2. `getattr(cls, "name")` returns the *slot descriptor*, not `None`, when
   nobody declared a value. Reading a declared scalar therefore walks the MRO's
   `__dict__` and treats a `MemberDescriptorType` as "undeclared".

Neither is visible from the code that trips over it, which is why they are
written down here and commented at both call sites.

## 5. Targets

### 5.1 The adapter contract

A `TargetAdapter` is the compiler's back end:

```python
class TargetAdapter(ABC):
    name: ClassVar[str]
    capabilities: ClassVar[TargetCapabilities]

    def render(self, role, *, registry=None) -> ArtifactSet: ...
```

Two rules hold for every adapter.

**Nothing is written.** `render` returns paths and bytes. Installing them is a
separate call in `contexture.targets.writer`, which is the only module in the
package that touches a filesystem. That keeps adapters testable without a
temporary directory and makes a dry-run preview possible.

**Losses are reported.** Each adapter declares a `TargetCapabilities`, and the
base class turns the gap between those capabilities and the declaration into
notes. An adapter states its limits once as data instead of remembering to
write the same warnings by hand.

### 5.2 The capability matrix

| | Claude Code | Codex | Cursor |
|---|---|---|---|
| separate skill files | yes | no | yes |
| MCP configuration | yes | yes (user-level) | yes |
| per-role tool allowlist | no | no | no |
| progressive disclosure | yes | no | yes |
| nested roles | yes | no | no |

Every "no" becomes a note on the rendered set. The most consequential is the
allowlist row: no target can express a per-role tool grant, so on all three the
grant is enforced by the host and not by the generated file. Saying that out
loud is the point — a surface that looked authoritative while silently
widening a grant would be a security problem, not a formatting one.

### 5.3 Determinism

`Artifact.digest` and `ArtifactSet.digest` are content hashes over sorted
paths and bodies. Recompiling and comparing digests is how a caller detects
that an installed surface has drifted from the declaration. The writer uses the
same comparison per file so unchanged files are left alone and only real
changes touch timestamps or wake file watchers.

## 6. The inbound boundary

Through `0.0.3` this section described a port — `MCPHostPort` — that an
application would implement to serve its declarations, alongside an `MCPClient`
for calling somebody else's server. Both are gone.

`contexture.server` is the inbound boundary now, and it is not a port but a
server: `ContextureApp` takes the declared roots, projects them onto the
official SDK, and runs. It is the only layer that imports `mcp`, which is what
keeps the object model describable without a wire protocol in the room. ADR 001
records why the arrow turned around; ADR 003 records why the outbound half was
removed rather than kept as an option.

## 7. Where a tool call happens

A tool call is not a kernel object. The model *describes* a tool and knows how
to execute one; deciding whether to call it belongs to an agent runtime, and
carrying the call over the wire belongs to the SDK:

```text
core           describes a Tool, and owns its `invoke`
server         derives the schema, projects it, dispatches the call
agent runtime  decides whether to call at all          (out of scope)
```

There is no `ToolCall` or `ToolResult` type in this package. The SDK owns the
wire form, and inventing a parallel one would be a second protocol wearing the
first one's clothes.

## 8. Invariants added in 0.0.3

### Layering

1. `contexture.core` imports no layer above it.
2. Only `contexture.targets.writer` performs filesystem I/O.
3. No layer below `contexture.server` performs network I/O.

### Declaration

1. A declared node is substitutable for an imperatively built one.
2. Subclassing states identity, never containment.
3. Declaration order and MRO order together fix member order.
4. A class's own docstring is the only docstring that describes it.
5. Contradictions are raised at class creation, not first use.

### Targets

1. `render` never writes.
2. Every capability a target cannot express produces a note.
3. Identical declarations render byte-identical artifacts.
4. An artifact path is relative and stays inside the project tree.
5. A role's rendered surface lists only that role's own tools and resources.

## 9. Deliberate non-goals, restated

Unchanged from Design 01 §22, and reinforced here: no agent loop, no planner,
no model client, no orchestration, no new protocol. `0.0.3` added a declaration
front end and several rendering back ends around the same kernel; `0.0.4` turned
the main path into a server and removed the client half entirely (ADR 001, ADR
003). Neither moved the kernel toward being an agent runtime.
