"""The three read-only tools this responder can run.

Every tool states its parameters and its result as ordinary Python type hints.
Nothing here writes a JSON Schema, and nothing here imports the MCP SDK — the
schemas in `tools/list` are derived from these signatures when the role graph
is projected onto a server.
"""

from __future__ import annotations

from dataclasses import dataclass

from contexture import ContextureError
from contexture import Tool
from . import fixtures


# No slots: the SDK derives this tool's output schema from the return
# annotation, and a slotted dataclass exposes member descriptors that pydantic
# reads as unserializable defaults, silently dropping the structured result.
@dataclass
class PodStatus:
    """The current state of one Pod."""

    namespace: str
    pod: str
    phase: str
    container_state: str
    restart_count: int
    ready: bool
    image: str


@dataclass
class PodEvent:
    """One event the kubelet recorded about a Pod."""

    type: str
    reason: str
    message: str
    count: int


def _require_known_pod(namespace: str, pod: str) -> None:
    """Refuse anything the fixture does not cover, rather than inventing it.

    A demo that answers plausibly for a Pod it has never heard of teaches an
    agent that this server guesses. It is better to fail in a way that names
    what does exist.

    `ContextureError` rather than `NodeNotFoundError`: nothing here failed to
    *resolve* — the tool was found and ran. What it could not find is a Pod,
    which is this demo's own domain and not the tree's, and a lookup error
    carries facts about a ref rather than a sentence about a cluster.
    """

    if namespace == fixtures.NAMESPACE and pod == fixtures.POD:
        return
    raise ContextureError(
        f"No pod {pod!r} in namespace {namespace!r}. This demo serves a single "
        f"fixed incident: pod {fixtures.POD!r} in namespace "
        f"{fixtures.NAMESPACE!r}."
    )


class GetPodStatus(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="get_pod_status",
            description="Return the current phase, container state, and restart count of a Pod.",
            read_only=True,
        )

    async def invoke(self, namespace: str, pod: str) -> PodStatus:
        _require_known_pod(namespace, pod)
        return PodStatus(**fixtures.POD_STATUS)


class GetPodLogs(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="get_pod_logs",
            description="Return the recent container logs for a Pod.",
            read_only=True,
        )

    async def invoke(
        self,
        namespace: str,
        pod: str,
        previous: bool = False,
    ) -> str:
        """Read logs. Set `previous` to read the container's last run instead.

        The fixture's container fails identically on every attempt, so both
        runs return the same output — which is itself evidence that the failure
        is deterministic rather than a transient startup race.
        """

        _require_known_pod(namespace, pod)
        return fixtures.POD_LOGS


class GetPodEvents(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="get_pod_events",
            description="Return the Kubernetes events recorded against a Pod.",
            read_only=True,
        )

    async def invoke(self, namespace: str, pod: str) -> list[PodEvent]:
        _require_known_pod(namespace, pod)
        return [PodEvent(**event) for event in fixtures.POD_EVENTS]


@dataclass
class RolloutStatus:
    """Where one Deployment's rollout currently stands."""

    namespace: str
    deployment: str
    current_revision: int
    previous_revision: int
    current_image: str
    previous_image: str
    updated_replicas: int
    available_replicas: int
    rolled_out_at: str


def _require_known_deployment(namespace: str, deployment: str) -> None:
    if namespace == fixtures.NAMESPACE and deployment == fixtures.DEPLOYMENT:
        return
    raise ContextureError(
        f"No deployment {deployment!r} in namespace {namespace!r}. This demo "
        f"serves a single fixed incident: deployment {fixtures.DEPLOYMENT!r} "
        f"in namespace {fixtures.NAMESPACE!r}."
    )


class GetRolloutStatus(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="get_rollout_status",
            description="Return the current and previous revision of a Deployment's rollout.",
            read_only=True,
        )

    async def invoke(self, namespace: str, deployment: str) -> RolloutStatus:
        _require_known_deployment(namespace, deployment)
        return RolloutStatus(**fixtures.ROLLOUT_STATUS)


class RollBackDeployment(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="roll_back_deployment",
            description="Restore a Deployment's previous revision, replacing its running Pods.",
            read_only=False,
        )

    async def invoke(self, namespace: str, deployment: str) -> str:
        _require_known_deployment(namespace, deployment)
        status = fixtures.ROLLOUT_STATUS
        return (
            f"Rolled {namespace}/{deployment} back from revision "
            f"{status['current_revision']} to {status['previous_revision']} "
            f"({status['previous_image']}). The failing Pods have been replaced, "
            "so their logs and events are no longer available."
        )


__all__ = [
    "GetPodEvents",
    "GetPodLogs",
    "GetPodStatus",
    "GetRolloutStatus",
    "PodEvent",
    "PodStatus",
    "RollBackDeployment",
    "RolloutStatus",
]
