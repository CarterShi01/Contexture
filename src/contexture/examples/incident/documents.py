"""Content this responder can consult.

Each of these is a read-only tool that takes no arguments — which is what
content already sitting there looks like once there is no separate kind of node
for it. Two calls return the same bytes, and nothing is computed from an
argument.

The body runs only when something actually reads it. A routing card costs one
line of description, which is the whole reason this is a tool of its own rather
than a paragraph pasted into a skill.

`server.py` also publishes both of these on MCP's resource primitive, at URIs
that do not move when the node does. That is a second address for one thing,
not a second copy of it.
"""

from __future__ import annotations

from contexture import Tool
from . import fixtures


class CrashLoopRunbook(Tool):
    """How to diagnose a container that keeps restarting, and what not to do."""

    name = "crash_loop_runbook"
    read_only = True

    async def invoke(self) -> str:
        return fixtures.CRASH_LOOP_RUNBOOK


class RollbackPolicy(Tool):
    """When a rollback is the right remediation, and what it costs."""

    name = "rollback_policy"
    read_only = True

    async def invoke(self) -> str:
        return fixtures.ROLLBACK_POLICY


__all__ = ["CrashLoopRunbook", "RollbackPolicy"]
