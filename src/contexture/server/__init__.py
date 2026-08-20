"""The inbound MCP surface: Contexture served as a native MCP server.

This is the layer the two mental models meet in. A business application
declares its context once in `contexture.core`, and every agent runtime —
Claude Code, Codex, anything else that speaks MCP — connects to the one server
this package builds, rather than reading a file compiled for it in advance.

**What** this server exposes is declared one layer down, in
`core.mcp_interface`, one module per MCP primitive. This package is **how**:
the SDK calls, the dispatch, and every sentence said to whoever is reading.

Four responsibilities share it, and they change at four different rates, so
they are four modules rather than one:

    identity        who is calling: the socket a business plugs its token
                    verifier into, and the protocol facts around it. Moves
                    when the authorization specification does.
    messages        everything said *to* somebody: the bootstrap text, the
                    sentence a failed lookup becomes, what a person reads at
                    the top of a command. Moves when the way an agent is
                    taught to walk the tree changes.
    instructions    fitting that text into one host's budget. Moves when Claude
                    Code or Codex ships.
    binding         hanging the declared surface on the SDK. Moves when the
                    SDK does.

`app` composes the three; `launch` emits the one file a host still needs — the
command that starts this server — and belongs to none of them.

Only `app` and `binding` import the official MCP SDK, and this facade resolves
its exports lazily so that the two modules which do not — `messages` and
`launch` — stay importable, and testable, without a wire in the room.
"""

from __future__ import annotations

import importlib
from typing import Any

#: Exported name -> the submodule that defines it.
_EXPORTS = {
    "ContextureApp": ".app",
    "ContextureOptions": ".app",
    "DEFAULT_HOST": ".app",
    "DEFAULT_PATH": ".app",
    "DEFAULT_PORT": ".app",
    "LOOPBACK": ".app",
    "ServeError": ".app",
    "Transport": ".app",
    "configure_logging": ".app",
    "Auth": ".identity",
    "TokenVerifier": ".identity",
    "principal_of": ".identity",
    # The entry points are declared one layer down, in
    # `core.mcp_interface`, beside what this server puts on the other two
    # primitives. They are forwarded here because `contexture.server` is where
    # a caller looks for what is on the wire — but they are defined there, and
    # this is a pointer rather than a second copy.
    "DISCOVER_TOOL": "..core.mcp_interface.tool",
    "GATEWAY": "..core.mcp_interface.tool",
    "GATEWAY_TOOLS": "..core.mcp_interface.tool",
    "GatewayTool": "..core.mcp_interface.tool",
    "INVOKE_READ_ONLY_TOOL": "..core.mcp_interface.tool",
    "INVOKE_TOOL": "..core.mcp_interface.tool",
    "OPEN_TOOL": "..core.mcp_interface.tool",
    "PREAMBLE": ".messages",
    "unresolved": ".messages",
    "Dispatch": ".binding",
    "project": ".binding",
    "Launch": ".launch",
    "claude_code_config": ".launch",
    "cli_commands": ".launch",
    "codex_config": ".launch",
    "cursor_config": ".launch",
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
