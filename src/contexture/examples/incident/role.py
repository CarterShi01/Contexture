"""The role a connecting agent discovers first."""

from __future__ import annotations

from ...core.role import Role
from .resources import CrashLoopRunbook
from .skills import DiagnoseCrashLoopBackOff
from .tools import GetPodEvents, GetPodLogs, GetPodStatus


class KubernetesIncidentResponder(Role):
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


__all__ = ["KubernetesIncidentResponder"]
