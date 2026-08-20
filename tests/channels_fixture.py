"""A server whose capabilities reach something outside their own process.

Launched as a subprocess by `test_channels.py`. It is written the way an
application with downstream connections is meant to be written, and the order
is the point: the connection is built first, handed to the registry, and only
then is anything registered against it.

The "connection" here is a dictionary rather than a socket. What is being
tested is that a capability reaches *the object the application built*, and a
real socket would only add a second thing that can fail.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from contexture import ControllerManager, Prompt, Resource, Role, Skill, Tool
from contexture.server import ContextureApp


@dataclass
class Gateway:
    """Stands in for a session against a remote MCP gateway."""

    endpoint: str
    calls: list[str] = field(default_factory=list)

    def call(self, name: str) -> str:
        self.calls.append(name)
        return f"{self.endpoint}:{name}#{len(self.calls)}"


@dataclass
class Channels:
    """Everything this application reaches outside its own process."""

    gateway: Gateway
    catalogue: dict[str, str]


class NotifySquad(Tool):
    """Notify the squad that owns a service, through the gateway."""

    name = "notify_squad"
    read_only = False

    async def invoke(self, squad: str) -> str:
        return self.channels.gateway.call(f"notify:{squad}")


class WhereAmI(Tool):
    """Report this capability's own address and what it can reach."""

    name = "where_am_i"
    read_only = True

    async def invoke(self) -> str:
        return f"{'/'.join(self.path)} -> {self.channels.gateway.endpoint}"


class Runbook(Tool):
    """The escalation runbook, as the gateway currently publishes it."""

    name = "runbook"
    read_only = True

    async def invoke(self) -> str:
        return self.channels.catalogue["runbook"]


class Escalate(Skill):
    """Escalate an incident to the squad that owns the service."""

    instructions = "1. Read the runbook. 2. Call notify_squad with the owner."


class Escalation(Role):
    """Reach the humans who own a failing service."""

    instructions = "Read the runbook before paging anyone."

    escalate = Escalate
    notify = NotifySquad
    where = WhereAmI
    runbook = Runbook


class Operations(Role):
    """Operate the platform."""

    instructions = "Route to the branch that owns the question."

    escalation = Escalation


PUBLISHED = (
    Resource(
        opens="operations/escalation/runbook",
        uri="contexture://runbooks/escalation",
        mime_type="text/markdown",
        description="How to escalate, as the gateway publishes it.",
    ),
    Prompt(
        opens="operations/escalation/escalate",
        description="Escalate an incident to the owning squad.",
    ),
)


def build() -> ContextureApp:
    """Build the app the way `main()` should read.

    Connections first, because a capability that cannot reach its downstream is
    not ready to be served; then the registry, which is what hands the handle to
    everything it registers; then the server.
    """

    channels = Channels(
        gateway=Gateway(endpoint="https://gateway.internal"),
        catalogue={"runbook": "Page the owner, then open an incident channel."},
    )
    manager = ControllerManager(channels=channels)
    manager.register(Operations)
    return ContextureApp(roots=manager, publish=PUBLISHED, name="channels-fixture")


app = build()


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    app.run(transport="stdio")
