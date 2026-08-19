# oc-goal

One real domain from [one-creator](https://github.com/CarterShi01/one-creator) —
attention allocation: areas that never end and hold a budget, goals that end and
hold criteria — rebuilt on Contexture's four objects, against the same database
as the original.

Where the other reference application keeps its data in a fixtures module, this
one has a primary key, compare-and-set, write-locked fields and a global
invariant, because the question it exists to answer is what happens to a real
model layer.

- **[DESIGN.md](DESIGN.md)** — the object models and how they relate, what was
  ported and what was not, and two things Contexture turned out not to have.
- **[PLAN.md](PLAN.md)** — what is verified, what is not, and the experiment
  this demo was built to run.

## Run it

```bash
export OC_OBJECT_DB_PATH=/tmp/oc-goal.db   # optional: point at a real oc.db instead
python -m oc_goal.seed                     # refuses a database that already holds areas
python check.py                            # 34 assertions, no MCP SDK needed

contexture list                            # what would be served
contexture serve                           # serve it over stdio
```

Without `OC_OBJECT_DB_PATH` the database lands under your data directory, so
this works on a machine that has never heard of one-creator.

## What is here

```
oc_goal/
  goal/            the role and everything it holds
    role.py        GoalDomain — flat, no child roles
    tools.py       4 reads, 4 writes
    skills.py      review-the-attention-chain
    resources.py   goal://focus, goal://objects
    model.py       Area, Goal, Focus
  citizens/        what makes an object first-class — ported from one-creator
  db/              three sqlite tables, DDL identical to oc.db
  surface.py       where a write contract lives once there is no Manager
  wiring.py        hands each citizen its table
  seed.py          sample data for an empty database
check.py           drives every node
```

Four layers, and the disclosure layer is empty: the surface is five gateway
tools whatever this declares, and a reference is a path through the role tree.
In one-creator that layer is a set of address decorators, a 254-line reflector
and a registration chain. Removing it is the finding, and
[DESIGN.md §3](DESIGN.md) shows the accounting.

## Sharing a database

The DDL is copied column for column and `user_version` is never written, so
pointing this at one-creator's `oc.db` is a no-op on the schema, and creating a
fresh database leaves one-creator free to migrate it later. Concurrent writes
are safe: compare-and-set is one `BEGIN IMMEDIATE` transaction, so a second
writer gets a `ConflictError` rather than a race.
