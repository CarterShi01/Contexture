# ADR 004 — Progressive disclosure as a lazily loaded role tree


> **One detail superseded by [ADR 013](013-a-constructor-is-the-declaration.md).**
> The member keys in an opened role are `roles`, `skills`, `tools`. The rule
> this ADR decided — a whole sibling set per call, never a subtree — is
> unchanged.
**Status:** accepted, implemented in v0.1.0
**Date:** 2026-08-19

## Context

### What progressive disclosure used to cover

`server/projection.py` registered every capability the graph could reach:

```python
for _, role, tool in graph.local_tools():        # every tool in the whole forest
    server.add_tool(tool.invoke, ...)
```

So the moment a host connected it held the name, description, input schema and
output schema of every tool, and the URI and description of every resource, for
every role — before the user had said anything. What was actually deferred was
narrower than the README implied: a Role's `instructions`, a Skill's
`instructions`, and which role owned what.

### Why it grew that way

Not an oversight. MCP tool and resource lists are flat, and since the
2026-07-28 revision explicitly stateless: a server may not vary them per
connection, nor as a side effect of an earlier call. ADR 001 recorded this and
drew the right conclusion for the role *tree* — it travels inside tool payloads.
It did not draw the same conclusion for tools and resources themselves, which
stayed on the surface because that is where the SDK puts them.

### What it cost

Sizing a mid-size platform team — 6 roles, 14 skills, 21 tools, 9 resources —
against per-item costs read off the example package and rounded (estimates from
measured text lengths, not tokenizer output):

```text
resident before the user says anything
  21 tools x 150  +  9 resources x 35  +  framework tools  +  instructions
  = 3,150         +  315               +  200              +  150      ~= 3,800
```

Against a full expansion of roughly 7,200, deferral saved about 47%, and
everything it saved was prose. A framework whose stated purpose is keeping
hundreds of capabilities out of context was deferring documentation.

### Two defects in the same layer

**Cards that could not be opened.** `Role._compile_active` inlined
`available_sub_roles`, `available_skills`, `available_tools` and
`available_resources`. A ref was a `contexture.discovery` concept and `core`
must not know one exists, so those cards carried no ref. The suite had already
named the failure — *"a card without a ref is a dead end: the agent can see it,
not reach it"* — and checked it only on the `discover` path, while
`get_context("role:...")` returned exactly such cards.

**Two operations, one answer.** `discover("role:X")` and `get_context("role:X")`
returned the same child cards under different field names, differing only by
`instructions`. And `discover()` with no ref returned `{"roots": [...]}`,
sharing no field name with the shape `discover(ref)` returned.

## Goals

1. Nothing is resident that the current task does not need — tools and
   resources included, not only prose.
2. Selection stays possible: an agent choosing among sibling roles must see all
   of them at once. What cannot be seen together is guessed between.
3. Every card that is shown can be opened. No ref is ever assembled by a model.
4. Stateless: every call remains a pure function of its ref.
5. The host keeps authorization, and the read/write distinction survives.
6. `core` stays free of the SDK, of JSON Schema, and of refs.

## Decision A — the surface is a fixed gateway

Business tools and resources are no longer projected. The surface is five
tools, whatever the declaration contains:

```text
contexture_discover                readOnlyHint   the role skeleton
contexture_open(ref)               readOnlyHint   one node's detail plus cards
contexture_read(ref)               readOnlyHint   a resource's content
contexture_invoke_read_only(...)   readOnlyHint   run a tool that only reads
contexture_invoke(...)             -              run a tool that changes things
```

A capability's schema now travels in a payload rather than on the surface,
which is what makes it deferrable. The SDK still derives it —
`Tool.from_function` needs no server, so derivation and argument validation stay
in `contexture.server` and `core` learns nothing about JSON Schema.

### Why `invoke` is two tools

Splitting by `read_only` is how `readOnlyHint` survives the gateway. The
classification stops being a property of a tool the host can see and becomes
*which entry point was used*, which the host can still see and a model still
cannot forge, because of one server-enforced rule:

> **If the entry point's read-only stance disagrees with the ref's, the call is
> refused.**

A model may pick the wrong door. Picking it gets the call rejected, not
executed. This is the same principle as `read_only` never entering an input
schema, relocated.

### What Decision A costs

| cost | mitigation |
| --- | --- |
| Host UI no longer lists what the server can do | accepted; the roster in the instructions replaces it |
| Schema validation leaves the wire | `Tool.run` validates in-process against the derived schema |
| Per-tool approval prompts collapse to two | the read-only split keeps the distinction that matters |
| **Business tools lose their output schema** | none. A gateway's return type is the union of every tool's, which is `Any`. `GetPodStatus.invoke` is annotated `-> PodStatus` and the SDK would have derived structured output from it; through the gateway the values arrive as text. Asserted in `test_stdio_server.py` rather than left implicit |
| **Models are trained on native tool calls, not a generic dispatch tool** | none. This is the real risk and it is not theoretical |

The last row is why the demo now declares three roles: a one-role tree sits on
the wrong side of this trade, and a new reader's first impression should not be
of the case where the argument fails.

## Decision B — eager skeleton, lazy capabilities

Disclosure splits by **kind**, not by depth:

> **The role skeleton is delivered whole.** It is cheap — a role card is a name,
> a sentence and a path — and it is the precondition for routing.
>
> **Capability detail waits.** Skill descriptions, tool schemas and resource
> descriptors arrive when the role holding them is opened, one level, on demand.

Traced against the six-role example for *"the checkout pod is crashlooping"*,
counting a round trip at ~200 tokens of reasoning and wrapper:

```text
one level per call        4 round trips     ~2,745
whole tree in one call    3 round trips     ~4,085   (~1,080 of it four domains
                                                      that are never opened)
skeleton, then per role   3 round trips     ~2,545
```

One level at a time pays a round trip to learn the shape of a level that costs
almost nothing to send. The whole tree pays for capability cards in branches the
agent never enters. Splitting by kind pays for neither, and removes the
wrong-branch guess entirely, because every sibling is visible before the choice.

The skeleton also ships in the server's instructions. It is static, it is small,
and without it a gateway presents five tools whose names all begin
`contexture_` and no sign that any of them lead to Kubernetes. When a forest
outgrows the budget the roster is cut and says so, and `contexture_discover` is
how the rest is read.

### Skills stay pure text

Considered and rejected: letting a Skill declare the tools it uses, so that
opening a skill delivers its procedure together with exactly the schemas it
needs. Traced, that saves one round trip and the schemas of tools the procedure
does not touch (~2,020 against ~2,545).

Rejected on simplicity, not on merit. It gives `Skill` a second kind of content
and introduces a skill-to-tool reference needing rules for the case where the
named tool lives in another role. If the round trip proves expensive in
practice, this is the first thing to revisit.

## Decision C — one class

```python
tree.skeleton()      # every role in the forest, as cards
tree.find(ref)       # a reference to the node it addresses
tree.open(ref)       # that node's detail, plus a card for each member it holds
```

`ContextTree` replaces `discovery.py`, `compiler.py` and `core/registry.py`.
Eight classes become one.

**A reference is a path.** `kubernetes-platform/incident-response/get_pod_logs`
— no kind prefix, no second separator. That was bought by tightening member
names to be unique across kinds rather than within them, which is a better rule
anyway: a role holding both a skill and a tool called `diagnose` was going to
confuse a reader regardless of how they were addressed. The address now reads
like something a person could have written, and every card is built by a
function that takes the reference as an argument, so a card that can be seen can
always be opened.

**`Role._compile_active` describes only itself.** A node cannot list its members
completely, so it lists none. The tree lists them, where the reference exists.

**`schema_of` is a parameter, not a port.** `ContextTree` takes a callable; the
server passes one backed by the SDK. The dependency points the same way a
`Protocol` and an adapter class would, at a fraction of the ceremony.

### The design this replaced, and why it was cut

The first draft of this ADR proposed seven concepts: `Ref`, `Cursor`,
`CapabilityGraph`, a `SchemaSource` protocol, an `SDKSchemaSource` adapter, a
`Navigator` facade, a `ToolRunner`, and a five-file package to hold them. It
also proposed adding a polymorphic `members()` to `ContextNode` in order to
avoid a single `isinstance`.

Run against this repository's own admission test — *does this help a business
developer define a capability, or help the framework run one?* — most of it was
scaffolding for an eighty-line problem. `Ref` dissolved once a reference became
a path. `Cursor` existed to guarantee that a card carries its ref, which a
function signature guarantees for free. `ToolRunner` was three lines. `members()`
would have edited five classes in `core` to remove one branch from one method in
the layer above.

`ContextTree` is the one concept that survived, which is the count this layer
should have had from the start.

## What walking a session changed

Three fixes came from tracing a real Claude Code session against the design
before building it, and none of them were visible from the type signatures.

1. **The roster moved into the server instructions.** The first
   `contexture_discover` call was returning something static that the host could
   have been told at connect time — and without it, a gateway server looks like
   it does nothing.
2. **`contexture_read` accepts a URI as well as a ref.** The demo skill says
   *"Read contexture://runbooks/crash-loop-backoff"*, because that is how the
   document names itself. Refusing that spelling would make this framework's
   addressing scheme the skill author's problem to remember.
3. **A failed lookup names what the role does hold.** A wrong ref is a routine,
   recoverable mistake, and the recovery needs to be in the error.

## Consequences

- `compiler.py`, `discovery.py` and `core/registry.py` are gone. Design 01
  §17.2's argument for a separate compiler is withdrawn there: the decision it
  described is real and is written down as the reference, not as a request
  object nobody constructed.
- The target adapters lose a `registry` parameter threaded through three call
  sites and never read.
- `ContextTree` is deliberately absent from the top-level `contexture` facade.
  That facade is what a developer *declares* with; the tree is what the
  framework *runs* with, and `tests/test_layering.py` fails if importing `core`
  pulls in a layer above it.
- `contexture_get_context` is renamed `contexture_open`. Everything in this
  layer is context; "open one capability" is the actual mental model.

## Open questions

1. **Does the generic dispatch tool degrade tool use in practice?** The suite
   proves the mechanism works. It cannot prove a model will choose to navigate.
   Measuring that needs a real host and repeated runs.
2. **A skeleton budget.** `skeleton()` currently returns every role. The
   instructions roster is capped and says when it was cut, but the tool itself
   is uncapped. A forest large enough to need one has not been observed, and
   guessing the unit — node count, rendered characters — before then would be
   guessing.
3. **Does `Resource.uri` still earn its keep?** With resources off the surface
   the URI has no protocol role; it is now a name with a scheme, kept because
   procedures are written in terms of it.
