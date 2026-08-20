# ADR 011 — Identity is the framework's; permission is not

**Status:** accepted, implemented in v0.5.0
**Date:** 2026-08-20

**Implements** [ADR 002](002-per-call-context-and-options.md) Decision B, which
has stood as *proposed* since v0.2.0. Decision A of that ADR — a per-call
context object passed into `invoke` — remains unbuilt, and this decision is
what makes it unnecessary for the one use it had a caller for.

## Context

Two holes, and it took until somebody wanted to deploy this on a network to
see that they were the same hole.

### Serving over HTTP worked, and could not be configured

`Transport` has accepted `"streamable-http"` since v0.2.0, and it works: the
SDK's runner is handed the name and serves. What it could not be handed was an
address. `run()` took `**kwargs` and passed them on, which is fine for HTTP and
silently wrong for stdio — the SDK's stdio branch is `anyio.run(self.run_stdio_async)`
and accepts no keyword arguments at all, so

```python
app.run(transport="stdio", port=9000)
```

started a server on stdio and discarded the port without a word. A passthrough
cannot hold an opinion; that is the whole of what it does wrong.

Two more gaps only appear off loopback. The SDK enables DNS rebinding
protection by itself when `host` is `127.0.0.1`, `localhost` or `::1`, and
leaves it off for everything else — so the address where it matters is exactly
the address where nothing says so. And a `**kwargs` passthrough will happily
bind `0.0.0.0` with no authentication at all, which publishes every tool the
declaration reaches to anyone who can route to the port.

### "Does the framework do authentication" is not a question

It is five questions, and they have five different answers. Sorted by the
admission test this repository already applies — *does this help a business
developer **define** a capability, or help the framework **run** one?*

| | Helps define? | Helps run? | Verdict |
| --- | --- | --- | --- |
| Issuing tokens | no | no | **not built** |
| Verifying a token | no | no | **socket, not plug** |
| Protocol wiring — `401`, RFC 9728 metadata, audience | no | **yes** | **built** |
| Carrying the caller's identity to a capability | **yes** | yes | **built** |
| Deciding what a caller may do | no | no | **the business's** |

Rows one and two share a reason worth stating plainly: **a verifier that shipped
with this package would arrive with defaults, defaults get copied into
production, and a wrong default in OAuth is a vulnerability rather than a
nuisance.** A verifier from whoever issues your tokens is better than one
written here, every time.

Row three is built for the same reason `configure_logging` is built. Under
stdio the protocol owns stdout exclusively; a business developer should not
have to know that, and a project that gets it wrong is broken in a way nothing
reports. The path of an RFC 9728 metadata document, the shape of a
`WWW-Authenticate` challenge, and the requirement that a token was minted for
*this* server rather than some other one are the same kind of fact: one correct
answer, invisible when wrong, and no business's job to know.

Row four is the one that is genuinely ours and could not be anybody else's.
Identity arrives on the wire, and `server` is the only layer allowed to touch
the wire. If the framework does not carry it inward, a business tool has
exactly one way to learn who is calling — importing the SDK — and the claim the
README opens with is gone.

### What the neighbours do

Checked at signature level rather than recalled, because the two frameworks
Contexture sits beside disagree about the part that matters.

**The official Python SDK** keeps identity off its `Context` object entirely —
`headers`, `request_id`, `protocol_version`, `client_capabilities`, `session`,
`request_state`, and no `user` or `token`. The only route is the module-level
`get_access_token()`.

**FastMCP** does the same for identity (`get_access_token()`, or a
`CurrentAccessToken()` parameter default), and adds per-component authorization
— `@mcp.tool(auth=require_scopes("write"))`, taking `(AuthContext) -> bool`,
filtering list responses and answering *not-found* on direct access.

**mcp-go** puts identity in `context.Context` and offers two server-level
hooks: `ToolFilterFunc func(ctx, *mcp.Tool) bool` before listing, and
`ToolHandlerMiddleware` around calling.

**The official TypeScript SDK** exposes `ctx.http?.authInfo` and states that it
"does not support hiding tools from unauthorized users, only refusing
execution."

Three of the four keep identity out of the call-context object; all four
converge on the same predicate shape for authorization — `(who, what) -> bool`
— and they disagree only on whether the framework ships one.

## Decision A — `ContextureOptions`

```python
app.run()                                        # stdio, unchanged
app.run(ContextureOptions(
    transport="streamable-http",
    host="0.0.0.0",
    port=8080,
    auth=Auth(verifier=OktaVerifier(), issuer=..., resource=...),
    allowed_origins=["https://acme.example"],
))
```

`ContextureApp` is identity and topology, fixed before start. `ContextureOptions`
is how to serve it. Serving one graph on a laptop and in a cluster changes the
second and none of the first.

Every field defaults to `None` rather than to its eventual value, so *not
stated* and *stated as the default* stay different things. That is the whole
mechanism behind the first of the three positions this object holds.

**It reports what a passthrough discarded.** `transport="stdio"` alongside any
HTTP-only field raises, naming every field involved.

**It refuses to publish quietly.** A non-loopback `host` requires
`allowed_hosts` or `allowed_origins`, because rebinding protection does not
turn itself on there; and it requires either `auth` or an explicitly typed
`allow_anonymous=True`, because everything the declared tools reach becomes
reachable by whoever can route to the port.

**Statelessness is a position, not a knob.** `stateless_http` is pinned `True`
and `sdk_overrides` cannot set it. ADR 001's claim is that this server keeps no
per-connection state and that a ref resolves the same way for everyone; since
the 2026-07-28 revision there is no protocol session to keep state in anyway.
Serving with sessions would make the documented design false without making
anything fail — the worst kind of wrong. `event_store` is refused for the
same reason: there is no session for it to replay into.

`sdk_overrides` is the deliberate escape hatch, deliberately named as one, and
it may not set what this object owns. Two places deciding one value means the
answer depends on which is applied last.

## Decision B — Identity, and only identity

```python
# core/principal.py — shared ground
Principal(subject=…, client_id=…, issuer=…, scopes=…, claims=…)
current_principal() -> Principal | None
```

```python
# the business's own code
class RollBackDeployment(Tool):
    async def invoke(self, namespace: str, deployment: str) -> str:
        who = current_principal()
        if who is None or "k8s.write" not in who.scopes:
            raise PermissionError(...)
```

**A context variable, not a parameter.** Identity is a property of the request,
not of any one function's signature; threading it would put an argument on
every capability that has no interest in who is calling. This is what the
Python SDK, FastMCP and mcp-go all concluded, and it is why ADR 002's Decision A
is not needed for this: a `ToolContext` would have been a new seat built for one
occupant who does not need a seat.

**`Principal` sits on the shared ground**, beside `errors` and `types`. Three
places need it and no two are neighbours: a business tool reads it, `server`
builds it, and anything later that varies an answer by caller will read it too.
Putting it in `model` would make `server` import the object model to learn who
was calling; putting it in `server` would put it above the code that reads it.
Nothing in it knows what OAuth is — five plain fields, constructible by hand in
a test.

**Two identities, never one.** `client_id` is the application that connected;
`subject` is the person it acts for. Code that conflates them writes audit
records nobody can act on.

**No raw token.** `Principal` deliberately does not carry the token string. The
specification forbids passing a client's token through to an upstream API, and
while no framework can prevent it, this one can decline to make it convenient:
a business that insists must reach past `contexture` into the SDK, which is a
visible act in a review rather than an attribute access.

**`None` is a real answer.** Over stdio nobody authenticates and nobody ever
will — the host launched the process and the operating system already decided
who that is. Inventing an "anonymous" principal to spare capabilities a branch
would answer, silently and wrongly, a question only they can answer.

**One binding site.** The identity is bound around `_invoke` and nowhere else,
because that is the one place a declaration's own code runs. Discovering and
opening do not reach it, so binding around them would widen the scope of a
global for nobody's benefit.

**The socket is Contexture's type, not the SDK's.** A business implements
`async def verify(self, token: str) -> Principal | None`. That signature is the
boundary claim applied at the one place it would have been easiest to give up.

## What is deliberately not built

Not "not yet". These are decisions:

- **No authorization server.** The SDK's `OAuthAuthorizationServerProvider` is
  not exposed. Running a login, a consent screen and a token endpoint is an
  identity provider's job.
- **No verifier implementation.** Not even a convenient JWT one.
- **No `available_to`, no `require_scopes`, no visibility filtering.** A
  framework-supplied policy vocabulary is the framework deciding what the
  business owns. FastMCP ships one; Contexture does not, and the TypeScript SDK
  agrees. **The consequence is stated rather than hidden:** a caller who cannot
  *run* a capability can still *see its card*. On a public deployment the
  capability graph is public. Closing that would need one seam through
  `core.disclosure` and a second fix for the instructions roster, which is
  computed once at startup and identical for every caller — recorded here as
  the shape the work would take, not as work owed.
- **No scope naming convention, no user/tenant/group model, no audit log** —
  but identity reaches business code, which is what makes an audit log
  *possible*.

⚠️ **`Role` is not an RBAC role.** It is a unit of capability organisation
("the Kubernetes platform"), not a permission group ("the SRE on-call
rota"). The words collide and the mistake is expensive: a tree built as a
permission model is a tree that stops being about progressive disclosure.

## Consequences

- `core` gains one module on the shared ground and still imports no `mcp`; the
  layering test is unchanged, which is the check that this was done right.
- `run()` loses `**kwargs`. **Breaking**, and the point: what it did best was
  accept arguments the SDK would then discard. `run(transport="stdio")` and
  `run()` are untouched, which is every call site in this repository, the
  scaffold and the README.
- `contexture.server.READ_TOOL` is removed. It has been a dangling export since
  v0.4.0 deleted `contexture_read` — advertised by `__all__`, raising on access.
- Serving over HTTP is covered by tests for the first time: both protocol eras
  against one running process, statelessness observed rather than configured,
  and identity followed from a verifier's return value into a capability's own
  code.
- A verifier is not reachable from the command line, by design: it is an object
  with a method, not a string. A deployment that needs one writes the few lines
  that build `ContextureOptions(auth=…)`. `contexture serve --transport
  streamable-http --host … --port …` covers everything that *is* a string.
