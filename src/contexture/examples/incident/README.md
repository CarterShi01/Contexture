# Incident demo

A Contexture MCP server with one deterministic Kubernetes incident. Claude Code
and Codex connect to it with the same command and get the same capabilities;
neither reads a generated `CLAUDE.md`, `AGENTS.md`, or `SKILL.md`.

## What it declares

```text
kubernetes-platform                              role   the coordinator
├── incident-response                            role
│   ├── diagnose-crash-loop-backoff              skill  procedure, on request
│   ├── get_pod_status                           tool   read-only
│   ├── get_pod_logs                             tool   read-only
│   ├── get_pod_events                           tool   read-only
│   └── crash-loop-runbook                       resource
└── deployment-ops                               role
    ├── roll-back-a-failed-release               skill  procedure, on request
    ├── get_rollout_status                       tool   read-only
    ├── roll_back_deployment                     tool   writes; needs approval
    └── rollback-policy                          resource
```

Three roles rather than one, because one role is the shape at which a gateway
surface is a bad trade: a session pays only for the branch it enters, and a
tree with one branch has nothing to not pay for.

## What a host actually sees

Five tools, and no Kubernetes anywhere in them:

```text
contexture_discover · contexture_open · contexture_read
contexture_invoke_read_only · contexture_invoke
```

Everything above — every name, description and schema — arrives inside a
payload, when the role holding it is opened. A session that only diagnoses
never pays for `deployment-ops`.

The roster is in the server's instructions, so a host knows what this server is
for before it calls anything.

## The two doors

`roll_back_deployment` is the demo's one destructive path, and it is why there
are two invoke tools rather than one. It is reached through `contexture_invoke`,
which carries no read-only hint, so a host can put a human in front of it.
Sending it to `contexture_invoke_read_only` is refused rather than executed —
otherwise the host's approval decision would have been made about a call it
could not see.

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
uv run contexture demo               # serves MCP over stdio; blocks
```

## Connect a host

```bash
# Claude Code — note that `mcp add` writes to local scope unless told otherwise
claude mcp add --scope project contexture-demo -- uv run contexture demo
claude mcp list

# Codex
codex mcp add contexture-demo -- uv run contexture demo
codex mcp list
```

Then ask either one:

> Use the contexture-demo MCP server to diagnose why pod payments-api-7d9c in
> namespace prod keeps restarting. Start from Contexture's disclosed role and
> skill context. Use MCP evidence instead of inspecting this repository's
> source code. Explain the root cause and the next remediation step.

## The trace to expect

```text
contexture_discover                → three role cards; the skeleton, no detail
contexture_open(incident-response) → its skills, tools with schemas, resource
contexture_open(skill)             → the full procedure, here and only here
contexture_invoke_read_only(...)   → CrashLoopBackOff, restart_count 14
contexture_invoke_read_only(...)   → ConfigurationError: DB_URL is missing
contexture_invoke_read_only(...)   → container exited with code 1
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
exist only behind `contexture_open`.
