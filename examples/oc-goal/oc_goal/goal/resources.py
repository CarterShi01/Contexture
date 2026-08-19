"""Content this domain already holds, fetched only when asked for.

Both of these are resources rather than read-only tools by the test that
separates the two: they take no arguments, and two reads return the same bytes
until the underlying thing changes. `GetGoal` computes an answer from a slug;
these are already there.

`ObjectShapes` has no counterpart in one-creator's MCP surface, and that is a
gap rather than an omission. Its domain surface is published as three things —
objects, operations, resources — and the object half never reached an agent:
field constraints existed only inside each write tool's input schema, so
nothing could answer "what is an Area" without first deciding to change one.
Contexture has no node type for a schema either, so it lands here, where a
listing costs one sentence and the schema itself costs a read.
"""
from __future__ import annotations

import json

from contexture import Resource

from ..citizens import schema as citizen_schema
from .model import Area, Focus, Goal


class CurrentFocus(Resource):
    """The founder's current main thread and not-doing list."""

    uri = "goal://focus"
    mime_type = "application/json"

    async def read(self) -> str:
        # `read()`, not `current()`: the document's raw mapping is the contract
        # this address has always had, and returning an object would silently
        # change the payload's shape.
        return json.dumps(Focus.read(), ensure_ascii=False, indent=2)


class ObjectShapes(Resource):
    """The fields, constraints and invariants of Area, Goal and Focus."""

    uri = "goal://objects"
    mime_type = "application/json"

    async def read(self) -> str:
        shapes = {
            "Area": citizen_schema.of_citizen_document(Area),
            "Goal": citizen_schema.of_citizen_document(Goal),
            "Focus": _document_shape(Focus),
        }
        return json.dumps(shapes, ensure_ascii=False, indent=2)


def _document_shape(cls) -> dict:
    """A singleton has no primary key, so it gets no container wrapper.

    The same field reflector runs over it; what it does not get is the
    `{<key>: {...}}` envelope a keyed citizen's document is stored in.
    """

    return {
        "type": "object",
        "properties": {
            name: citizen_schema.of_field(spec)
            for name, spec in cls.__fields__.items()
        },
    }


__all__ = ["CurrentFocus", "ObjectShapes"]
