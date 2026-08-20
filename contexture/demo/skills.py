"""The procedure that turns three tools into a diagnosis.

These instructions are the payload progressive disclosure exists to defer. They
are never in the bootstrap text and never on a routing card; an agent receives
them only after calling contexture_open on this skill's ref.
"""

from __future__ import annotations

from contexture import Skill


class DiagnoseCrashLoopBackOff(Skill):
    def __init__(self) -> None:
        super().__init__(
            name="diagnose-crash-loop-backoff",
            description="Find why a Pod restarts repeatedly, before proposing any remediation.",
            instructions="""\
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
""",
        )


class RollBackAFailedRelease(Skill):
    def __init__(self) -> None:
        super().__init__(
            name="roll-back-a-failed-release",
            description="Decide whether to roll a release back, and what to capture first.",
            instructions="""\
A rollback destroys the evidence it was called for. Work in this order.

1. Read contexture://runbooks/rollback-policy before doing anything else.
2. Call get_rollout_status. Compare the current and previous image: if they
   differ only in a tag, the cause may not be in the image at all.
3. Establish the cause first, using the incident-response role. A rollback that
   follows a guess will be needed again on the next release.
4. Only then call roll_back_deployment, and say plainly what evidence is lost.

Constraints:
- Do not roll back before the cause is known and the evidence is captured.
- A configuration fault follows the previous revision back. Say so rather than
  presenting a rollback as a fix.
- roll_back_deployment changes the cluster. It is not read-only, so it must be
  run through contexture_invoke and a human may be asked first.\
""",
        )


__all__ = ["DiagnoseCrashLoopBackOff", "RollBackAFailedRelease"]
