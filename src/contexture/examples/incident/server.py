"""The entry point a host launches.

    contexture demo                     # via the framework's own runner
    python -m contexture.examples.incident.server

Nothing in this file mentions JSON-RPC, JSON Schema, stdio framing, or any
particular agent runtime. Claude Code and Codex run this same command.
"""

from __future__ import annotations

from contexture.server import ContextureApp
from .role import KubernetesPlatform

app = ContextureApp(
    roots=KubernetesPlatform(),
    name="contexture-demo",
)


def main() -> None:
    """Serve the demo over stdio until the host disconnects."""

    app.run(transport="stdio")


if __name__ == "__main__":
    main()
