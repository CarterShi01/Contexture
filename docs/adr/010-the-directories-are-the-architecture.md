# ADR 010 — The directories are the architecture

**Status:** accepted, implemented in v0.4.0
**Date:** 2026-08-20

**Companion to** [ADR 009](009-the-protocol-plane-is-not-the-object-model.md),
which made the decisions. This one moves files and renames modules and changes
no behaviour: every test that passed before it passes after it, unchanged.

> `declarative.py` was deleted in v0.5.0; see
> [ADR 013](013-a-constructor-is-the-declaration.md). The directory rule this
> ADR decided is unchanged — `model/` simply holds one file fewer.

## Context

The package was flat. `core/` held eight modules of object model, `tree.py` sat
beside it as its own layer, and `server/` held five. That shape was legible at
2,300 lines and stopped being legible once `core` had to hold three genuinely
different things — what a capability *is*, where it *hangs*, and what the
server *exposes*.

Three names had also drifted from what they named:

- `projection.py` projected the tree onto the SDK. After ADR 009 the surface is
  *declared* in `core.mcp_interface` and this module binds it — the projecting
  moved, the name did not.
- `contract.py` held the entry-point descriptions *and* the sentence a failed
  lookup becomes. The first half moved out; what remains is wording.
- `registration.py` registered nothing. It emits a launch command.

## Decision

### 1. `core` is three directories and a shared base

```text
core/
├── README.md
├── errors.py  types.py  constants.py      shared ground
├── model/          node · role · skill · tool · manager
├── disclosure/     tree
└── mcp_interface/  README · tool · resource · prompt
```

`core` answers *what Contexture is*; `server` answers *how it runs*. Each
sub-directory answers a different question, and the layering table says which
may see which.

**`errors` / `types` / `constants` stay directly under `core/`.** Folding them
into `model/` would force `mcp_interface` to import `model` for an exception
class — the one dependency ADR 009 forbids it. Shared ground is what lets three
siblings stay independent of each other without three copies of an exception
hierarchy.

### 2. `tree.py` becomes `core/disclosure/`

Named for what it produces rather than for the data structure it uses. This
layer invents the two things `core.model` does not have — **the reference** and
**the level** — and progressive disclosure is what they are for. `addressing/`
was the runner-up and covers `find` but not `skeleton`, `open` or `signpost`.

### 3. `mcp_interface`, not `mcp` and not `protocol`

`mcp/` would make `import mcp` inside it read as a self-reference, in the one
directory where that import is forbidden. `protocol/` is the name ADR 003
deleted an outbound client from, and reusing it would fight the history.

### 4. Renames in `server/`

| was | is | why |
|---|---|---|
| `projection.py` | `binding.py` | it binds a declared surface to the SDK |
| `contract.py` | `messages.py` | what is left is everything said to somebody |
| `registration.py` | `launch.py` | its subject is the `Launch` it emits |

### 5. `core/__init__.py` resolves lazily

Eager re-exports would make the shared base import its own sub-layers, which is
the one dependency it may not have — and would load `disclosure` for a project
that only wanted to declare a Role. Same `__getattr__` pattern `server` already
used.

### 6. Two READMEs, because a docstring is not where somebody looks first

`core/README.md` states the split and the two load-bearing empty-ish rows of
the layering table. `core/mcp_interface/README.md` opens with the sentence that
directory most needs — *this is not where the SDK is imported* — and then gives
the three primitives by who controls them.

## The test had to be hardened first, and that came first

`test_layering.py` derived a module's layer from `path.parts[0]`. Moving `tree`
into `core/` would have made it `core`, silently merging two rules into one:
**the "core must not import tree" edge would have disappeared with nothing
failing.** That is the decay the file's own docstring warns about, arriving
through the file tree instead of through an import.

So the move was done in two steps, and the first one touches no production
code. They land in one commit with ADR 009 — the file-level changes interleave
past the point where git could tell them apart — but the order is what matters
and it was followed:

1. **Harden.** Two-level layers (`core.model`, `core.__base__`), relative
   imports resolved to absolute names before being mapped, `mcp_types` added to
   the runtime SDK check beside `mcp`, and the hard-coded `('server', 'tree',
   'examples')` tuple replaced by a set derived from `ALLOWED`. Green against
   the **old** structure, proving the harness was not what changed.
2. **Move.**

Two defects were found by writing step 1, both of which would have made step 2
look successful while checking less than before:

- The runtime SDK check tested `mcp` and not `mcp_types`. The AST check tested
  both, so only the **indirect** import path — a module that pulls the SDK in
  without naming it — was unguarded. `mcp_interface` is precisely where someone
  would reach for `ToolAnnotations`, so the gap was about to matter.
- `_imported_layers` counted relative-import levels against a module's depth.
  At depth two that arithmetic under-reports: `core/disclosure/tree.py` doing
  `from ..model.role import Role` would have recorded **nothing**.

## Consequences

- `ALLOWED` gained `core.__base__`, `core.model`, `core.disclosure`,
  `core.mcp_interface`. The two entries that carry weight are
  `"core.__base__": set()` and `"core.mcp_interface": {"core.__base__"}` — the
  second load-bearing for what it leaves out.
- `contexture.server` still exports the gateway names, forwarded to their new
  home. A pointer, not a second copy: `server` is where a caller looks for
  what is on the wire.
- Adding a sub-directory under `core/` now fails the suite until `ALLOWED`
  names it. `_children_of` reads the tree rather than a list, so the failure is
  automatic.
- `tests/test_projection.py` and `tests/test_contract.py` follow the modules
  they test: `test_binding.py`, `test_messages.py`.

## Not done here

- **`core/disclosure/` holds one file.** Splitting `tree.py`'s 570 lines into
  tree / disclosure / completion would scatter `ContextTree`'s methods across
  three modules behind a mixin or free functions. Worth doing when it grows,
  not as part of a move.
- **`inspection.py` and `cli.py` stay at the top level.** Both sit above
  `server` and belong to no layer inside `core`.
