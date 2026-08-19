# ADR 004 — Progressive disclosure as a lazily loaded role tree

**Status:** proposed
**Date:** 2026-08-19

This is a proposal, not an implemented decision. Nothing in it has been built.
It exists to be argued with.

## Context

### What progressive disclosure currently covers

`server/projection.py` registers every capability the graph can reach:

```python
for _, role, tool in graph.local_tools():        # every tool in the whole forest
    server.add_tool(tool.invoke, ...)
for _, role, resource in graph.local_resources():
    server.add_resource(...)
```

So the moment a host connects, it holds the name, description, input schema and
output schema of every tool, and the URI and description of every resource, for
every role in the forest — before the user has said anything.

What is actually deferred is narrower than the README implies. Only three things
are not resident: a Role's `instructions`, a Skill's `instructions`, and the
organizational structure — which role owns what.

### Why it grew that way

Not an oversight. MCP tool and resource lists are flat, and since the 2026-07-28
revision explicitly stateless: a server may not vary them per connection, nor as
a side effect of an earlier call. ADR 001 recorded this and drew the correct
conclusion for the role *tree* — it travels inside tool payloads. It did not draw
the same conclusion for tools and resources themselves, which stayed on the
surface because that is where the SDK puts them.

### What it costs

Sizing a mid-size platform team — 6 roles, 14 skills, 21 tools, 9 resources —
against per-item costs read off `src/contexture/examples/incident/` and rounded
(these are estimates from measured text lengths, not tokenizer output):

| item | tokens |
| --- | --- |
| one native tool entry (name, description, input schema, output schema) | ~150 |
| one routing card `{kind, name, description, ref}` | ~35 |
| one Skill's instructions | ~220 |
| one Role's instructions | ~60 |

```text
resident before the user says anything
  21 tools x 150  +  9 resources x 35  +  framework tools  +  instructions
  = 3,150         +  315               +  200              +  150       ~= 3,800
```

Against a full expansion of roughly 7,200, deferral saves about 47%, and every
token it saves is prose. A framework whose stated purpose is to keep hundreds of
capabilities out of context is, in its current form, deferring documentation.

### Two defects in the same layer

**Cards that cannot be opened.** `Role._compile_active` inlines
`available_sub_roles`, `available_skills`, `available_tools` and
`available_resources`, each item compiled at ROUTE level. A ref is a
`contexture.discovery` concept and `core` must not know it, so those inlined
cards carry no ref. The project has already named this failure, in
`tests/test_discovery.py`:

```python
def test_every_card_carries_the_ref_that_opens_it(self) -> None:
    """A card without a ref is a dead end: the agent can see it, not reach it."""
```

That test exercises `discover()` only. `get_context("role:...")` returns cards
with no refs, and no test looks. An agent that opens a role and then wants a
skill it saw there has to guess the ref syntax — which is the one thing refs
exist to prevent.

**Two operations, one answer.** `discover("role:X")` and
`get_context("role:X")` return the same child cards under different field names;
the only material difference is `instructions`. And `discover()` with no ref
returns `{"roots": [...]}`, sharing not one field name with the shape
`discover(ref)` returns. One tool, two schemas.

## Goals

1. **Nothing is resident that the current task does not need.** Tools and
   resources included, not only prose.
2. **Selection stays possible.** An agent choosing among sibling roles must see
   all of them at once. What cannot be seen together is guessed at, not chosen.
3. **Every card that is shown can be opened.** No ref is ever constructed by the
   model.
4. **Stateless.** Every call remains a pure function of its ref, as the 2026-07-28
   revision requires.
5. **The host keeps authorization.** A read/write distinction must survive
   whatever we do to the surface, and must not become an argument a model fills
   in.
6. **`core` stays free of the SDK, of JSON Schema, and of refs.**

### Non-goals

- Reducing round trips at any cost. A round trip is expensive, but so is a
  payload; both are counted below.
- Semantic search, embeddings, or ranking. Filtering is enough; the model does
  the semantic work.
- Preserving the current tool names on the wire.

## Decision A — the surface becomes a fixed gateway

Business tools and resources are no longer projected onto the MCP surface. The
surface is five tools, whatever the declaration contains:

```text
contexture_discover(ref=None, query=None)      readOnlyHint  the role skeleton
contexture_open(ref)                           readOnlyHint  open one node
contexture_read(ref)                           readOnlyHint  resource content
contexture_invoke_read_only(ref, arguments)    readOnlyHint  run a read-only tool
contexture_invoke(ref, arguments)              -             run a writing tool
```

A capability's schema now travels in a payload rather than on the surface, which
is what makes it deferrable. The SDK still derives it — verified against
`mcp 2.0.0`:

```python
Tool.from_function(probe, name="get_pod_logs").parameters
# {"properties": {...}, "required": ["namespace", "pod"], "type": "object"}
```

`Tool.from_function` needs no server, so schema derivation and argument
validation stay in `contexture.server` and `core` learns nothing about JSON
Schema.

### Why `invoke` is two tools

Splitting by `read_only` is how `readOnlyHint` survives the gateway. The
classification stops being a property of a tool the host can see, and becomes
*which entry point was used* — which the host can still see, and the model still
cannot forge, because of one server-enforced rule:

> **If the entry point's read-only stance disagrees with the ref's, the call is
> refused.**

A model may pick the wrong door. Picking it gets the call rejected, not
executed. This is the same principle as `read_only` never entering an input
schema, relocated.

### What Decision A costs

| cost | severity | mitigation |
| --- | --- | --- |
| Host UI no longer lists what the server can do | low | accepted |
| Schema validation leaves the wire | medium | `Tool.run` validates in-process against the derived schema |
| Per-tool approval prompts collapse to two | medium | the read-only split restores the distinction that matters |
| **Models are trained on native tool calls, not on a generic dispatch tool** | **medium-high** | none. This is the real risk and it is not theoretical |

The last row should gate implementation. Before building this, run the incident
demo both ways against a real host and compare completion rates.

## Decision B — eager skeleton, lazy capabilities

Disclosure splits by **kind**, not by depth:

> **The role skeleton is delivered whole. It is cheap, and it is the precondition
> for routing.**
>
> **Capability detail — skill descriptions, tool schemas, resource descriptors —
> is loaded per role, one level, on demand.**

A role card carries no schema, so the entire organizational chart of the worked
example costs about 210 tokens. Sibling roles are exactly what an agent must
compare to choose a branch; what is under the branches it does not choose is
irrelevant to that choice.

### Why not one level at a time, and why not the whole tree

Traced against the same example, for the task *"the checkout pod is
crashlooping"*, counting a round trip at ~200 tokens of reasoning and wrapper:

```text
one level per call        discover() -> discover(root) -> open(role) -> open(skill)
                          4 round trips     ~2,745 total

whole tree in one call    discover() returns all 50 nodes as cards
                          3 round trips     ~4,085 total
                          (~1,080 of it describing four domains never opened)

skeleton, then per role   discover() -> open(role) -> open(skill)
                          3 round trips     ~2,545 total
```

One level at a time pays a round trip to learn the shape of a level that costs
almost nothing to send. The whole tree pays for capability cards in branches the
agent never enters. Splitting by kind pays for neither, and it removes the
wrong-branch guess entirely, because every sibling is visible before the choice.

### Payload shapes

```jsonc
// contexture_discover()
{
  "roles": [
    {"ref": "role:k8s-platform",                   "description": "..."},
    {"ref": "role:k8s-platform/incident-response", "description": "..."}
  ],
  "truncated": []
}
```

Flat, depth-first. Hierarchy is already encoded in the ref path; nesting it again
in JSON is punctuation charged to the context window. `name` is the last path
segment and is not repeated.

```jsonc
// contexture_open("role:k8s-platform/incident-response")
{
  "ref": "role:k8s-platform/incident-response",
  "description": "...",
  "instructions": "...",
  "sub_roles": [],
  "skills":    [{"ref": "skill:...#diagnose-crashloop", "description": "..."}],
  "tools":     [{"ref": "tool:...#get_pod_logs", "description": "...",
                 "read_only": true, "input_schema": {"type": "object", ...}}],
  "resources": [{"ref": "resource:...#contexture://runbooks/crash-loop-backoff",
                 "description": "...", "mime_type": "text/markdown"}]
}
```

Opening a role delivers that role's own capabilities and does not recurse into
sub-roles. Tool schemas arrive with the role rather than one tool at a time,
because selecting a role is the moment its tools become likely; per-tool laziness
would buy a few hundred tokens for several round trips.

`truncated` and `query` are backstops for a forest whose skeleton is itself too
large, not part of the ordinary path.

### Skills stay pure text

Considered and rejected for now: letting a Skill declare the tools it uses, so
that opening a skill delivers its procedure together with exactly the schemas it
needs. Traced, that saves one round trip and the schemas of tools the procedure
does not touch (~2,020 against ~2,545).

It is rejected on simplicity, not on merit. It gives `Skill` a second kind of
content beyond its instructions, and it introduces a skill-to-tool reference that
needs rules for the case where the named tool lives in another role. If the
round trip proves expensive in practice, this is the first thing to revisit.

## Decision C — the class design

### Six responsibilities

```text
1. addressing    a position in the graph  <->  a string
2. location      a node bound to its position          <- missing today
3. rendering     a located node -> payload, at two depths
4. resolution    ref -> located node
5. skeleton      role-axis traversal of the forest, with a budget
6. schema        a Tool's JSON Schema                  <- server layer
```

Today 1, 3 and 4 are interleaved in one `if/elif` chain in `DisclosureEngine`,
and 2 does not exist. The missing one is what causes the ref defect.

### The currency of the layer

```python
@dataclass(frozen=True, slots=True)
class Cursor:
    """A node together with where it sits."""

    node: ContextNode
    ref: Ref
```

`core` nodes do not know where they are, and must not — knowing would mean
knowing about refs, which means knowing about the protocol. Everything except
self-description needs the position. Binding the two in one value object
collapses the whole layer to `ref -> Cursor -> payload`.

This is a simplified Zipper: a position in a data structure. It is deliberately
not a Decorator — it does not implement `ContextNode`.

### The line between "itself" and "around it"

```text
core, polymorphic                  navigation, uniform
-------------------------------    ------------------------------------------
node.compile(ROUTE)                cursor.card()   = compile(ROUTE) + ref
node.compile(ACTIVE)               cursor.detail() = compile(ACTIVE) + ref
  + instructions                                    + each member's card()
```

`Role._compile_active` loses its four `available_*` lists. A node describes
itself; it never describes its neighbours, because it cannot describe them
completely.

To let the cursor reach members without inspecting types, `ContextNode` gains one
method with an empty default:

```python
class ContextNode:
    def members(self) -> Mapping[str, tuple[ContextNode, ...]]:
        return {}                       # leaves

class Role(ContextNode):
    def members(self):
        return {"sub_roles": tuple(self.children), "skills": tuple(self.skills),
                "tools": tuple(self.tools), "resources": tuple(self.resources)}
```

This does not put protocol knowledge in `core`. A node exposing its own
composition is the same kind of statement as exposing its own description. What
it buys is that `Cursor.detail()` is one branch-free method covering all four
node types — the `get_context` `if/elif` chain disappears rather than moving.

### Structure

```text
                    Ref                value object: kind + path + leaf
                     |
             CapabilityGraph           repository: address in, Cursor out
                     |                   resolve(Ref) -> Cursor
                     |                   skeleton(budget) -> tuple[Cursor, ...]
                     |                   search(query) -> tuple[Cursor, ...]
                  Cursor  ------------> ContextNode        (core)
                     |                    compile(level), members()
                 Navigator               facade: discover(), open()
                     |
               SchemaSource              port, declared here
                     |
              SDKSchemaSource            adapter, in server, uses the SDK

    server also holds:
      ToolRunner    validates arguments, runs the tool, enforces the
                    read-only agreement between entry point and ref
      Projection    registers the five tools and wires them up
```

### Patterns used, and refused

| pattern | where | why |
| --- | --- | --- |
| Value object | `Ref` | an address should be a value: immutable, self-validating, parseable |
| Zipper / cursor | `Cursor` | position becomes first-class; without it a ref can only be produced by string assembly, which is exactly today's defect |
| Repository | `CapabilityGraph.resolve` | address in, object out, no mutation |
| Ports and adapters | `SchemaSource` | only the SDK can derive a schema, and navigation may not import `mcp`. Declaring the port above and implementing it below points the dependency the right way — the same move ADR 002 makes for `ToolContext` |
| Polymorphism | `compile(level)`, `members()` | a new node type edits one class and no dispatcher |
| Facade | `Navigator` | the server layer talks to one object |

Refused:

- **Visitor.** It needs `accept(visitor)` on the node, which puts rendering
  knowledge back into `core`. It optimizes for output formats multiplying; here
  the node types (four) and the depths (two) are both stable.
- **Command.** Five operations with no undo, no queue, no replay.
- **Strategy for disclosure depth.** Two depths. An enum is the whole design.
- **A separate compiler object.** With dispatch absorbed by polymorphism there is
  no dispatch left to house. See *Consequences*.

### The invariant each class exists to hold

| class | invariant |
| --- | --- |
| `Ref` | an address is either valid or cannot be constructed |
| `Cursor` | anything that can be shown can be opened — a card carries its ref by construction, not by convention |
| `CapabilityGraph` | resolution is a pure function of the ref |
| `SchemaSource` | navigation never imports `mcp` |
| `ToolRunner` | an entry point whose read-only stance disagrees with the ref is refused |

### Files

```text
contexture/navigation/          (replaces discovery.py)
  ref.py        Ref
  cursor.py     Cursor
  graph.py      CapabilityGraph
  ports.py      SchemaSource
  navigator.py  Navigator

contexture/server/
  schema.py     SDKSchemaSource
  runner.py     ToolRunner
  projection.py
  app.py
```

A package rather than one file, not for line count — the whole thing is around
400 lines — but because addressing, traversal policy and outward shape are three
different subjects that currently share a scroll bar.

## Consequences

**`compiler.py` has nothing left to do.** Its one production call site passes an
empty selection and its caller discards the wrapper. Under this design the
remaining dispatch is absorbed by `Cursor.detail()`, so the "which node, at which
level" policy that ADR 003 and Design 01 section 17.2 cite as its reason for
existing is no longer a policy anyone writes down: it is the ref's kind. If this
proposal is accepted, section 17.2 should be withdrawn and the compiler folded
away.

**`targets` renders a different shape.** The adapters read `Role`'s active
compilation, which loses its four `available_*` keys. They must ask the graph for
members instead.

**Two tests change meaning.** `test_every_card_carries_the_ref_that_opens_it`
should cover `open()` as well as `discover()`; that is the regression this
proposal exists to make impossible.

**Renaming `contexture_get_context` to `contexture_open`** is proposed alongside,
because everything in this layer is context and the name distinguishes nothing,
while "open one capability" is the actual mental model. It costs edits to the
README, three ADRs, `server/instructions.py`, the tests, and
`docs/verification/hosts.md`. That cost may not be worth paying; the rest of the
proposal does not depend on it.

## Open questions

1. **What unit does `skeleton(budget)` count?** Node count is predictable and
   easy to document ("200 roles"), but treats a long description and a short one
   alike. Rendered character count tracks the real cost more closely and needs no
   dependency, but the threshold is harder to explain. A real tokenizer is
   rejected: it is a dependency, and hosts do not share one.
2. **Does the generic dispatch tool degrade tool use in practice?** Measure
   before building.
3. **Does `query` belong in the first version**, or only once a forest is
   observed outgrowing its skeleton budget?
