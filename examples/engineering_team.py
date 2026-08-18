"""A two-server engineering team built from the reference object model.

The team spans two independent MCP servers so that least-privilege grants,
host-side tool references, and resource authorization can all be demonstrated
across a boundary that a single-server example cannot show.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from role_runtime import (
    InMemoryTransport,
    MCPBinding,
    MCPClient,
    MCPResource,
    MCPServer,
    MCPTool,
    Role,
    RoleRuntime,
    Skill,
    ToolAnnotations,
)

KUBERNETES_SERVER_ID = "production-kubernetes"
GITHUB_SERVER_ID = "github-cloud"

RUNBOOK_URI = "resource://kubernetes/runbook/incidents"
DEPLOYMENT_URI = "resource://kubernetes/deployment/payments-api"
REPO_README_URI = "resource://github/payments-api/README.md"


@dataclass(slots=True, kw_only=True)
class DemoEnvironment:
    """Objects exposed to examples and tests."""

    runtime: RoleRuntime
    root_role: Role
    troubleshooter: Role
    operator: Role
    liaison: Role
    kubernetes_server: MCPServer
    github_server: MCPServer
    kubernetes_transport: InMemoryTransport
    github_transport: InMemoryTransport


def build_demo_environment() -> DemoEnvironment:
    """Build a runnable team bound to two independent MCP servers."""

    kubernetes_server, kubernetes_contents = _build_kubernetes_server()
    github_server, github_contents = _build_github_server()

    inspect_pod_failure = Skill(
        name="inspect-pod-failure",
        description=(
            "Diagnose why a Kubernetes Pod is crashing, restarting, or failing "
            "to become ready."
        ),
        instructions="""
1. Identify the cluster, namespace, Pod, and container.
2. Inspect the Pod status and restart count.
3. Read current logs.
4. Read previous logs when a container has restarted.
5. Inspect relevant Kubernetes events.
6. Correlate status, logs, and events before proposing remediation.
""".strip(),
    )

    report_incident = Skill(
        name="report-incident",
        description="Turn a completed diagnosis into a tracked GitHub issue.",
        instructions="""
1. Summarize the symptom, the evidence, and the root cause.
2. Read the repository README to name the owning team.
3. Draft a title that states the failing component and the impact.
4. Obtain explicit approval before creating the issue.
""".strip(),
    )

    troubleshooter = Role(
        name="k8s-troubleshooter",
        description=(
            "Diagnose unhealthy Pods, failed Deployments, CrashLoopBackOff, "
            "scheduling failures, and runtime errors."
        ),
        instructions="""
Start with read-only inspection. Select a diagnostic Skill, activate only the
required MCP Tool schemas, collect evidence, and explain the root cause before
recommending remediation. Do not modify cluster resources.
""".strip(),
        skills=[inspect_pod_failure],
        mcp_bindings=[
            MCPBinding(
                server=kubernetes_server,
                allowed_tools=["get_pod_logs", "get_events"],
                read_only_tools=["get_pod_logs", "get_events"],
                allowed_resources=[RUNBOOK_URI, DEPLOYMENT_URI],
            )
        ],
    )

    operator = Role(
        name="k8s-operator",
        description=(
            "Perform approved Kubernetes remediation, rollout, restart, and "
            "resource-management operations."
        ),
        instructions="""
Inspect before changing the cluster. Explain the intended effect, obtain explicit
approval for every write operation, execute the smallest safe change, and verify
the result.
""".strip(),
        mcp_bindings=[
            MCPBinding(
                server=kubernetes_server,
                allowed_tools=["get_pod_logs", "get_events", "delete_pod"],
                read_only_tools=["get_pod_logs", "get_events"],
                allowed_resources=[DEPLOYMENT_URI],
            )
        ],
    )

    liaison = Role(
        name="github-liaison",
        description=(
            "File and track GitHub issues once an incident has been diagnosed."
        ),
        instructions="""
Read the repository context before writing. Never open an issue without an
explicit approval, and always include the evidence that motivated it.
""".strip(),
        skills=[report_incident],
        mcp_bindings=[
            MCPBinding(
                server=github_server,
                allowed_tools=["create_issue"],
                read_only_tools=[],
                allowed_resources=[REPO_README_URI],
            )
        ],
    )

    root = Role(
        name="engineering-team",
        description=(
            "Coordinate Kubernetes and GitHub work and route each request to "
            "the most appropriate specialist."
        ),
        instructions="""
Classify the request, select the most appropriate direct child Role, and avoid
loading specialist instructions or capability schemas until that Role is active.
""".strip(),
        children=[troubleshooter, operator, liaison],
    )

    kubernetes_transport = InMemoryTransport(
        handler=_build_mcp_handler(
            server=kubernetes_server,
            tool_handlers=_kubernetes_tool_handlers(),
            resource_contents=kubernetes_contents,
        )
    )
    github_transport = InMemoryTransport(
        handler=_build_mcp_handler(
            server=github_server,
            tool_handlers=_github_tool_handlers(),
            resource_contents=github_contents,
        )
    )

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
        kubernetes_server=kubernetes_server,
        github_server=github_server,
        kubernetes_transport=kubernetes_transport,
        github_transport=github_transport,
    )


def _build_kubernetes_server() -> tuple[MCPServer, dict[str, tuple[str, str]]]:
    get_pod_logs = MCPTool(
        name="get_pod_logs",
        description=(
            "Read current or previous logs from a container inside a "
            "Kubernetes Pod."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "The Kubernetes namespace.",
                    "x-mcp-header": "Namespace",
                },
                "pod": {
                    "type": "string",
                    "description": "The Pod name.",
                },
                "container": {
                    "type": "string",
                    "description": "The container name.",
                },
                "previous": {
                    "type": "boolean",
                    "default": False,
                },
            },
            "required": ["namespace", "pod", "container"],
            "additionalProperties": False,
        },
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )

    get_events = MCPTool(
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
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )

    delete_pod = MCPTool(
        name="delete_pod",
        description=(
            "Delete one Kubernetes Pod and allow its controller to recreate it."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "namespace": {"type": "string"},
                "pod": {"type": "string"},
            },
            "required": ["namespace", "pod"],
            "additionalProperties": False,
        },
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )

    runbook = MCPResource(
        name="kubernetes-incident-runbook",
        description="Operational guidance for common Kubernetes incidents.",
        uri=RUNBOOK_URI,
        mime_type="text/markdown",
    )

    deployment = MCPResource(
        name="payments-api-deployment",
        description="The live Deployment manifest for the payments API.",
        uri=DEPLOYMENT_URI,
        mime_type="application/yaml",
    )

    server = MCPServer(
        server_id=KUBERNETES_SERVER_ID,
        name="kubernetes",
        description="Provides Kubernetes cluster inspection and operations.",
        tools=[get_pod_logs, get_events, delete_pod],
        resources=[runbook, deployment],
    )

    contents = {
        RUNBOOK_URI: (
            "text/markdown",
            "# Kubernetes Incident Runbook\n\n"
            "For CrashLoopBackOff, inspect current logs, previous logs, "
            "events, probes, and configuration changes.",
        ),
        DEPLOYMENT_URI: (
            "application/yaml",
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: payments-api\n"
            "  namespace: payments\n"
            "spec:\n"
            "  replicas: 3\n",
        ),
    }
    return server, contents


def _build_github_server() -> tuple[MCPServer, dict[str, tuple[str, str]]]:
    create_issue = MCPTool(
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
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=True,
        ),
    )

    readme = MCPResource(
        name="payments-api-readme",
        description="Repository overview and ownership for the payments API.",
        uri=REPO_README_URI,
        mime_type="text/markdown",
    )

    server = MCPServer(
        server_id=GITHUB_SERVER_ID,
        name="github",
        description="Provides GitHub repository context and issue tracking.",
        tools=[create_issue],
        resources=[readme],
    )

    contents = {
        REPO_README_URI: (
            "text/markdown",
            "# payments-api\n\n"
            "Owned by the Payments Platform team. Page #payments-oncall for "
            "production incidents.",
        ),
    }
    return server, contents


ToolHandler = Callable[[Mapping[str, Any]], str]


def _kubernetes_tool_handlers() -> dict[str, ToolHandler]:
    return {
        "get_pod_logs": lambda arguments: (
            f"Logs for {arguments['namespace']}/{arguments['pod']} "
            f"container={arguments['container']}: connection refused"
        ),
        "get_events": lambda arguments: (
            "Warning BackOff: restarting failed container"
        ),
        "delete_pod": lambda arguments: (
            f"Deleted Pod {arguments['namespace']}/{arguments['pod']}"
        ),
    }


def _github_tool_handlers() -> dict[str, ToolHandler]:
    return {
        "create_issue": lambda arguments: (
            f"Opened {arguments['repository']}#421: {arguments['title']}"
        ),
    }


def _build_mcp_handler(
    *,
    server: MCPServer,
    tool_handlers: Mapping[str, ToolHandler],
    resource_contents: Mapping[str, tuple[str, str]],
):
    """Build an in-memory MCP server that serves tools and resources."""

    async def handler(
        payload: dict[str, Any],
        headers: Mapping[str, str],
    ) -> dict[str, Any]:
        request_id = payload["id"]
        method = payload["method"]
        params = payload.get("params", {})

        if method == "tools/list":
            return _result(
                request_id,
                {
                    "resultType": "complete",
                    "tools": [tool.to_protocol_dict() for tool in server.tools],
                    "ttlMs": 300_000,
                    "cacheScope": "private",
                },
            )

        if method == "resources/list":
            return _result(
                request_id,
                {
                    "resources": [
                        resource.to_protocol_dict() for resource in server.resources
                    ],
                    "ttlMs": 300_000,
                    "cacheScope": "private",
                },
            )

        if method == "resources/read":
            uri = params["uri"]
            if uri not in resource_contents:
                return _error(request_id, -32602, "Unknown resource")
            mime_type, text = resource_contents[uri]
            return _result(
                request_id,
                {
                    "contents": [
                        {"uri": uri, "mimeType": mime_type, "text": text},
                    ]
                },
            )

        if method != "tools/call":
            return _error(request_id, -32601, "Method not found")

        tool_name = params["name"]
        implementation = tool_handlers.get(tool_name)
        if implementation is None:
            return _error(request_id, -32602, "Unknown tool")

        return _result(
            request_id,
            {
                "resultType": "complete",
                "content": [
                    {
                        "type": "text",
                        "text": implementation(params.get("arguments", {})),
                    }
                ],
                "isError": False,
            },
        )

    return handler


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }
