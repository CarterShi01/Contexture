"""Host configuration that points at this server, rather than replacing it.

The one file a host still needs is the one that says how to launch the server,
which is what this module emits — not CLAUDE.md, not AGENTS.md, not a rendered
copy of the declaration in whatever dialect the runtime reads.

That distinction is the whole point of the pivot. A generated context file is a
copy that drifts the moment the declaration changes; a launch command is a
pointer that cannot.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field
from typing import Sequence


@dataclass(slots=True, frozen=True, kw_only=True)
class Launch:
    """How a host should start one Contexture server."""

    name: str
    command: str
    args: Sequence[str] = field(default_factory=tuple)

    def as_list(self) -> list[str]:
        return [self.command, *self.args]

    def as_shell(self) -> str:
        return " ".join(shlex.quote(part) for part in self.as_list())


def claude_code_config(launch: Launch) -> str:
    """Return `.mcp.json`, which Claude Code reads for project-scoped servers."""

    return _json(
        {
            "mcpServers": {
                launch.name: {
                    "type": "stdio",
                    "command": launch.command,
                    "args": list(launch.args),
                }
            }
        }
    )


def cursor_config(launch: Launch) -> str:
    """Return `.cursor/mcp.json`, which uses the same shape as Claude Code."""

    return claude_code_config(launch)


def codex_config(launch: Launch) -> str:
    """Return the `~/.codex/config.toml` stanza for this server.

    Hand-rolled rather than serialized through a TOML writer: this is three
    keys of known shape, and the alternative is a dependency whose only job
    would be to quote a command string.
    """

    lines = [
        f"[mcp_servers.{launch.name}]",
        f"command = {json.dumps(launch.command)}",
        f"args = {json.dumps(list(launch.args))}",
    ]
    return "\n".join(lines) + "\n"


def cli_commands(launch: Launch) -> dict[str, str]:
    """Return the one-liner each host documents for adding a stdio server."""

    return {
        # Claude Code writes to local scope unless a scope is named; project
        # scope is what puts the server in a file a team shares.
        "claude-code": (
            f"claude mcp add --scope project {launch.name} -- {launch.as_shell()}"
        ),
        "codex": f"codex mcp add {launch.name} -- {launch.as_shell()}",
    }


def _json(payload: object) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


__all__ = [
    "Launch",
    "claude_code_config",
    "cli_commands",
    "codex_config",
    "cursor_config",
]
