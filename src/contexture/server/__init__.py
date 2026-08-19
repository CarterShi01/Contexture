"""The inbound MCP surface: Contexture served as a native MCP server.

This is the layer the two mental models meet in. A business application
declares its context once in `contexture.core`, and every agent runtime —
Claude Code, Codex, anything else that speaks MCP — connects to the one server
this package builds, rather than reading a file compiled for it in advance.

It is the only layer that imports the official MCP SDK. `contexture.core` stays
free of it by design, and a layering test enforces that.
"""

from .app import ContextureApp, Transport, configure_logging
from .instructions import PREAMBLE
from .projection import DISCOVER_TOOL, GET_CONTEXT_TOOL, Projection, project
from .registration import (
    Launch,
    claude_code_config,
    cli_commands,
    codex_config,
    cursor_config,
)

__all__ = [
    "ContextureApp",
    "DISCOVER_TOOL",
    "GET_CONTEXT_TOOL",
    "Launch",
    "PREAMBLE",
    "Projection",
    "Transport",
    "claude_code_config",
    "cli_commands",
    "codex_config",
    "configure_logging",
    "cursor_config",
    "project",
]
