# ADR 012 — Registration is where a declaration becomes a capability

**Status:** accepted, implemented in v0.5.0
**Date:** 2026-08-20

**Discharges:** [ADR 002](002-per-call-context-and-options.md) Decision A, which
parked `ToolContext` until a real requirement arrived. The requirement arrived —
a capability that reaches a remote gateway — and it turned out not to need a
per-call object at all.
**Confirms:** [ADR 003](003-remove-the-outbound-half.md). Nothing removed there
comes back.

## Context

### The demand

A role's instructions describe a workflow, and some of its steps are not this
application's capabilities: they belong to a Lark server, a Notion server, a
browser driver, and in the deployment this framework was written for they sit
behind one gateway that has already narrowed them per profile and injected
their credentials.

The obvious reading is that Contexture needs a way to *call out*. It does not.
`model/skill.py` settles it — *a Skill is executed by the model and returns
nothing* — so a Role never calls anything; the model does. The framework
question is not how a role reaches outside the process but **how a role's text
may legitimately name something outside itself**, and wrapping answers that
completely: a wrapped remote capability is an ordinary `Tool` with a real
address, a derived schema, and a description written by whoever knows when to
use it. `Tool.invoke` is arbitrary async Python and needs no new node type.

Note what a 1:1 mirror of an upstream catalogue would have been: not a wrapping
at all. The upstream's own names and descriptions would flow through untouched
and the disclosure text — the whole of what this project produces — would not
participate. **The wrapping is the product.**

### What was actually missing

`invoke` needs a live connection, and a connection is built at *run* time while
the object graph is built at *import* time. `declarative.collect` runs in
`__init_subclass__`, `declaration` is a `ClassVar`, and one Tool instance
served every call in the process. A Tool could not hold a session.

And the moment that hole is named it is obviously not about gateways. A
database pool, an HTTP client, a tracer and a cache have the identical shape:
**built once before serving, shared by every call, disposed once after**. This
is a lifecycle-scoped resource, and there should be exactly one mechanism for
all of them.

### Three questions with three different homes

Registration did not exist, so three questions about a *running* application
were answered in three places at three times:

| Question | Where it was answered |
| --- | --- |
| which capabilities does this server offer | `ContextureApp(roots=...)` |
| where does each one hang | recomputed by every walker that needed it |
| what may one reach outside the process | nowhere |

### brpc answers all three in `main()`, and we could not

The split this framework already borrowed from brpc — framework-filled
parameters beside business ones — comes with an ownership model:
`brpc::Channel` is a process-level handle, initialised once and shared by every
thread, held by the service implementation; `brpc::Controller` is per-call.
Crucially **the Channel is not fetched from the request**: a handler uses
`this->channel_`.

We could not do that because a brpc service implementation is constructed by
the application in `main()`, while a Contexture node is constructed by the
import system as a side effect of reading a class body — three phases earlier
than any application code runs. That is the cost of using the class body as the
authoring surface, and it is the whole of what this ADR pays down.

Also worth recording, because it changes the shape of the answer:
**`Channel::Init` does not open a connection.** It resolves the naming service
and prepares a load balancer; sockets are created on demand. A Channel is a
*handle*, which is exactly what can be built synchronously and handed out early.

### Measured against the installed SDK

`mcp 2.0.0`, probed rather than reasoned about, because the shape of the answer
depended on it.

| # | Question | Result |
| --- | --- | --- |
| 1 | Does the SDK recognise a `Context` **subclass**? | Yes — resolved via `typing.get_type_hints`, not by matching annotation text |
| 2 | Can a *static* resource handler take a `Context`? | **No.** The SDK raises: *"Context injection for static resources is not supported"* |
| 3 | What does `FunctionResource.read()` call? | `fn()` — no arguments, no context, ever |
| 4 | Does a URI *template* variable buy injection? | Yes, but the address would have to grow a variable it does not want |
| 5 | Does `server.call_tool()` carry a request context? | No, and the lifespan is never entered |

Facts 2 and 3 are decisive. A hand-off that travels with the request reaches a
tool call and **cannot** reach a resource read, and since ADR 009 a published
document *is* a read-only tool — so the same node would have a connection at one
door and none at the other. Fact 5 rules out sourcing anything from
`request_context.lifespan_context`: it would make every capability that used one
untestable in process.

## Decisions

### 1. A registry owns registration, and the handle comes first

`ControllerManager` takes the channels, and then takes controllers:

```python
channels = OCChannels(gateway=connect("https://gateway.internal"))
manager = ControllerManager(channels=channels)
manager.register(OneCreator)
app = ContextureApp(roots=manager, publish=PUBLISHED)
```

It accepts a class as readily as an instance, and builds the class here. That
is not a convenience: it makes registration the moment a controller comes into
existence with everything it needs, which is what `main()`'s order assumes.

**Controller** against MVC deliberately: the model is the declaration, the view
is `disclosure` compiling a node for an agent, and this is the C both of them
had been doing without a home.

### 2. A node is told its address; it still cannot work one out

Registration stamps `path` — **a tuple of segments, never a joined string**.
Position belongs to the model; which character spells a separator stays in
`disclosure`, and a test pins the boundary so it cannot drift down a layer.

This also removes the last caller ADR 002's Decision A had. The two things a
shared instance could not know about itself — where it hangs and what it may
reach — now arrive the same way, so neither needs a per-call parameter.

### 3. The handle is stamped, not carried

`ContextNode.channels` is `Any`, because the framework must never learn what is
in it, and stamped at registration rather than passed to `__init__`, because a
declared member is built by the declaration machinery and the application never
gets to call its constructor.

Stamping is what makes the two doors agree. A tool call and a resource read
reach a capability through different SDK machinery; a hand-off that travelled
with the request would serve one and not the other, and fact 2 says no argument
would make the second one work. Both are checked over real stdio.

The cost is stated rather than hidden: **every controller sees the whole
handle**, where brpc narrows visibility by having each service hold only the
channels it was given. Narrowing would need the application to construct nodes,
which is the thing the declaration exists to remove. Revisit it when a
deployment genuinely needs one branch unable to see another's connections.

### 4. Members are materialised per owning instance

A declared member used to be built once, when the class body was read, and
shared by every instance of the declaring class. That was invisible while
nothing was ever written onto a node, and stopped being invisible the moment a
registry started writing an address and a handle onto one: two servers in one
process would each find their capabilities pointing at the other's.

So `DeclaredMember.build()` makes a fresh member per owner. A member declared
as an *object* is still that object — an author who wrote out an instance with
constructor arguments meant that one, and it cannot be rebuilt from nothing.

Copies are cheap: a 300-role forest with distinct strings is 184 KB resident.

### 5. The tree reads the registry instead of walking it

`ContextTree` walked the forest four times before it could answer anything —
once to refuse a cycle, once to refuse a name holding a separator, once for
`uses`, and once more on every `find`. Registration already walks it, so three
of those become reads and `find` becomes a dictionary lookup.

What moved rather than vanished: the cycle check and the root-name check are
registration's, because they are about the graph. The separator check stays in
`disclosure`, because it is about how an address is spelled.

Registration is also the first place in this package that sees the whole graph,
so it refuses what `_reject_cycles` passed in silence: **the same object held at
two addresses**, the DAG [ADR 008](008-who-may-open-a-node.md) recorded as
failing quietly.

### 6. A handle that must be opened is opened by the lifespan, and closed by it

`channels` covers a handle that can simply be constructed — which is most of
them, because the shape worth copying is `Channel::Init`: cheap, synchronous,
connections dialled on demand. `provision` covers the rest: a pool that must be
awaited into existence, a session that shakes hands, anything that has to be
closed again.

It is a **factory** returning an async context manager, never a context manager
itself, because one is consumed by being entered — a server run twice would
meet an `AttributeError` raised from inside `contextlib`, a long way from the
line that caused it. That mistake is refused at construction, where it was
written.

The framework enters exactly one. Composing several belongs to the application,
in its own factory, where `async with a, b` already unwinds in the right order
and runs every teardown even when one raises. A framework-side exit stack would
buy the same property one layer further from the code that knows what it holds.

Probed rather than assumed, because the whole shape depends on it:

| Question | Result |
| --- | --- |
| Is `MCPServer(lifespan=...)` entered and exited over **stdio**? | Yes — `start, enter, call, exit` |
| Over **streamable-HTTP**? | Yes — `start, enter, … exit` on shutdown |
| Does a failure while opening stop the server? | Yes, before it serves; the reason reaches stderr |
| Is a context-manager instance re-enterable? | No — `AttributeError` from `contextlib` |

`build_server()` stays synchronous, which is a constraint rather than an
accident: tests build a server and call into it with no transport and no
session. So the lifecycle wraps *serving*, never *construction*.

What the lifespan yields reaches the SDK as `request_context.lifespan_context`
and nothing here reads it back. The opened handle is **stamped onto every
controller** instead, for the reason decision 3 gives: half the doors into a
capability carry no request context at all.

On the way out the handle is cleared. A call arriving after shutdown then sees
`None`, which fails legibly, rather than a session somebody already closed,
which fails somewhere inside a client library.

### 7. What is deliberately not built

- **No DI container, registry of providers, or wiring graph.** There is one
  level: the application builds the handle, controllers consume it. No ordering
  to resolve.
- **No `ToolContext.deps`.** It would be a second way to reach the same object,
  and one of the two would not work at a resource read.
- **No per-slot fields** (`ContextureApp(gateway=..., db=...)`). That is exactly
  what does not generalise; a third dependency is a field on a business
  dataclass, not a change here.
- **No dict.** Stringly typed, uncompletable, unchecked.

## Consequences

- `core/model/manager.py` is new. `core/model/node.py` gains two stamped
  fields, neither compared: two nodes are the same node by what they declare,
  not by where they hang.
- `ContextureApp` accepts a manager, or `channels` for an application that
  never wanted to hold one, and refuses both at once — two answers to what a
  capability reaches is one answer too many.
- `contexture list`, `inspection` and every existing test keep passing bare
  roots; the tree builds a private registry for them. An empty registry does not
  overwrite a handle a full one stamped, which is what makes the two doors safe.
- 291 tests pass, including a subprocess fixture whose tool call and resource
  read both reach the object its `main()` built.

## Not done here

- **Configuration-driven registration.** `[tool.contexture]` already resolves
  roots by reflection; pushing that to individual controllers should only ever
  **subtract**. A configuration that could add a member would be a second source
  of truth for what a role holds, and the two would drift.
- **No narrowing of what a controller can see**, per decision 3.
