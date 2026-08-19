"""The three read-only tools this responder can run.

Every tool states its parameters and its result as ordinary Python type hints.
Nothing here writes a JSON Schema, and nothing here imports the MCP SDK — the
schemas in `tools/list` are derived from these signatures when the role graph
is projected onto a server.
"""

from __future__ import annotations

from dataclasses import dataclass

from contexture import NodeNotFoundError
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
    """

    if namespace == fixtures.NAMESPACE and pod == fixtures.POD:
        return
    raise NodeNotFoundError(
        f"No pod {pod!r} in namespace {namespace!r}. This demo serves a single "
        f"fixed incident: pod {fixtures.POD!r} in namespace "
        f"{fixtures.NAMESPACE!r}."
    )


class GetPodStatus(Tool):
    """Return the current phase, container state, and restart count of a Pod."""

    name = "get_pod_status"
    read_only = True

    async def invoke(self, namespace: str, pod: str) -> PodStatus:
        _require_known_pod(namespace, pod)
        return PodStatus(**fixtures.POD_STATUS)


class GetPodLogs(Tool):
    """Return the recent container logs for a Pod."""

    name = "get_pod_logs"
    read_only = True

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
    """Return the Kubernetes events recorded against a Pod."""

    name = "get_pod_events"
    read_only = True

    async def invoke(self, namespace: str, pod: str) -> list[PodEvent]:
        _require_known_pod(namespace, pod)
        return [PodEvent(**event) for event in fixtures.POD_EVENTS]


__all__ = [
    "GetPodEvents",
    "GetPodLogs",
    "GetPodStatus",
    "PodEvent",
    "PodStatus",
]
