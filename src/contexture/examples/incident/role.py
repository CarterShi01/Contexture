"""The roles a connecting agent discovers first.

Three roles rather than one, because a single role is the shape at which a
gateway surface is a bad trade: the whole point of keeping capabilities off the
wire is that a session pays only for the branch it enters, and a tree with one
branch has nothing to not pay for. Two specialisms under a coordinator is the
smallest arrangement where the disclosure model is doing visible work.

They are also two genuinely different kinds of work. Diagnosis reads; rollback
writes and destroys the evidence diagnosis depends on. That is what puts one
tool behind the writing door.
"""

from __future__ import annotations

from contexture import Role
from .documents import CrashLoopRunbook, RollbackPolicy
from .skills import DiagnoseCrashLoopBackOff, RollBackAFailedRelease
from .tools import (
    GetPodEvents,
    GetPodLogs,
    GetPodStatus,
    GetRolloutStatus,
    RollBackDeployment,
)


class IncidentResponse(Role):
    """Diagnose unhealthy Kubernetes workloads from cluster evidence."""

    instructions = """\
Work from evidence, never from the shape of the question. Select the skill that
matches the reported symptom, follow its procedure, and collect tool output
before naming a cause. Report the root cause and the smallest safe next action.
"""

    diagnose_crash_loop = DiagnoseCrashLoopBackOff

    pod_status = GetPodStatus
    pod_logs = GetPodLogs
    pod_events = GetPodEvents

    crash_loop_runbook = CrashLoopRunbook


class DeploymentOps(Role):
    """Inspect and reverse Kubernetes releases that have gone wrong."""

    instructions = """\
Remediation follows diagnosis and never replaces it. Read the policy, establish
what the previous revision would restore, and say what evidence a rollback
destroys before proposing one. Anything that changes the cluster is run through
contexture_invoke, where a host can put a human in front of it.
"""

    roll_back_release = RollBackAFailedRelease

    rollout_status = GetRolloutStatus
    roll_back = RollBackDeployment

    rollback_policy = RollbackPolicy


class KubernetesPlatform(Role):
    """Operate a Kubernetes platform: diagnose incidents, and reverse releases."""

    instructions = """\
Route to the specialism the task belongs to, and open only that one. Diagnose
before remediating: incident-response establishes a cause from evidence, and
deployment-ops reverses a release once the cause is known.
"""

    incidents = IncidentResponse
    deployments = DeploymentOps


__all__ = [
    "DeploymentOps",
    "IncidentResponse",
    "KubernetesPlatform",
]
