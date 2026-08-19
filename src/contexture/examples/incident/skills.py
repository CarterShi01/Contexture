"""The procedure that turns three tools into a diagnosis.

These instructions are the payload progressive disclosure exists to defer. They
are never in the bootstrap text and never on a routing card; an agent receives
them only after calling contexture_get_context on this skill's ref.
"""

from __future__ import annotations

from ...core.skill import Skill


class DiagnoseCrashLoopBackOff(Skill):
    """Find why a Pod restarts repeatedly, before proposing any remediation."""

    name = "diagnose-crash-loop-backoff"

    instructions = """\
Establish the cause from evidence, in this order.

1. Call get_pod_status. A high restart_count with ready=false confirms a
   restart loop rather than a slow or pending start.
2. Call get_pod_logs. The container's own output names the failure; read it
   before forming a hypothesis.
3. Call get_pod_events. Events tell you what the kubelet observed, including
   the exit code, which separates an application failure from a kill.
4. Read contexture://runbooks/crash-loop-backoff and match the evidence you
   collected against its table of causes.

Then report the root cause and the single smallest next action.

Constraints:
- Do not recommend restarting or deleting the Pod before the cause is known.
  A restart does not repair a configuration error; it produces one more restart.
- Do not state any cluster state you have not read from a tool.
- Name the specific evidence, including the exit code, that supports your
  conclusion.\
"""


__all__ = ["DiagnoseCrashLoopBackOff"]
