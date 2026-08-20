# ADR 007 — The role axis is lazy too


> **One detail superseded by [ADR 013](013-a-constructor-is-the-declaration.md).**
> The payload key is now `roles` rather than `sub_roles`, and `discover`
> answers with the same three keys `open` does, because a standalone skill or
> tool may also be a root. The laziness this ADR decided is unchanged.
**Status:** accepted, implemented in v0.2.0
**Date:** 2026-08-19

**Supersedes:** [ADR 004](004-progressive-disclosure-as-a-lazy-role-tree.md),
Decision B, in part. Its reasoning stands; its conclusion was over-applied.

## Context

ADR 004 split disclosure by **kind** rather than by depth: capability detail
waits until a role is opened, while the role skeleton is delivered whole. The
justification given for delivering it whole was this:

> Splitting by kind pays for neither, and removes the wrong-branch guess
> entirely, **because every sibling is visible before the choice.**

That is correct, and it remains the rule. But it is a claim about **one sibling
set**, and the implementation delivered **every sibling set in the forest**.
Those are the same thing at the six-role, two-level example the ADR traced
against, which is why the conflation was invisible. They stop being the same
thing at depth three.

Measured, with a card at its real size (~147 bytes) and a round trip at the
~200 tokens ADR 004 used:

| shape | roles | whole skeleton | one level per call | ratio |
| --- | ---: | ---: | ---: | ---: |
| six roles (ADR 004's example) | 6 | 596 | 656 | 0.9× |
| 3×2 | 13 | 841 | 957 | 0.9× |
| 5×3 | 156 | 6,083 | 1,540 | 4.0× |
| 8×3 | 585 | 21,845 | 1,852 | 11.8× |
| 10×4 | 11,111 | 441,208 | 2,727 | 161.8× |

The crossover is around thirty roles. Below it the eager skeleton wins, and
ADR 004's trace lands there — so its conclusion was right about its own
example and wrong as a general rule.

Three things make this worth reversing rather than tolerating.

**The framework claims the scale where it fails.** The README's comparison with
the SDK says Contexture assumes "hundreds of capabilities, most of them out of
context". At 585 roles the skeleton is 21,000 tokens **before the agent has
asked anything**, which is precisely the cost the gateway exists to avoid. At
eleven thousand roles it does not fit in a 200k window at all: the server is
unusable, and nothing in the code says so.

**The mechanism was already there.** `open()` has always returned `sub_roles`
cards. The role axis was already lazily traversable; `skeleton()` simply also
delivered all of it eagerly. This change is mostly subtraction.

**The bootstrap roster truncated along the wrong axis.** `instructions.build()`
caps the roster at 1200 characters and walked depth-first, so a wide, deep
forest spent the entire budget on one spine — the root, its first child, its
first grandchild — and never mentioned the root's other children. For text
whose only job is routing, that is the worst reachable answer.

## Decision

**`contexture_discover` answers with the roots.** Everything below arrives from
`contexture_open`, one level at a time, alongside everything else that role
holds. The surface is still five tools; `discover` simply returns less.

Entering a server now costs the number of roots rather than the size of the
forest, and a branch costs only what is on the way down it.

**The bootstrap roster walks breadth-first**, and still fills its budget. It
differs from `discover` on purpose: it costs no round trip, so a small forest
may as well arrive whole, and a large one is cut after the levels that matter
most for routing rather than after one spine.

## Consequences

- Reaching depth *d* takes *d* round trips before work begins. For a shallow
  tree this is marginally worse than before — the table's 0.9× rows — and that
  is accepted: the change makes small trees slightly more expensive and large
  trees possible at all.
- **A new obligation on whoever declares a role: its description must route for
  its whole subtree.** An agent choosing among siblings can no longer see the
  grandchildren. This is deliberately a documented constraint rather than a
  mechanism; adding a subtree summary or a child count to the card would be
  machinery compensating for a description that was not written to route.
- `ContextTree.roles_with_refs()` stays, depth-first, for callers that
  legitimately want the whole forest: `contexture list` printing a tree to a
  terminal, and the statelessness suite enumerating everything a server can be
  asked. `roles_by_level()` is new and is what gets truncated.
- `PREAMBLE` now tells the agent that a call reveals one level and to keep
  opening down the branch. It is 508 characters against Codex's 512-character
  self-contained window — four characters of headroom, and a test holds it
  there.
- `tests/test_stdio_server.py` navigates root → sub-role instead of expecting
  `discover` to name a specialism directly, which is a better test of the model
  it is checking. It also now asserts that `discover`'s payload does *not*
  contain a sub-role name.

## Not done here

- **A depth-bounded `discover`** — return *N* levels, default 2 — was
  considered. It would have kept the demo's behaviour identical while capping
  cost, but the constant has no principled answer, and "one call shows one
  level of siblings" is the rule ADR 004 already argued for. Rejected for the
  rule.
- **Adapting to tree size** — deliver the whole forest when it is small — was
  rejected for the same reason from the other side: what `discover` returns
  should not be something a model has to infer from the size of the server it
  is talking to.
- Whether a *host* can be trusted to walk several levels before doing any work
  is unmeasured, like everything else about real hosts here. It is the same
  open risk as HANDOFF item 3, now with more levels to walk.
