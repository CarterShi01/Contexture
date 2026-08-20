# ADR 009 — The protocol plane is not the object model

**Status:** accepted, implemented in v0.4.0
**Date:** 2026-08-20

**Supersedes** [ADR 008](008-who-may-open-a-node.md) decision 1, which put
`opened_by` on `ContextNode`. Every other conclusion of ADR 008 stands: the
person's plane exists, its size is authored rather than derived, a reserved
node keeps its card, and `uses` stays on `Skill`.

## Context

### MCP has three primitives and the project was using one name twice

The protocol splits its primitives by **who decides when one is used**: tools
are model-controlled, resources are application-controlled, prompts are
user-controlled. `core` held a class called `Resource` that was none of those —
it was a node in the forest, disclosed to a model, reached through the gateway.

Nothing was mapped wrongly on the wire. `contexture_read` was a gateway tool,
not `resources/read`, and `core/resources.py` said so in a comment that had to
exist:

> `mime_type`, not the protocol's `mimeType`. **This payload is not a protocol
> resource descriptor** — it travels inside a tool result.

A comment and a spelling difference are what stood between two unrelated
concepts. That is a convention, not a mechanism, and conventions of this kind
are re-litigated by every reader — including the ones who wrote them.

### Two protocol fields had leaked into the object model

`Resource.uri` and `Resource.mime_type` are addresses and media types: things a
*protocol* needs. `core` is not supposed to know either, in the same way it does
not know what a separator is. The leak had a visible cost —
`ContextTree._by_uri` scanned the whole forest linearly to resolve an address
that was never the tree's to resolve.

`opened_by` was the same leak from the other direction. It let `core` know that
people exist, and it stated a rule — who may *open* a node — in a vocabulary
`core` cannot check, because `core` does not know what opening looks like on a
wire.

### The exception that was still an exception

Three of the four node kinds compiled ROUTE and ACTIVE. `Resource` did not: its
boundary was descriptor-versus-content, so the README needed a paragraph
beginning *"Resources are the exception that proves the rule"*. ADR 004 states
there are two levels and no third; one node kind was answering a different
question entirely.

### What a Resource actually was

Read the definition and it describes a tool:

> A tool computes an answer from the arguments it is handed; a resource takes
> none, and two reads return the same bytes.

A read-only tool that takes no arguments. Everything else `Resource` carried —
the URI, the media type, the separate gateway entry point — was protocol
apparatus stored on a node.

## Decision

### 1. `core.Resource` is deleted; content is an ordinary read-only Tool

```python
class CrashLoopRunbook(Tool):
    """How to diagnose a container that keeps restarting."""

    name = "crash_loop_runbook"
    read_only = True

    async def invoke(self) -> str:
        return RUNBOOK
```

`core.model` now holds three kinds, and all three compile ROUTE and ACTIVE.
**ADR 004's "two levels and no third" has no exception left.**

### 2. The three primitives are declared in `core/mcp_interface`

One module per primitive, so the answer to *what does this server expose?* is a
directory listing:

```text
mcp_interface/tool.py       the four gateway entry points
mcp_interface/resource.py   Resource — content published at a URI
mcp_interface/prompt.py     Prompt — a node a person triggers by name
```

Both `Resource` and `Prompt` hold `opens`: a **reference string** naming a node
the tree still holds. The string is the guarantee, exactly as in `Skill.uses` —
a `str` cannot be walked into, so this plane cannot reach into the forest and
the forest cannot reach back. One capability gets two addresses; it never gets
two declarations.

The name `Resource` is reused deliberately. With the object-model class gone it
means one thing in this repository: the MCP primitive. **The two planes are
told apart by position, not by renaming**, and `core/mcp_interface/README.md`
is where that position is explained.

### 3. `core.mcp_interface` does not import `core.model`, or the SDK

The load-bearing entry in the layering table is what it omits:

```python
"core.mcp_interface": {"core.__base__"}     # no core.model
```

It does not import `mcp` either. Declaring what a primitive carries and putting
it on a wire are two jobs, and only the second belongs to `server`.

### 4. `opened_by` and `Opener` are deleted; `Prompt.model_may_open` replaces them

The guardrail is unchanged in behaviour: a node reserved for a person is
refused to a model, the refusal names the prompt that reaches it, and the card
stays in `open(role)` so the model can point at it.

What changes is where it is stated. `server` already knew which door a call
came through — that is what `wrong_door` rests on — so it enforces this too,
from a set computed at registration. **`core.model` no longer knows that people
exist.**

A card no longer carries an `opened_by` field. It was the object model
reporting a fact about a plane it should not be able to see.

### 5. The gateway is four tools; `contexture_read` is gone

Content is run like any other read-only tool:

```text
contexture_discover              the root roles, one level
contexture_open                  one node's detail, plus its members' cards
contexture_invoke_read_only      run a tool that leaves the world unchanged
contexture_invoke                run a tool that does not
```

### 6. The resource primitive is implemented, for the first time

`resources/list` and `resources/read` are served from the declared surface. A
host reads a URI; the server resolves `opens` and runs that node. Publishing is
checked when the server is built: the ref must resolve, the node must be a
read-only tool, and it must take no arguments — because a host reads with none.

### 7. URI addressing leaves the tree

`ContextTree.resource()`, `_by_uri()` and `LookupFailure.NO_SUCH_URI` are gone.
A URI is an address in the protocol's scheme, resolved by the host's own read.

A procedure that wants to name something outside its own parent uses `uses`,
which ADR 008 introduced one version earlier. The timing is a coincidence; the
succession is not.

## Consequences

- `core/model` holds three kinds. The README's *"exception that proves the
  rule"* paragraph is deleted rather than reworded.
- A `Role` no longer has a `resources` list; `members()` walks three lists.
- **Breaking.** `contexture.Resource` and `contexture.Opener` are gone from the
  public facade, `contexture_read` is gone from the wire, and a declaration
  using either must be updated. The scaffold and the bundled example show the
  new shape.
- `docs/verification/hosts.md` records three runs that used `contexture_read`
  and URI addressing through the gateway. Those runs are kept as recorded, per
  that file's own convention, and a note at the top says which model they
  describe.
- Server memory is unchanged; the linear `_by_uri` scan is gone.

## Not done here

- **The directory reorganisation.** ADR 010 covers it, and is deliberately a
  separate change: it moves files and renames modules without altering a single
  semantic, so it can be reviewed file by file.
- **No prompt is declared anywhere in this repository.** The demo has no
  operation where going wrong is expensive enough to justify one, and the
  criterion from ADR 008 decision 3 is worth more than an illustration. The
  machinery is covered by tests; the example teaches the rule instead.
- **Codex is still unverified**, and whether it renders prompts or services
  `completion/complete` is still unknown. This ADR does not need that answer:
  what it moves is where things are declared, not whether a host displays them.
