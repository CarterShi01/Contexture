"""An engineering team declared the way a business project would declare it.

Everything here is business vocabulary: a `K8sTroubleshooter` is a class, an
`InspectPodFailure` is a class, and the capabilities each may reach are stated
as class attributes. Nothing in this file names Claude Code, Codex, or Cursor —
that translation is a target adapter's job, and this declaration is what those
adapters consume.

The two MCP servers are served by `InMemoryHost`, so the tools and resources
the roles are granted are backed by real handlers rather than a hand-written
fake protocol server.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from contexture import (
    HTTPConnection,
    MCPBinding,
    MCPResource,
    MCPServer,
    MCPTool,
    Role,
    Skill,
    StdioConnection,
    ToolAnnotations,
)
from contexture.execution import RoleRuntime
from contexture.protocol import (
    InMemoryHost,
    InMemoryTransport,
    MCPClient,
    ResourceContents,
    ToolResult,
)

KUBERNETES_SERVER_ID = "production-kubernetes"
GITHUB_SERVER_ID = "github-cloud"

RUNBOOK_URI = "resource://kubernetes/runbook/incidents"
DEPLOYMENT_URI = "resource://kubernetes/deployment/payments-api"
REPO_README_URI = "resource://github/payments-api/README.md"


# ---------------------------------------------------------------------------
# Capabilities the business owns
# ---------------------------------------------------------------------------

GET_POD_LOGS = MCPTool(
    name="get_pod_logs",
    description="Read current or previous logs from a container inside a Pod.",
    input_schema={
        "type": "object",
        "properties": {
            "namespace": {
                "type": "string",
                "description": "The Kubernetes namespace.",
                "x-mcp-header": "Namespace",
            },
            "pod": {"type": "string", "description": "The Pod name."},
            "container": {"type": "string", "description": "The container name."},
            "previous": {"type": "boolean", "default": False},
        },
        "required": ["namespace", "pod", "container"],
        "additionalProperties": False,
    },
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False),
)

GET_EVENTS = MCPTool(
    name="get_events",
    description="Read Kubernetes events for a namespace or resource.",
    input_schema={
        "type": "object",
        "properties": {
            "namespace": {"type": "string"},
            "resource_name": {"type": "string"},
        },
        "required": ["namespace"],
        "additionalProperties": False,
    },
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False),
)

DELETE_POD = MCPTool(
    name="delete_pod",
    description="Delete one Pod and let its controller recreate it.",
    input_schema={
        "type": "object",
        "properties": {
            "namespace": {"type": "string"},
            "pod": {"type": "string"},
        },
        "required": ["namespace", "pod"],
        "additionalProperties": False,
    },
    annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True),
)

CREATE_ISSUE = MCPTool(
    name="create_issue",
    description="Open a new issue in a GitHub repository.",
    input_schema={
        "type": "object",
        "properties": {
            "repository": {
                "type": "string",
                "description": "The owner/name repository slug.",
                "x-mcp-header": "Repository",
            },
            "title": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["repository", "title", "body"],
        "additionalProperties": False,
    },
    annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True),
)

RUNBOOK = MCPResource(
    name="kubernetes-incident-runbook",
    description="Operational guidance for common Kubernetes incidents.",
    uri=RUNBOOK_URI,
    mime_type="text/markdown",
)

DEPLOYMENT = MCPResource(
    name="payments-api-deployment",
    description="The live Deployment manifest for the payments API.",
    uri=DEPLOYMENT_URI,
    mime_type="application/yaml",
)

REPO_README = MCPResource(
    name="payments-api-readme",
    description="Repository overview and ownership for the payments API.",
    uri=REPO_README_URI,
    mime_type="text/markdown",
)

KUBERNETES = MCPServer(
    server_id=KUBERNETES_SERVER_ID,
    name="kubernetes",
    description="Provides Kubernetes cluster inspection and operations.",
    tools=[GET_POD_LOGS, GET_EVENTS, DELETE_POD],
    resources=[RUNBOOK, DEPLOYMENT],
    connection=StdioConnection(
        command="npx",
        args=("-y", "@example/kubernetes-mcp"),
        env={"KUBECONFIG": "${KUBECONFIG}"},
    ),
)

GITHUB = MCPServer(
    server_id=GITHUB_SERVER_ID,
    name="github",
    description="Provides GitHub repository context and issue tracking.",
    tools=[CREATE_ISSUE],
    resources=[REPO_README],
    connection=HTTPConnection(
        url="https://mcp.example.com/github",
        headers={"Authorization": "Bearer ${GITHUB_MCP_TOKEN}"},
    ),
)


# ---------------------------------------------------------------------------
# Knowledge the business owns
# ---------------------------------------------------------------------------


class InspectPodFailure(Skill):
    """Diagnose why a Pod is crashing, restarting, or failing to become ready."""

    instructions = """
1. Identify the cluster, namespace, Pod, and container.
2. Inspect the Pod status and restart count.
3. Read current logs.
4. Read previous logs when a container has restarted.
5. Inspect relevant Kubernetes events.
6. Correlate status, logs, and events before proposing remediation.
""".strip()


class ReportIncident(Skill):
    """Turn a completed diagnosis into a tracked GitHub issue."""

    instructions = """
1. Summarize the symptom, the evidence, and the root cause.
2. Read the repository README to name the owning team.
3. Draft a title that states the failing component and the impact.
4. Obtain explicit approval before creating the issue.
""".strip()


# ---------------------------------------------------------------------------
# Roles the business owns
# ---------------------------------------------------------------------------


class K8sTroubleshooter(Role):
    """Diagnose unhealthy Pods, failed Deployments, and scheduling failures."""

    instructions = """
Start with read-only inspection. Select a diagnostic Skill, activate only the
required MCP Tool schemas, collect evidence, and explain the root cause before
recommending remediation. Do not modify cluster resources.
""".strip()

    inspect_failures = InspectPodFailure

    cluster = MCPBinding(
        server=KUBERNETES,
        allowed_tools=["get_pod_logs", "get_events"],
        read_only_tools=["get_pod_logs", "get_events"],
        allowed_resources=[RUNBOOK_URI, DEPLOYMENT_URI],
    )


class K8sOperator(Role):
    """Perform approved Kubernetes remediation, rollout, and restart operations."""

    instructions = """
Inspect before changing the cluster. Explain the intended effect, obtain explicit
approval for every write operation, execute the smallest safe change, and verify
the result.
""".strip()

    cluster = MCPBinding(
        server=KUBERNETES,
        allowed_tools=["get_pod_logs", "get_events", "delete_pod"],
        read_only_tools=["get_pod_logs", "get_events"],
        allowed_resources=[DEPLOYMENT_URI],
    )


class GithubLiaison(Role):
    """File and track GitHub issues once an incident has been diagnosed."""

    instructions = """
Read the repository context before writing. Never open an issue without an
explicit approval, and always include the evidence that motivated it.
""".strip()

    report = ReportIncident

    repository = MCPBinding(
        server=GITHUB,
        allowed_tools=["create_issue"],
        read_only_tools=[],
        allowed_resources=[REPO_README_URI],
    )


class EngineeringTeam(Role):
    """Coordinate Kubernetes and GitHub work across the specialists who own it."""

    instructions = """
Classify the request, select the most appropriate direct child Role, and avoid
loading specialist instructions or capability schemas until that Role is active.
""".strip()

    troubleshooter = K8sTroubleshooter
    operator = K8sOperator
    liaison = GithubLiaison


# ---------------------------------------------------------------------------
# Handlers behind the declared capabilities
# ---------------------------------------------------------------------------

RESOURCE_BODIES: dict[str, str] = {
    RUNBOOK_URI: (
        "# Kubernetes Incident Runbook\n\n"
        "For CrashLoopBackOff, inspect current logs, previous logs, events, "
        "probes, and configuration changes."
    ),
    DEPLOYMENT_URI: (
        "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n"
        "  name: payments-api\n  namespace: payments\nspec:\n  replicas: 3\n"
    ),
    REPO_README_URI: (
        "# payments-api\n\n"
        "Owned by the Payments Platform team. Page #payments-oncall for "
        "production incidents."
    ),
}


def _resource_provider(mime_type: str):
    async def provide(uri: str) -> ResourceContents:
        return ResourceContents(
            uri=uri, text=RESOURCE_BODIES[uri], mime_type=mime_type
        )

    return provide


async def _get_pod_logs(arguments: Mapping[str, Any]) -> ToolResult:
    return ToolResult.text(
        f"Logs for {arguments['namespace']}/{arguments['pod']} "
        f"container={arguments['container']}: connection refused"
    )


async def _get_events(arguments: Mapping[str, Any]) -> ToolResult:
    return ToolResult.text("Warning BackOff: restarting failed container")


async def _delete_pod(arguments: Mapping[str, Any]) -> ToolResult:
    return ToolResult.text(
        f"Deleted Pod {arguments['namespace']}/{arguments['pod']}"
    )


async def _create_issue(arguments: Mapping[str, Any]) -> ToolResult:
    return ToolResult.text(
        f"Opened {arguments['repository']}#421: {arguments['title']}"
    )


def build_kubernetes_host() -> InMemoryHost:
    """Bind the declared Kubernetes capabilities to the code behind them."""

    host = InMemoryHost()
    host.register_tool(GET_POD_LOGS, _get_pod_logs)
    host.register_tool(GET_EVENTS, _get_events)
    host.register_tool(DELETE_POD, _delete_pod)
    host.register_resource(RUNBOOK, _resource_provider("text/markdown"))
    host.register_resource(DEPLOYMENT, _resource_provider("application/yaml"))
    return host


def build_github_host() -> InMemoryHost:
    """Bind the declared GitHub capabilities to the code behind them."""

    host = InMemoryHost()
    host.register_tool(CREATE_ISSUE, _create_issue)
    host.register_resource(REPO_README, _resource_provider("text/markdown"))
    return host


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


@dataclass(slots=True, kw_only=True)
class DemoEnvironment:
    """Objects exposed to the demo and the tests."""

    runtime: RoleRuntime
    root_role: Role
    troubleshooter: Role
    operator: Role
    liaison: Role
    kubernetes_server: MCPServer
    github_server: MCPServer
    kubernetes_host: InMemoryHost
    github_host: InMemoryHost
    kubernetes_transport: InMemoryTransport
    github_transport: InMemoryTransport


def build_demo_environment() -> DemoEnvironment:
    """Instantiate the declared team and back it with in-process MCP hosts."""

    root = EngineeringTeam()
    troubleshooter, operator, liaison = root.children

    kubernetes_host = build_kubernetes_host()
    github_host = build_github_host()

    kubernetes_transport = InMemoryTransport(handler=kubernetes_host.handle)
    github_transport = InMemoryTransport(handler=github_host.handle)

    runtime = RoleRuntime(
        root_role=root,
        mcp_clients={
            KUBERNETES_SERVER_ID: MCPClient(transport=kubernetes_transport),
            GITHUB_SERVER_ID: MCPClient(transport=github_transport),
        },
    )

    return DemoEnvironment(
        runtime=runtime,
        root_role=root,
        troubleshooter=troubleshooter,
        operator=operator,
        liaison=liaison,
        kubernetes_server=KUBERNETES,
        github_server=GITHUB,
        kubernetes_host=kubernetes_host,
        github_host=github_host,
        kubernetes_transport=kubernetes_transport,
        github_transport=github_transport,
    )
