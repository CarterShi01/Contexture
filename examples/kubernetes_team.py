"""A complete Kubernetes team built from the reference object model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from role_runtime import (
    DataAccess,
    DataBinding,
    DataClassification,
    DataSource,
    InMemoryDataProvider,
    InMemoryTransport,
    MCPBinding,
    MCPClient,
    MCPServer,
    MCPTool,
    Role,
    RoleRuntime,
    Skill,
    ToolAnnotations,
)


@dataclass(slots=True, kw_only=True)
class DemoEnvironment:
    """Objects exposed to examples and tests."""

    runtime: RoleRuntime
    root_role: Role
    troubleshooter: Role
    operator: Role
    server: MCPServer
    transport: InMemoryTransport


def build_demo_environment() -> DemoEnvironment:
    """Build a runnable team with shared MCP and data infrastructure."""

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
        description="Delete one Kubernetes Pod and allow its controller to recreate it.",
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

    kubernetes_server = MCPServer(
        server_id="production-kubernetes",
        name="kubernetes",
        description="Provides Kubernetes cluster inspection and operations.",
        tools=[get_pod_logs, get_events, delete_pod],
    )

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

    runbook_source = DataSource(
        name="kubernetes-incident-runbook",
        description="Operational guidance for common Kubernetes incidents.",
        source_id="runbook/kubernetes-incidents",
        uri="memory://runbooks/kubernetes-incidents",
        provider_id="memory",
        media_type="text/markdown",
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
            )
        ],
        data_bindings=[
            DataBinding(
                source=runbook_source,
                access=DataAccess.READ,
                classification=DataClassification.INTERNAL,
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
            )
        ],
    )

    root = Role(
        name="k8s-team",
        description=(
            "Coordinate Kubernetes work and route each request to the most "
            "appropriate specialist."
        ),
        instructions="""
Classify the request, select the most appropriate direct child Role, and avoid
loading specialist instructions or capability schemas until that Role is active.
""".strip(),
        children=[troubleshooter, operator],
    )

    transport = InMemoryTransport(
        handler=_build_demo_mcp_handler(kubernetes_server)
    )
    client = MCPClient(transport=transport)
    provider = InMemoryDataProvider(
        values={
            runbook_source.uri: (
                "# Kubernetes Incident Runbook\n\n"
                "For CrashLoopBackOff, inspect current logs, previous logs, "
                "events, probes, and configuration changes."
            )
        }
    )
    runtime = RoleRuntime(
        root_role=root,
        mcp_clients={kubernetes_server.server_id: client},
        data_providers={"memory": provider},
    )

    return DemoEnvironment(
        runtime=runtime,
        root_role=root,
        troubleshooter=troubleshooter,
        operator=operator,
        server=kubernetes_server,
        transport=transport,
    )


def _build_demo_mcp_handler(server: MCPServer):
    async def handler(
        payload: dict[str, Any],
        headers: Mapping[str, str],
    ) -> dict[str, Any]:
        request_id = payload["id"]
        method = payload["method"]
        params = payload.get("params", {})

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "resultType": "complete",
                    "tools": [tool.to_protocol_dict() for tool in server.tools],
                    "ttlMs": 300_000,
                    "cacheScope": "private",
                },
            }

        if method != "tools/call":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": "Method not found",
                },
            }

        tool_name = params["name"]
        arguments = params.get("arguments", {})

        if tool_name == "get_pod_logs":
            text = (
                f"Logs for {arguments['namespace']}/{arguments['pod']} "
                f"container={arguments['container']}: connection refused"
            )
            return _tool_result(request_id, text)

        if tool_name == "get_events":
            return _tool_result(
                request_id,
                "Warning BackOff: restarting failed container",
            )

        if tool_name == "delete_pod":
            return _tool_result(
                request_id,
                f"Deleted Pod {arguments['namespace']}/{arguments['pod']}",
            )

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32602,
                "message": "Unknown tool",
            },
        }

    return handler


def _tool_result(request_id: Any, text: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "resultType": "complete",
            "content": [{"type": "text", "text": text}],
            "isError": False,
        },
    }
