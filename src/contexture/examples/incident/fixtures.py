"""The one incident this demo knows about, stated once.

A single unhealthy Pod with a cause that cannot be guessed from its symptom:
the restart loop looks like a scheduling or image problem until something
actually reads the logs. That is the point — it forces the traversal the demo
is meant to demonstrate, instead of rewarding a lucky guess.
"""

from __future__ import annotations

NAMESPACE = "prod"
POD = "payments-api-7d9c"

POD_STATUS = {
    "namespace": NAMESPACE,
    "pod": POD,
    "phase": "Running",
    "container_state": "CrashLoopBackOff",
    "restart_count": 14,
    "ready": False,
    "image": "registry.internal/payments-api:1.8.2",
}

POD_LOGS = """\
2026-08-19T09:12:04Z INFO  payments-api starting, build 1.8.2
2026-08-19T09:12:04Z INFO  loading configuration from environment
2026-08-19T09:12:04Z ERROR ConfigurationError: required environment variable \
DB_URL is missing
2026-08-19T09:12:04Z FATAL startup aborted after configuration error\
"""

POD_EVENTS = [
    {
        "type": "Normal",
        "reason": "Pulled",
        "message": "Container image already present on machine",
        "count": 15,
    },
    {
        "type": "Normal",
        "reason": "Created",
        "message": "Created container payments-api",
        "count": 15,
    },
    {
        "type": "Warning",
        "reason": "BackOff",
        "message": "Back-off restarting failed container",
        "count": 14,
    },
    {
        "type": "Warning",
        "reason": "Unhealthy",
        "message": "Container exited with code 1",
        "count": 14,
    },
]

CRASH_LOOP_RUNBOOK = """\
# Runbook: CrashLoopBackOff

A container that starts and exits repeatedly. Kubernetes backs off between
restarts, so the symptom is visible long before the cause is.

## Order of investigation

1. **Status first.** A high `restart_count` with `ready: false` confirms the
   loop rather than a slow start.
2. **Logs before events.** The container's own output names the failure.
   Events describe what the kubelet observed, which is one level removed.
3. **Correlate the exit code.** Exit code 1 is an application-level failure:
   the process ran and then rejected its own state. Exit code 137 would mean
   it was killed, usually for memory, which is a different runbook.

## Common causes, in the order they are usually found

| Evidence in logs | Cause | Remediation |
| --- | --- | --- |
| `ConfigurationError`, missing variable | Config or Secret not projected into the Pod | Add the key to the ConfigMap or Secret, then roll out |
| Connection refused to a dependency | Dependency unavailable, or wrong address | Fix the address, or wait for the dependency |
| Panic or uncaught exception on startup | Application defect | Roll back to the last good image |
| OOMKilled, exit 137 | Memory limit too low | Raise the limit |

## Do not

Restarting the Pod does not repair a configuration error; it produces restart
15. Identify the cause before recommending any change.
"""


DEPLOYMENT = "payments-api"

ROLLOUT_STATUS = {
    "namespace": NAMESPACE,
    "deployment": DEPLOYMENT,
    "current_revision": 9,
    "previous_revision": 8,
    "current_image": "registry.internal/payments-api:1.8.2",
    "previous_image": "registry.internal/payments-api:1.8.1",
    "updated_replicas": 3,
    "available_replicas": 0,
    "rolled_out_at": "2026-08-19T09:11:47Z",
}

#: The write path is a fixture too. A demo that could really roll a cluster
#: back would be demonstrating a cluster, not a framework.
ROLLBACK_POLICY = """\
# Policy: rolling back a failed release

A rollback is a remediation, not a diagnosis. It restores the previous revision
and destroys the evidence of why the current one failed.

Before rolling back:

- Establish the cause from the workload's own output. A rollback that follows a
  guess teaches nothing and will be needed again on the next release.
- Capture logs and events first. The failing Pods are replaced immediately.
- Check whether the cause is in the image at all. A missing environment
  variable, a bad ConfigMap, or an absent Secret follows the previous revision
  back and reappears.

After rolling back, the incident is not closed. The release that failed is
still the release that will be re-attempted.
"""
