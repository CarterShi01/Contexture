# Verify with Claude Code

```bash
uv sync
```

## Register

`claude mcp add` writes to **local** scope unless told otherwise. Local scope is
private to you; project scope writes `.mcp.json` for the team and requires
approval on first use inside `claude`.

```bash
# private to this machine
claude mcp add contexture-demo -- uv run contexture-incident-demo

# or shared with the team
claude mcp add --scope project contexture-demo -- uv run contexture-incident-demo
```

Check it:

```bash
claude mcp list          # expect: contexture-demo … ✔ Connected
claude mcp get contexture-demo
```

Inside `claude`, `/mcp` shows the same.

## Drive it

Restricting `--allowedTools` to the server's own tools is the point: it proves
the answer came over MCP and not from reading this repository.

```bash
claude -p "Use the contexture-demo MCP server to diagnose why pod \
payments-api-7d9c in namespace prod keeps restarting. Start from Contexture's \
disclosed role and skill context. Use MCP evidence instead of inspecting this \
repository's source code. Explain the root cause and the next remediation step." \
  --allowedTools \
    "mcp__contexture-demo__contexture_discover" \
    "mcp__contexture-demo__contexture_get_context" \
    "mcp__contexture-demo__get_pod_status" \
    "mcp__contexture-demo__get_pod_logs" \
    "mcp__contexture-demo__get_pod_events" \
    "ReadMcpResource"
```

## What counts as a pass

- [ ] It names `kubernetes-incident-responder` and `diagnose-crash-loop-backoff`
      — both reachable only through discovery.
- [ ] It calls all three tools and reads the runbook.
- [ ] Root cause: `DB_URL` missing, container exits 1, not an OOM kill.
- [ ] It refuses to recommend restarting first — a constraint that exists only
      inside the skill's instructions.
- [ ] No `CLAUDE.md`, `SKILL.md`, or `.claude/skills/**` was involved.

## Clean up

```bash
claude mcp remove contexture-demo
```
