# ADR 002 — A per-call context object, and options instead of `**kwargs`

**Status:** Decision B accepted and implemented in v0.5.0, as
[ADR 011](011-identity-is-the-frameworks-permission-is-not.md). Decision A
remains proposed — its premise was removed by the gateway, and ADR 011 removed
the one use it had a caller for; see the revision note below before
implementing any of it
**Date:** 2026-08-19
**Revised:** 2026-08-19, after [ADR 006](006-errors-carry-facts-and-the-contract-is-one-module.md)

## Context

Two holes, and they are the same hole seen from two sides: the boundary between
what a business declaration states and what the SDK happens to accept is not
drawn anywhere.

**A tool has no side channel.** `projection` hands `tool.invoke` straight to
`server.add_tool`, so the SDK derives the input schema from that signature. Every
parameter is therefore a model-filled argument, and there is nowhere to put the
things MCP offers per call — progress, logging, elicitation, reading the server's
own resources. Adding one means adding it to the schema, which is precisely the
mistake `read_only` exists to avoid: a framework concern the model can fill in is
not a framework concern any more.

**Options leak the SDK.** `ContextureApp.run(transport, **kwargs: object)`
forwards whatever it is given. The SDK's `run()` surface is what a user must
learn, an SDK rename breaks business code, and wrong combinations fail silently —
the stdio branch is `anyio.run(self.run_stdio_async)`, which accepts no kwargs at
all, so `app.run("stdio", port=9000)` is a typo the program never mentions.

brpc answered the first one in 2014 and has not changed the answer since. Its
generated service method is

```c++
void Echo(google::protobuf::RpcController* cntl_base,
          const EchoRequest* request, EchoResponse* response,
          google::protobuf::Closure* done);
```

Business parameters (`request`, `response`) and framework parameters
(`cntl_base`, `done`) are physically separated in the signature, and everything
per-call that accumulated over a decade — timeouts, retries, backup requests,
attachments, tracing, compression, authentication — went onto the Controller
instead of onto the signature. The signature never grew.

The second, brpc answers with `ServerOptions`: a plain struct of defaults, passed
to `Start(addr, &options)`, distinct from both the server's identity and its
topology.

## Decision A — `ToolContext`

> **Revision note, 2026-08-19.** Everything below was written while business
> tools were registered natively — `projection` handed `tool.invoke` to
> `server.add_tool`, and the SDK owned dispatch. Behind the five-tool gateway
> neither is true, and three of this decision's load-bearing claims changed.
> Measured against the installed SDK rather than reasoned from its API:
>
> **The side channel already exists.** A business tool that annotates the SDK's
> `Context` gets it today, over real stdio, with `ctx.info()` reaching the host
> and `ctx.request_id` populated — and the SDK keeps the parameter out of the
> derived schema on its own. The hole this ADR opens with is closed.
>
> **A custom abstract type cannot be annotated.** Give `SDKTool.from_function` a
> parameter annotated with a type the SDK does not recognise and it tries to put
> it in the schema: `PydanticInvalidForJsonSchema`. So the `core`-abstract half
> of the split below cannot work without the trampoline.
>
> **But the trampoline is no longer needed, and the reason it was rejected no
> longer holds.** "Mechanism" rules out subclassing the SDK's `Context` because
> `MCPServer._handle_call_tool` constructs its own and injects that, making the
> annotation a lie. Under the gateway that method never sees a business tool.
> `Dispatch.run(tool, arguments, context)` runs it, Contexture chooses what
> `context` is, and the SDK passes it through unchecked
> (`pass_directly[self.context_kwarg] = context`). A `ToolContext(Context)`
> living in `server/` is therefore annotatable, is stripped from the schema for
> free, and can carry `ref` and `declared_in`. Prototyped; it works.
>
> **What is left of this decision is one line of import.** Not a dependency:
> a served project already has the SDK through `contexture-mcp`. What the split
> buys is that business code names `contexture.server` rather than
> `mcp.server.mcpserver`, so an SDK rename lands in one place. That is worth
> something — the SDK has already moved this module once and kept no alias —
> but it protects code that does not exist: no tool in the examples, the
> scaffold, or the tests takes a `ctx`, and none is waiting to.
>
> **And waiting is free.** A tool annotating the SDK's `Context` keeps working
> if Contexture later passes a `ToolContext` subclass, because a subclass is
> still a `Context` and nothing type-checks the injected object. The timing
> argument this ADR rests on — that the position must exist before people write
> tools, or every signature changes — is mechanically false.
>
> So: **do not implement the two-type split or the trampoline.** When a tool
> actually wants progress or elicitation, add `ToolContext(Context)` to
> `server/`, build it in `_invoke` where the ref is already in hand, and export
> it from `contexture.server` — which the examples are already allowed to
> import. Roughly forty lines, and the shape will be answerable from a real
> requirement instead of a guess.
>
> One consequence has been taken already, because it had a victim without any
> of this: `Tool._compile_active` used to publish `parameters()`, read straight
> off the signature, so a tool taking a `ctx` disclosed an argument its own
> schema rejected. Opening a tool now answers with the same `input_schema` its
> card carries. `ToolDisclosureTests` holds it.


### The abstract base lives in `core`, the implementation in `server`

brpc's split is worth copying exactly. The signature names
`google::protobuf::RpcController` — an abstract type from the IDL layer, which
knows nothing about sockets — and the framework passes a `brpc::Controller`.
The user casts down when they need the real thing.

So:

- `contexture.core.context_object.ToolContext` — an abstract class with no
  dependencies, exported from `contexture`. This is what business code annotates.
- `contexture.server.runtime.MCPToolContext(ToolContext)` — the implementation,
  wrapping the SDK's `mcp.server.mcpserver.Context`.

`core` stays free of `mcp`, so `tests/test_layering.py` needs no new exception.

### What a tool looks like

```python
from contexture import Tool, ToolContext

class GetPodLogs(Tool):
    """Return recent container logs for one Pod."""

    name = "get_pod_logs"
    read_only = True

    async def invoke(
        self,
        ctx: ToolContext,
        namespace: str,
        pod: str,
        previous: bool = False,
    ) -> str:
        await ctx.progress(1, 2, "reading logs")
        return await kubernetes.logs(namespace, pod, previous=previous)
```

`ctx` is **optional** and found by annotation, not by name — a tool that does not
want it keeps the signature it has today. Every tool in
`src/contexture/examples/incident/` keeps working unchanged, which is the
migration story.

`ctx` never appears in the input schema. It is the same rule as `read_only`,
applied to a wider class of thing: **the model fills business arguments; the
framework fills framework arguments; the two are separated in the signature so
the separation cannot be forgotten.**

### The surface

| `ToolContext` | wraps | why it is on the surface |
| --- | --- | --- |
| `await ctx.progress(done, total=None, message=None)` | `report_progress` | long tool calls otherwise look hung |
| `await ctx.info / warning / error(msg)` | `Context.info / warning / error` | log lines the *host* shows, distinct from `logging` to stderr |
| `await ctx.ask(message, schema)` | `elicit` | a context framework that cannot ask the human is missing a direction |
| `await ctx.read(uri)` | `read_resource` | a tool consulting a declared resource shouldn't re-implement its reader |
| `ctx.request_id` | `request_id` | correlating logs to one call |
| `ctx.ref` | — | Contexture's own: which node is executing |
| `ctx.declared_in` | — | Contexture's own: the role paths that declare this tool |
| `ctx.raw` | the SDK `Context` | the documented escape hatch |

Deliberately **not** on the surface: `session`, `headers`, `mcp_server`,
`notify_*`, `close_sse_stream`. These are wire-level; exposing them puts protocol
mechanics into business code, which is the thing the whole package is arranged to
prevent. `ctx.raw` is there so that need does not become a fork — brpc makes the
same concession, and makes it visible, with `static_cast<brpc::Controller*>`.

### `ctx.ref` and its honest limit

This is the part a Controller can do that nothing else in the design can: carry
framework knowledge into the handler. In an RPC framework that cargo is the call;
here it is **position in the capability graph**.

But it must be exactly as much as the server actually knows, and no more:

- `ctx.ref` is the tool's own ref, e.g. `tool:k8s-troubleshooter#get_pod_logs`.
- `ctx.declared_in` is the tuple of role paths declaring it — a tool shared by two
  roles has two, and neither is "the one the agent came through".

There is deliberately **no** `ctx.came_from_skill`, `ctx.disclosed`, or
`ctx.current_role`. ADR 001 rests on the server keeping no per-connection state
and on `get_context` being a pure function of its ref; a context object that
reported which skill the agent had opened would be that state, smuggled in
through a side door. The server does not know, and must not appear to.

### Mechanism: a trampoline in `projection`

The two obvious routes are both closed, and it is worth recording why so nobody
reopens them:

- **Let the user annotate the SDK's `Context`.** That puts `import mcp` in
  business code. The layering exists to prevent this.
- **Make `ToolContext` a subclass of the SDK's `Context`.** `find_context_parameter`
  would then find it (it tests `issubclass(annotation, Context)`), but
  `MCPServer._handle_call_tool` constructs `Context(...)` itself and injects
  *that*. The user's annotation would be a lie and none of `ToolContext`'s methods
  would exist on the object they received.
  **No longer true behind the gateway** — see the revision note. That method
  never runs a business tool now, and the object it would have constructed is
  one Contexture passes itself. This is the route to take if the decision is
  ever taken.

So `projection` — already the only module that knows what MCP looks like, and
already declared to hold no business rules — builds the adapter:

```python
_CTX_PARAM = "_contexture_ctx"

def _adapt(tool: Tool, ref: str, roles: tuple[str, ...]) -> Callable[..., Any]:
    """Wrap `tool.invoke` in the signature the SDK should see."""

    ctx_name = _context_parameter(tool)        # the ToolContext param, or None
    signature = _business_signature(tool)      # invoke's params, minus self and ctx

    async def call(**arguments: Any) -> Any:
        if ctx_name is None:
            return await tool.invoke(**arguments)
        raw = arguments.pop(_CTX_PARAM)
        bound = MCPToolContext(raw=raw, ref=ref, declared_in=roles)
        return await tool.invoke(**{ctx_name: bound, **arguments})

    if ctx_name is not None:
        signature = _with_sdk_context(signature, _CTX_PARAM)
    call.__signature__ = signature
    call.__annotations__ = _annotations(tool, ctx_name, _CTX_PARAM)
    return call
```

Three SDK facts this rests on, all read out of `mcp` 2.x source rather than
assumed:

1. `func_metadata` builds the argument model from
   `inspect.signature(func, eval_str=True)`, which returns `__signature__` when
   one is set.
2. `find_context_parameter` reads `typing.get_type_hints(fn)`, i.e.
   `__annotations__` — so the SDK `Context` annotation must be set there too, as a
   real class object, and `__signature__` alone is not enough.
3. `Tool.from_function` puts the detected context parameter into `skip_names`, so
   it is excluded from the schema by the SDK's own path — Contexture does not have
   to filter anything.

All three were verified against a local reproduction before this was written: a
synthesized signature is picked up, `get_type_hints` sees the injected
annotation, the context parameter is the one dropped, and the return annotation
survives — which matters, because `structured_output` auto-detects from it and
that is what makes the incident demo's `PodStatus` dataclass project as a
structured result.

Pick `_CTX_PARAM` to be a name no business tool would use, and reject a tool that
does use it at projection time, with a message naming the tool.

**Fallback, if signature synthesis proves brittle across SDK versions:**
`Tool.from_function(fn, name=..., context_kwarg=_CTX_PARAM)` accepts the context
parameter name *explicitly* and skips detection entirely, and the resulting
`Tool` objects can be handed to `MCPServer(tools=[...])` at construction. It is a
different construction path than `add_tool`, so it is the second choice, not the
first — but it is public API and it removes fact 2 from the list above.

### Testing without a transport

The abstract base pays for itself here. `contexture.testing.RecordingToolContext`
implements `ToolContext` over nothing: it records progress calls and log lines,
returns scripted answers from `ask`, and serves `read` out of a dict.

```python
ctx = RecordingToolContext(ref="tool:demo#get_pod_logs")
assert await GetPodLogs().invoke(ctx, namespace="prod", pod="payments-api-7d9c")
assert ctx.progress_reports == [(1, 2, "reading logs")]
```

`app.py`'s docstring already claims the domain model stays testable without a
transport. Today that is true only because tools have no framework surface at
all; this is what keeps it true once they do.

## Decision B — `ContextureOptions`

```python
@dataclass(slots=True, frozen=True, kw_only=True)
class ContextureOptions:
    """How to serve a graph. Not what to serve, and not what it is called."""

    transport: Transport = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000
    path: str = "/mcp"
    log_level: LogLevel = "INFO"
    max_request_body_size: int = DEFAULT_MAX_REQUEST_BODY_SIZE
    sdk_overrides: Mapping[str, Any] = field(default_factory=dict)
```

```python
app.run()                                                    # unchanged
app.run(ContextureOptions(transport="streamable-http", port=9000))
```

The split mirrors brpc: `ContextureApp(roots=, name=, version=, instructions=)`
is identity and topology, fixed before start and frozen after — `AddService`, and
"services cannot be added after startup". `ContextureOptions` is runtime — the
`ServerOptions` passed to `Start`.

Three things this does that `**kwargs` cannot.

**It validates combinations.** `transport="stdio"` with a `port` is a mistake
today that nothing reports, because the SDK's stdio branch takes no kwargs.
Options raises, naming both fields.

**It holds an opinion the SDK does not.** `stateless_http` is not a tuning knob
for this framework. ADR 001's central claim is that the server keeps no
per-connection state and that `get_context` is a pure function of its ref;
serving with sessions would make the documented design false without making
anything fail. So it is not a field — it is pinned `True`, and an attempt to set
it `False` through `sdk_overrides` raises with that sentence as the reason. This
is the whole value of an options object over a passthrough: a passthrough cannot
disagree with its caller.

**It defaults `host` to loopback.** A context server's tools are the interesting
half of a machine. Binding wider should be a thing someone typed.

`sdk_overrides` is the deliberate escape hatch, and it is deliberately *named* as
one, so the coupling shows up in the code that takes it rather than hiding inside
`**kwargs`. Same reasoning as `ctx.raw`, and same reasoning as brpc making you
write the `static_cast` yourself.

### A latent bug this closes

Found while working out where names collide. `ToolManager.add_tool` on a
duplicate name **warns and returns the existing tool** rather than raising:

```python
existing = self._tools.get(tool.name)
if existing:
    if self.warn_on_duplicate_tools:
        logger.warning(f"Tool already exists: {tool.name}")
    return existing
```

`_register_framework_tools` runs before `_register_tools`, and `_register_tools`
only compares business tools against each other. So a business tool named
`contexture_discover` passes Contexture's own duplicate check, is silently
dropped by the SDK, and **`Projection.business_tools` still lists it** — the
projection report, whose stated purpose is "what was projected, so a caller can
assert on it", reports a tool that is not there.

Fix belongs with this work: reserve the `contexture_` prefix in `_register_tools`
and raise `DuplicateNameError` with the reason. brpc reserves its built-in
service paths for exactly this reason; a framework that ships endpoints owes the
user a namespace they cannot walk into by accident.

## Consequences

- `core` gains one public abstract class and still imports no `mcp`. The layering
  test is unchanged, which is the check that this was done right.
- `projection` gains the most intricate code in the package. It is the place an
  SDK upgrade will bite, so it needs a test that asserts the **generated input
  schema does not contain the context parameter** — not a test that the tool
  runs, which would pass while leaking.
- Business tools gain progress, host-visible logging, and elicitation without
  learning MCP; the signature that carries them is stated in Contexture's
  vocabulary, so the SDK can rename `Context` without touching a declaration.
- One more surface to keep in sync as the SDK's `Context` grows. That cost is
  real and is the price of not exposing `mcp` types; `ctx.raw` keeps it from
  being a blocker.
- `run()`'s signature changes. `**kwargs` was never documented as supported, and
  no example in the repository uses it.

## Not done here

- **Disclosure telemetry** — which refs get discovered, which skills are actually
  opened, how often a tool is called without its skill ever being read. That
  number is the only evidence that progressive disclosure works, and `ToolContext`
  is where it gets injected, which is why it comes after this and not before.
- **An `Extension<T>`-style registry** for target adapters. `BUILTIN_ADAPTERS` is
  a hard-coded tuple; `targets` is a side road, so this waits for a real second
  user.
- **`Resource.read` context.** Symmetric and probably wanted, but the SDK path
  is `FunctionResource.from_function`, not `add_tool`, so it has to be checked
  before it is designed.
