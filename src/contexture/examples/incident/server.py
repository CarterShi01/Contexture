"""The entry point a host launches.

    contexture-incident-demo

Nothing in this file mentions JSON-RPC, JSON Schema, stdio framing, or any
particular agent runtime. Claude Code and Codex run this same command.
"""

from __future__ import annotations

from ...server import ContextureApp
from .role import KubernetesIncidentResponder

app = ContextureApp(
    roots=KubernetesIncidentResponder(),
    name="contexture-incident-demo",
)


def main() -> None:
    """Serve the demo over stdio until the host disconnects."""

    app.run(transport="stdio")


if __name__ == "__main__":
    main()
