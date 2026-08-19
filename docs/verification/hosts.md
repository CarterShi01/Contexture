# Host verification — v0.0.4

Recorded 2026-08-19 against the branch `feature/native-mcp-server`.

The claim under test: **one server, one launch command, two hosts, no generated
context files.**

| Host | Version | Connected | Full diagnosis |
| --- | --- | --- | --- |
| Claude Code | 2.1.235 | ✅ | ✅ recorded below |
| Codex | 0.147.0 | ✅ registered | ⚠️ blocked — see below |
| Official SDK client | mcp 2.0.0 | ✅ | ✅ automated, `tests/test_stdio_server.py` |

## Claude Code

```bash
claude mcp add contexture-demo -- /path/to/.venv/bin/contexture-incident-demo
claude mcp list
# contexture-demo: … - ✔ Connected
```

Run headlessly with only the server's own tools allowed, so nothing could be
answered by reading this repository:

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

Result: 12 turns, no permission denials, `is_error: false`.

What the run demonstrates, point by point:

* It **found the role and skill through discovery**, not through the filesystem —
  it names `kubernetes-incident-responder` and `diagnose-crash-loop-backoff`,
  which appear nowhere except in the server's responses.
* It **followed the disclosed procedure in order** (status → logs → events →
  runbook), which only reached it via `contexture_get_context`.
* It **read the resource** rather than being handed its content up front.
* It **obeyed the constraint** that exists only inside the skill: it explicitly
  refused to recommend restarting the Pod first.
* It **distinguished exit 1 from exit 137**, which is the runbook's own test for
  separating a config failure from an OOM kill.

### Transcript

```text
## Diagnosis: `prod/payments-api-7d9c`

I started from the server's disclosed role (`kubernetes-incident-responder`), took its `diagnose-crash-loop-backoff` skill, and followed that procedure in order: status → logs → events → runbook.

**Evidence collected**

| Source | Finding |
| --- | --- |
| `get_pod_status` | `phase: Running`, `container_state: CrashLoopBackOff`, `restart_count: 14`, `ready: false`, image `registry.internal/payments-api:1.8.2` |
| `get_pod_logs` | `ERROR ConfigurationError: required environment variable DB_URL is missing`, followed by `FATAL startup aborted after configuration error` |
| `get_pod_events` | `Created container payments-api` ×15, `BackOff: Back-off restarting failed container` ×14, `Unhealthy: Container exited with code 1` ×14 |

**Root cause**

The container is missing the required environment variable `DB_URL`. The application reads its configuration at startup, finds `DB_URL` absent, logs `ConfigurationError`, and aborts before serving anything. It exits with **code 1** — an application-level self-rejection, not a kill. Per the runbook, exit 1 is what separates this from an OOM kill (which would be exit 137 and a different runbook), so memory limits are not implicated. The image pulls and the container is created successfully all 15 times, which rules out image or scheduling problems: the failure is entirely inside startup config loading.

Matching against the runbook's cause table, this is row one: *`ConfigurationError`, missing variable → Config or Secret not projected into the Pod.*

**Next remediation step**

Add the `DB_URL` key to the ConfigMap or Secret referenced by the `payments-api` Pod spec (and confirm the spec actually projects that key into the container as an env var), then roll out the Deployment.

Do not restart or delete the Pod first. The 14 restarts already performed are the same operation the kubelet is retrying automatically; a manual restart repairs nothing and just produces restart 15.

One scope note: the MCP tools here expose status, logs, and events only — there's no tool to read the ConfigMap/Secret or the Pod spec, so I can't tell you from evidence *which* object is missing the key or whether it's an absent key versus a broken `valueFrom` reference. That distinction needs a look at the workload manifest.
```

## Codex

Registration succeeded and the server is listed:

```bash
codex mcp add contexture-demo -- /path/to/.venv/bin/contexture-incident-demo
codex mcp list
# contexture-demo  …/contexture-incident-demo  -  -  -  enabled  Unsupported
```

The diagnosis run could **not** be completed:

```text
ERROR: You've hit your usage limit. … try again at Aug 21st, 2026 12:02 PM.
```

So **Codex is unverified end to end.** What is verified is that it accepts the
same launch command with no Codex-specific artifacts. The protocol path itself
is covered independently by `tests/test_stdio_server.py`, which drives the same
subprocess with the official SDK client over real stdio — including the legacy
handshake revision Codex may negotiate — but that is not a substitute for
running Codex itself.

To finish this row once the limit resets, see `scripts/verify_codex.md`.

## Automated equivalent

`tests/test_stdio_server.py` launches the demo as a subprocess and drives it
over real stdio with the official client, asserting:

* the 2026-07-28 revision is negotiated through `server/discover`
* a legacy host using `initialize` still gets a working server
* server instructions fit both hosts' limits (512-char opening, 2KB total)
* `read_only` appears as an annotation and in no input schema
* the full traversal produces the intended evidence
* a skill's procedure is absent from bootstrap and from every routing card, and
  present only after `contexture_get_context`
* resource content is absent from listing and from disclosure, and present only
  after a read
