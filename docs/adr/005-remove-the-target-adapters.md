# ADR 005 — Remove the target adapters

**Status:** accepted, implemented in v0.2.0
**Date:** 2026-08-19

## Context

ADR 001 turned the main arrow around. Before it, the primary route to an agent
was *declare → compile → emit CLAUDE.md / AGENTS.md / SKILL.md → the agent reads
the files*. After it, the primary route was *declare → one native MCP server →
the agent connects*. `contexture.targets` — the layer that rendered the files —
was not removed. It was demoted to a side road and kept "for runtimes that
cannot connect".

ADR 003 removed the outbound half on the reasoning that a half-made decision
produces visible symptoms. The same reasoning applies here, and the symptoms
were measured rather than guessed.

**Nothing in the framework calls it.** Grepping `src` for `contexture.targets`
returns the facade's own layer diagram and one sentence in
`server/registration.py` that exists only to contrast with it. No module on the
path from a declaration to the wire imports the layer.

**There is no way to reach it without writing Python.** The CLI is `new`,
`list`, `serve`, `demo`. There is no `contexture render`. The scaffold does not
mention the layer. A user's only route to it is importing `render_all` by hand,
having first learned it exists from one paragraph of the README — which is not
a route anyone takes.

**It was the reason a public error existed.** `TargetRenderError` was exported
from the top-level `contexture` facade, so the object model's error hierarchy
carried a member that only a dead road could raise.

**It was one of the two reasons the package could write files.** The IO
boundary test named two exemptions: `targets/writer.py` and `cli.py`.

Measured: seven files, 740 lines, ten classes — thirty per cent of the classes
in the framework — plus 244 lines of tests, all of it reachable by nobody.

The honest counter-argument is that `targets` was the only answer Contexture had
to "what about a runtime that cannot speak MCP?" That answer stopped being real
the moment it had no entry point. A capability nobody can invoke is not a
capability that is being kept; it is one that is being paid for.

## Decision

`contexture.targets` is deleted, not relocated and not deprecated.

Gone: `TargetAdapter`, `TargetCapabilities`, `Artifact`, `ArtifactSet`,
`ClaudeCodeAdapter`, `CodexAdapter`, `CursorAdapter`, the markdown helpers, and
`writer.py` with `WritePlan` / `PlannedChange` / `Change`. With them go
`TargetRenderError` and `tests/test_targets.py`.

If per-runtime rendering is ever wanted again, it comes back as a command with
a user-facing entry point — `contexture render <target>` — built on the
smaller package this leaves behind, not as a library API nobody can find.

## Consequences

- The framework drops from 25 source files to 18, from 3170 lines to 2321, and
  from 33 classes to 22. The test suite drops one file and 17 cases; the
  remaining 89 pass.
- **`contexture.cli` is now the only module in the package that touches a
  filesystem**, and it does so only to scaffold a project. The claim
  `tests/test_layering.py` makes is stronger than the one it made before:
  nothing on the path from a declaration to the wire opens a file. The test was
  renamed to say so.
- **Breaking change to the public API.** `TargetRenderError` was exported from
  `contexture` and is gone. It was raised only by the deleted layer, so an
  `except TargetRenderError` outside this package could never have fired, but
  the import will now fail rather than the handler going quiet.
- `core/errors.py` holds five exceptions, all of them raisable by code that
  still exists.
- Design 02 keeps its section 5 as a record. The capability matrix in 5.2 — what
  each runtime *cannot* express — is still the clearest statement of the fact
  that motivated serving a declaration instead of rendering it, and that fact
  did not stop being true when the code implementing it went away.
- The atlas loses its multi-target rendering plate. This is the second time a
  removal has cost a plate; both times the plate documented a road that had
  already stopped being the main one.

## Not done here

- The three server-layer findings this deletion was reviewed alongside:
  `Dispatch` caching by `id()` without holding a reference, `Projection`
  reporting a constant, and the gateway tools each carrying two descriptions.
  Those are changes to code that runs, and they are kept separate from a
  deletion of code that does not.
- Any host-configuration rendering beyond `server/registration.py`, which emits
  the one file a host still needs: the launch command.
