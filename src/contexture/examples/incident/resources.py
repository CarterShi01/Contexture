"""The runbook this responder can consult.

The content is produced only when something reads the resource. Listing it
costs one line of description, which is the whole reason a resource is a
resource and not a paragraph pasted into a skill.
"""

from __future__ import annotations

from contexture import Resource
from . import fixtures


class CrashLoopRunbook(Resource):
    """How to diagnose a container that keeps restarting, and what not to do."""

    uri = "contexture://runbooks/crash-loop-backoff"
    mime_type = "text/markdown"

    async def read(self) -> str:
        return fixtures.CRASH_LOOP_RUNBOOK


class RollbackPolicy(Resource):
    """When a rollback is the right remediation, and what it costs."""

    uri = "contexture://runbooks/rollback-policy"
    mime_type = "text/markdown"

    async def read(self) -> str:
        return fixtures.ROLLBACK_POLICY


__all__ = ["CrashLoopRunbook", "RollbackPolicy"]
