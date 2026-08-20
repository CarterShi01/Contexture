"""The entry point a host launches.

    contexture demo                     # via the framework's own runner
    python -m contexture.demo.server

Nothing in this file mentions JSON-RPC, JSON Schema, stdio framing, or any
particular agent runtime. Claude Code and Codex run this same command.
"""

from __future__ import annotations

from contexture import Resource
from contexture.server import ContextureApp
from .role import KubernetesPlatform

#: What this demo publishes on MCP's resource primitive.
#:
#: Both name a node the tree already holds, so a procedure can cite a document
#: by the name the document gives itself, and a model can reach the same bytes
#: by navigating to it. One capability, two addresses — not two declarations.
#:
#: Nothing is published on the prompt primitive here. This demo has no
#: operation where going wrong is expensive enough to be worth reserving for a
#: person, and marking one anyway would make the example teach the opposite of
#: what the rule says.
PUBLISHED = (
    Resource(
        opens="kubernetes-platform/incident-response/crash_loop_runbook",
        uri="contexture://runbooks/crash-loop-backoff",
        mime_type="text/markdown",
        description=(
            "How to diagnose a container that keeps restarting, and what not "
            "to do."
        ),
    ),
    Resource(
        opens="kubernetes-platform/deployment-ops/rollback_policy",
        uri="contexture://runbooks/rollback-policy",
        mime_type="text/markdown",
        description="When a rollback is the right remediation, and what it costs.",
    ),
)

app = ContextureApp(
    roots=KubernetesPlatform(),
    publish=PUBLISHED,
    name="contexture-demo",
)


def main() -> None:
    """Serve the demo over stdio until the host disconnects."""

    app.run(transport="stdio")


if __name__ == "__main__":
    main()
