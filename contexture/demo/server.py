"""The entry point a host launches.

    contexture demo                     # via the framework's own runner
    python -m contexture.demo.server

Nothing in this file mentions JSON-RPC, JSON Schema, stdio framing, or any
particular agent runtime. Claude Code and Codex run this same command.
"""

from __future__ import annotations

from contexture import Prompt, Resource
from contexture.server import ContextureApp
from .role import KubernetesPlatform

#: What this demo publishes on MCP's resource primitive.
#:
#: Both name a node the tree already holds, so a procedure can cite a document
#: by the name the document gives itself, and a model can reach the same bytes
#: by navigating to it. One capability, two addresses — not two declarations.
class CrashLoopRunbookDocument(Resource):
    def __init__(self) -> None:
        super().__init__(
            opens="kubernetes-platform/incident-response/crash_loop_runbook",
            uri="contexture://runbooks/crash-loop-backoff",
            mime_type="text/markdown",
            description=(
                "How to diagnose a container that keeps restarting, and what "
                "not to do."
            ),
        )


class RollbackPolicyDocument(Resource):
    def __init__(self) -> None:
        super().__init__(
            opens="kubernetes-platform/deployment-ops/rollback_policy",
            uri="contexture://runbooks/rollback-policy",
            mime_type="text/markdown",
            description=(
                "When a rollback is the right remediation, and what it costs."
            ),
        )


#: What this demo publishes on MCP's prompt primitive.
#:
#: One command, and the rule it passes is the rule `Prompt` states: declare one
#: only where going wrong is expensive. A rollback destroys the evidence that
#: would have shown whether it was the right move, so it is the one operation
#: here a person may want to start themselves — and starting it means putting
#: the procedure in context, not running anything.
#:
#: `model_may_open` is left at its default. Reserving this node would take the
#: procedure away from an agent that was asked to perform a rollback, while
#: `deployment-ops` goes on telling it to follow that procedure — a guardrail
#: that contradicts the instructions around it is a bug, not a guardrail. The
#: command is a second way in for a person, not a fence.
class RollBackARelease(Prompt):
    def __init__(self) -> None:
        super().__init__(
            opens="kubernetes-platform/deployment-ops/roll-back-a-failed-release",
            name="roll-back-a-release",
            description=(
                "Put the rollback procedure in context: what to capture "
                "before a release is reversed, and what reversing it destroys."
            ),
        )


PUBLISHED = (
    CrashLoopRunbookDocument,
    RollbackPolicyDocument,
    RollBackARelease,
)

app = ContextureApp(
    roots=KubernetesPlatform,
    publish=PUBLISHED,
    name="contexture-demo",
)


def main() -> None:
    """Serve the demo over stdio until the host disconnects."""

    app.run(transport="stdio")


if __name__ == "__main__":
    main()
