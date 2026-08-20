"""One-creator's Goal domain, served through Contexture.

Four layers, and the second one is empty on purpose:

    serve         `contexture serve` — reads pyproject, builds the server
    disclosure    the five gateway tools — the framework's, nothing written here
    domain        `goal/`   the role, its tools, skills, resources and model
                  `citizens/`  what makes an object first-class, ported from
                               one-creator's `domain/`
    storage       `db/`     three sqlite tables, schema identical to oc.db

The empty layer is the point of the exercise. In one-creator it is `Manager`'s
`@read(address=…)` decorators, a 254-line reflector and a registration chain in
brain-mcp — everything that decides what an agent sees and how it is addressed.
Here a reference is a path through the role tree, and the surface is five tools
whatever the declaration contains.

Importing this package binds the citizens to their tables. That is a
composition root's job and it has to happen before the role is used;
`contexture serve` resolves `oc_goal.goal:GoalDomain`, which imports this
first. Binding opens nothing — the database is touched when a tool actually
reads.
"""
from .wiring import bind_stores

bind_stores()

__all__ = ["bind_stores"]
