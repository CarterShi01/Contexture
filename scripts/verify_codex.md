# Verify with Codex

The point of this file is that it differs from `verify_claude_code.md` only in
the CLI syntax. Same server, same launch command, no Codex-specific artifacts.

```bash
uv sync
codex mcp add contexture-demo -- uv run contexture-incident-demo
codex mcp list          # expect: contexture-demo … enabled
```

Inside `codex`, `/mcp` shows the same.

## Drive it

```bash
codex exec "Use the contexture-demo MCP server to diagnose why pod \
payments-api-7d9c in namespace prod keeps restarting. Start from Contexture's \
disclosed role and skill context. Use MCP evidence instead of inspecting this \
repository's source code. Explain the root cause and the next remediation step."
```

## What counts as a pass

Identical to the Claude Code checklist, plus the thing this row exists to show:

- [ ] The launch command is the same string used for Claude Code.
- [ ] No `AGENTS.md` and no `~/.codex/config.toml` context entry was needed —
      only the server registration.

Codex reads the server's `instructions` field and asks that the first 512
characters be self-contained. `tests/test_projection.py` asserts that limit, so
a regression there fails before it reaches a host.

## Clean up

```bash
codex mcp remove contexture-demo
```

## Status

Not yet completed on this machine — the account hit its usage limit during
v0.0.4 verification. See `docs/verification/hosts.md`.
