# ADR 014 — Navigation is part of the kernel

**Status:** accepted, implemented in v0.6.0
**Date:** 2026-08-21

**Supersedes** section 2 of [ADR 010](010-the-directories-are-the-architecture.md),
which put `tree.py` in a directory of its own. Everything else ADR 010 decided
stands.

## Context

Progressive disclosure is what this framework is for, and it had no single
home. Three symptoms, all of them visible in the code rather than argued from
first principles.

**The four verbs were cut into three pieces.** `contexture_discover`,
`contexture_open`, `contexture_invoke_read_only` and `contexture_invoke` kept
their *identity* (name, description, `read_only`) in `core/mcp_interface/tool.py`,
their *behaviour* in four closures in `server/binding.py`, and the *object they
act on* in `core/disclosure/tree.py`. Those closures held no business of their
own: each one forwarded to a `ContextTree` method, derived a schema, and wrapped
an exception.

**The seam left a mark in a docstring.** `server/messages.py` explained why the
agent-facing sentence for a failed lookup could not be written where the failure
happened:

> When a lookup fails inside `core.disclosure`, the useful half of the reply is
> "call `contexture_open` on the role you came from" — and the tree does not
> know the gateway tool names, and must not.

That is true only while the entry points belong to somebody else. It is a
constraint the architecture imposed on itself and then had to work around.

**Two objects claimed the same graph.** `ContextTree` held its own `roots`
alongside a `ControllerManager` that had already registered them, and needed a
defensive check to confirm the two agreed:

```python
elif self.manager.roots != self.roots:
    raise ModelValidationError("... two answers to what is being served is one too many.")
```

**Disclosure was polymorphic in name only.** Every node compiled *itself*, but
which nodes were asked, and what each kind's payload contained, was decided by
five `isinstance` chains in `tree.py` — `open`, `_by_kind`, `_tool_card`,
`signpost`, `_reference_card`. A fifth kind of node would have been five edits
in a module that owns none of them.

## Decision

### 1. `core` is two directories and a shared base

```text
core/
├── errors.py  types.py  constants.py  principal.py     shared ground
├── model/          node · role · skill · tool · manager · tree · system_api
└── mcp_interface/  prompt · resource · tool (names only)
```

`core/disclosure/` is gone and `tree.py` sits beside the nodes it discloses.
ADR 010 named that directory for the two things it invented — the reference and
the level — but `CompileLevel` was always in `node.py`, so the claim only ever
covered the reference. Navigation is the kernel's, so the reference is too.

`SEPARATOR` and the four entry-point names move to `core/constants.py`. Three
layers that may not import each other all hold reference strings; shared ground
is what lets them name the same thing without a second copy going stale.

### 2. A node discloses itself; the tree is the view it asks

`ContextNode` gains `card(view)`, and `_compile_active` takes a `Disclosure` —
a four-method port (`ref_of`, `card_of`, `card_for`, `schema_of`) that answers
the two things a node cannot work out: where it hangs, and what its schema is.

The five `isinstance` chains are gone. `open` is one line. A `Role` renders its
own members, a `Skill` its own `uses` cards, a `Tool` its own schema — and
`ContextTree.open` no longer knows there are three kinds.

This overturns a rule `Role._compile_active` used to state: that a role could
not list its members because it could not give them addresses. The reasoning
was right and the conclusion too strong. A role does not need to know how an
address is *spelled* in order to hand one out; it asks the view, so every card
it renders is openable by construction. It is the same distinction `node.path`
already drew — position without spelling.

`_Alone` fills in when nobody supplies a view, answering from `path` and
falling back to the node's own name. So `core.model` can disclose a declaration
end to end with no tree and no server in the room.

### 3. The three node kinds are closed

`group` is a `ClassVar` on each kind, one of `roles` / `skills` / `tools`, and
a payload always carries all three keys. Three named fields translate to Go and
TypeScript; an open map of kinds does not. Adding a fourth kind is a breaking
change to the framework, which is the honest price.

### 4. The four entry points are the kernel's: `core/model/system_api.py`

Names, descriptions, `read_only`, behaviour, and every refusal, in one module.
`SystemAPI` binds them to one tree with two injected seams — `schema_of` on the
tree, `execute` here — so nothing in `core` learns what JSON Schema is or how an
argument is validated.

**They are not `Tool` nodes and must not become any.** A `Tool` is declared by a
business, hangs in a role, and is paid for by disclosure. These are fixed logic
that exists before any declaration. Modelling them as nodes would put the
framework's own plumbing into the forest it is disclosing.

The door check (`read_only` is which entry point, not which argument) and the
`reserved` check (a node a person has claimed) move here with them. Both are
answers to "who may run this, and how" — ADR 008's question, not the wire's.

### 5. `mcp_interface` is the business-extensible face

| primitive | what a business writes | what it points at |
| --- | --- | --- |
| prompt | `class Command(Prompt)`, `opens=…` | a node, typically a skill |
| resource | `class Runbook(Resource)`, `opens=…`, `uri=…` | a read-only, argument-less tool |
| tool | **nothing** | occupied by the kernel's four |

The third row is the design, not a gap: an entry on the tool primitive is one
every session pays for forever. So `core/mcp_interface/tool.py` keeps the four
*names* and nothing else, which is the same sentence the other two write — a
name pointing into `core`. `ALLOWED["core.mcp_interface"] = {"core.__base__"}` is
unchanged: no module here imports the object model.

### 6. What a call answers with belongs to `core`; an opening belongs to the host

`unresolved`, `wrong_door` and `taken_by_a_person` move to `system_api`, beside
the calls that raise them. `PREAMBLE`, the roster, `goto` and the command text
stay in `server`, because what fits in one host's instructions field is a fact
about that host's release.

`server/binding._translated` collapses to one branch: every failure that
reaches it already carries its sentence.

### 7. `ControllerManager` and `ContextTree` stay two types

They were **not** merged, and the reason is time rather than tidiness.
Registration is additive and mutable; disclosure is sealed and frozen. Sealing
is the earliest moment the whole-forest checks can run — a skill in the first
registered root may legitimately name a capability in the third, which
`tests/test_tree.py::test_a_crossing_is_allowed_and_reported` pins by doing
exactly that. Folding the checks into registration turns that test red; folding
the two phases into one mutable object with a `sealed` flag says with a boolean
what two types say in the signature.

What *was* merged is the duplication:

- `ContextTree.roots` is a property over the manager; the defensive check is gone.
- `register_root` moved to `manager.py`, where every line of it already pointed.
- `ControllerManager.sealed(schema_of=…)` is the one construction path;
  `ContextTree.of(...)` is sugar over it.
- `crossings` and `_reject_unresolvable_uses` read `manager.of_kind("skill")`
  and `manager.address_of`, which existed and had no callers.

## Consequences

**The whole agent trace is testable without the SDK.** `tests/test_system_api.py`
runs the sequence `docs/verification/hosts.md` records a host taking — discover,
open a root, open a specialism, open a skill, three read-only invokes — plus
both wrong-door refusals, a wrong ref, signposts, reserved nodes and
statelessness, importing no `mcp`. Before this, a checkout without the SDK could
assert nothing about what an agent receives. `test_stdio_server.py` keeps the
claims that genuinely need a wire.

**The reference face is exercised.** `demo/skills.py` declared its cross-role
dependency in prose — "using the incident-response role" — which is unresolvable
by anything. It is now `uses=(…)`, so it is checked at startup, arrives as a
ROUTE card, and would be listed by `crossings()` if it ever left the branch.
(It does not, so `crossings()` on the demo is still empty and cross-root
auditing stays covered by unit tests.)

**The demo publishes one command.** `roll-back-a-release` opens the rollback
skill for a person. `model_may_open` is left at its default: reserving that node
would take the procedure away from an agent that `deployment-ops` instructs to
follow it, and a guardrail that contradicts the instructions around it is a bug.

**The routing-sentence rule is measured, not enforced.** `inspection` reports a
description that runs past 200 characters or names something its node holds.
`core` still refuses only what is structurally unusable: past that the rule is
about wording, and a framework with an opinion about English is wrong in Chinese
and wrong again in Go.

**Removed:** `core.disclosure` (package), `core.mcp_interface.tool.GATEWAY`,
`GATEWAY_TOOLS` and `GatewayTool` (moved to `core.model.system_api`, the record
renamed `SystemTool`), `server.messages.unresolved` / `wrong_door` /
`command_taken_by_a_person`. `contexture.server` still forwards the entry-point
names, so a caller that asks `contexture.server` what is on the wire is
unaffected.
