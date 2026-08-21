# Contexture Handbook

This is the user path for a Contexture application. Start here; read the ADRs
only when you need to understand framework internals.

## 1. Build Hello World

```bash
uv tool install contexture-mcp
contexture new hello-context
cd hello-context
uv sync
uv run contexture check
uv run contexture call hello-context-assistant/ping --input '{"target":"example.test"}'
```

The generated package exports one `app`. Its Role owns a Skill and a Tool:
Role says who is responsible, Skill tells an agent how to work, and Tool is
typed code Contexture runs. Edit `tools.py`, repeat `call`, and see the result
without configuring an MCP host.

## 2. Connect an agent

```bash
uv run contexture serve
claude mcp add --scope project hello-context -- uv run contexture serve
codex mcp add hello-context -- uv run contexture serve
```

The host and local runner consume the same `app`; there is no separate server
configuration to keep in sync.

## 3. Model a real domain

Keep work that belongs to one responsibility in one Role. Add child Roles only
when an agent must choose among distinct responsibility boundaries. Put a
procedure in a Skill and point its `uses` at the Tools it needs; put deterministic
work and its typed arguments in a Tool. Use `contexture list` for refs and
`contexture inspect REF` to see exactly what an agent receives.

## 4. Connect external systems

When Tools need a database, HTTP client, or cluster, add a `Channels` subclass
to the same app. Its constructor records cheap configuration; `open()` obtains
connections; `close()` releases them. `check` does not open Channels. `call`
and `serve` use their production lifecycle.

```python
app = Contexture(name="operations", roots=(Operations,), channels=OperationsChannels)
```

## 5. Publish entrances

Use Prompt for a person-triggered entrance and Resource for a host-readable
URI. Neither duplicates a capability: each points at an existing node, and both
are declared in `Contexture(..., prompts=..., resources=...)`.

## 6. Test and debug

- `check` compiles and validates without connections.
- `list` prints the names and refs the application contains.
- `inspect` replays progressive disclosure.
- `call REF --input JSON` invokes a read-only Tool locally.

Writing Tools require `--allow-write`; this prevents an accidental local debug
command from changing an external system. Diagnostics go to stderr, so Tool
results on stdout remain scriptable.

## 7. Deploy

Start with stdio. For Streamable HTTP, use the same declaration:

```bash
uv run contexture serve --transport streamable-http --port 8080
```

For public addresses, explicitly set host-origin and authentication policy with
`ContextureOptions`; those choices are deployment policy, not fields in a Tool.

## 8. Embed

An existing process can host the same app with a short entry point:

```python
from my_context import app
from contexture.server import ContextureOptions, serve

serve(app, ContextureOptions(transport="stdio"))
```

If you already have an event loop, use `build_server(app)` and await its async
start method. Do not separately construct Manager and Index for ordinary
applications.

## 9. Internals

The runtime compiles `Contexture → ControllerManager → Index → Disclosure →
ContextureServer`. `ControllerManager` owns constructed nodes and Channels,
`Index` owns compiled addresses and Tool bindings, and `Disclosure` decides
what an agent sees at each navigation step. These are framework internals;
their detailed decisions live in [ADR](adr/).
