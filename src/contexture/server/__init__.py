"""The inbound MCP surface: Contexture served as a native MCP server.

This is the layer the two mental models meet in. A business application
declares its context once in `contexture.core`, and every agent runtime —
Claude Code, Codex, anything else that speaks MCP — connects to the one server
this package builds, rather than reading a file compiled for it in advance.

Three responsibilities share this package, and they change at three different
rates, so they are three modules rather than one:

    contract        what the agent reads: the vocabulary, the bootstrap
                    contract, each entry point's description, and the sentence
                    a failed lookup becomes. Moves when the way an agent is
                    taught to walk the tree changes.
    instructions    fitting that text into one host's budget. Moves when Claude
                    Code or Codex ships.
    projection      hanging it on the SDK. Moves when the SDK does.

`app` composes the three; `registration` emits the launch command a host needs
and belongs to none of them.

Only `app` and `projection` import the official MCP SDK, and this facade
resolves its exports lazily so that the two modules which do not — `contract`
and `registration` — stay importable, and testable, without a wire in the room.
"""

from __future__ import annotations

import importlib
from typing import Any

#: Exported name -> the submodule that defines it.
_EXPORTS = {
    "ContextureApp": ".app",
    "Transport": ".app",
    "configure_logging": ".app",
    "DISCOVER_TOOL": ".contract",
    "GATEWAY": ".contract",
    "GATEWAY_TOOLS": ".contract",
    "GatewayTool": ".contract",
    "INVOKE_READ_ONLY_TOOL": ".contract",
    "INVOKE_TOOL": ".contract",
    "OPEN_TOOL": ".contract",
    "PREAMBLE": ".contract",
    "READ_TOOL": ".contract",
    "unresolved": ".contract",
    "Dispatch": ".projection",
    "project": ".projection",
    "Launch": ".registration",
    "claude_code_config": ".registration",
    "cli_commands": ".registration",
    "codex_config": ".registration",
    "cursor_config": ".registration",
}


def __getattr__(name: str) -> Any:
    """Resolve an export on first use, then cache it in the module globals."""

    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(__all__)


__all__ = sorted(_EXPORTS)
