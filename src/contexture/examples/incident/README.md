# Incident demo

A Contexture MCP server with one deterministic Kubernetes incident. Claude Code
and Codex connect to it with the same command and get the same capabilities;
neither reads a generated `CLAUDE.md`, `AGENTS.md`, or `SKILL.md`.

## What it declares

```text
KubernetesIncidentResponder            role
└── diagnose-crash-loop-backoff        skill   the procedure, disclosed on request
    ├── get_pod_status                 tool    read-only
    ├── get_pod_logs                   tool    read-only
    ├── get_pod_events                 tool    read-only
    └── contexture://runbooks/crash-loop-backoff
                                       resource  content read on demand
```

The incident is fixed: `payments-api-7d9c` in `prod` is in `CrashLoopBackOff`
with 14 restarts, its logs name a missing `DB_URL`, and its events record exit
code 1. Nothing contacts a cluster, so a failed run means the framework failed
rather than the environment.

The symptom does not reveal the cause. A restart loop looks like a scheduling
or image problem until something reads the logs — which is what forces the
traversal this demo exists to show, instead of rewarding a guess.

## Run it

```bash
uv sync
uv run contexture-incident-demo      # serves MCP over stdio; blocks
```

## Connect a host

```bash
# Claude Code — note that `mcp add` writes to local scope unless told otherwise
claude mcp add --scope project contexture-demo -- uv run contexture-incident-demo
claude mcp list

# Codex
codex mcp add contexture-demo -- uv run contexture-incident-demo
codex mcp list
```

Then ask either one:

> Use the contexture-demo MCP server to diagnose why pod payments-api-7d9c in
> namespace prod keeps restarting. Start from Contexture's disclosed role and
> skill context. Use MCP evidence instead of inspecting this repository's
> source code. Explain the root cause and the next remediation step.

## The trace to expect

```text
contexture_discover           → the responder's routing card
contexture_discover(role:…)   → skill, tools, and resource, as cards only
contexture_get_context(skill) → the full procedure arrives here, and only here
get_pod_status                → CrashLoopBackOff, restart_count 14
get_pod_logs                  → ConfigurationError: DB_URL is missing
get_pod_events                → container exited with code 1
read contexture://runbooks/crash-loop-backoff
                              → matches row 1 of the cause table
```

The conclusion: the container is not being killed, it is rejecting its own
startup state because `DB_URL` is absent, and exit code 1 rather than 137
separates that from an out-of-memory kill. The remediation is to add the key
and roll out — *not* to restart the Pod, which the skill and the runbook both
rule out.

An agent is free to skip the traversal and call a tool directly; the surface is
flat and every tool is visible. What disclosure controls is knowledge, not
access. The procedure, the ordering, and the "do not restart first" constraint
exist only behind `contexture_get_context`.
