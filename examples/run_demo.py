"""Run the progressive compilation and MCP execution demonstration."""

from __future__ import annotations

import asyncio
import json

from role_runtime import CapabilitySelection, CompileRequest

from examples.kubernetes_team import build_demo_environment


async def main() -> None:
    environment = build_demo_environment()
    runtime = environment.runtime

    print("=== Root role: active surface ===")
    root_context = runtime.compile("k8s-team").to_dict()
    print(json.dumps(root_context, indent=2, ensure_ascii=False))

    print("\n=== Troubleshooter: selected capabilities activated ===")
    specialist_context = runtime.compile(
        "k8s-team/k8s-troubleshooter",
        CompileRequest(
            selection=CapabilitySelection(
                skill_names=("inspect-pod-failure",),
                tool_refs=("production-kubernetes/get_pod_logs",),
                data_refs=("runbook/kubernetes-incidents",),
            )
        ),
    ).to_dict()
    print(json.dumps(specialist_context, indent=2, ensure_ascii=False))

    print("\n=== Authorized read-only MCP tool call ===")
    outcome = await runtime.call_tool(
        "k8s-team/k8s-troubleshooter",
        "production-kubernetes/get_pod_logs",
        {
            "namespace": "payments",
            "pod": "payment-service-7b9c8f6d5d-q2x7k",
            "container": "payment-service",
            "previous": True,
        },
    )
    print(json.dumps(outcome.raw, indent=2, ensure_ascii=False))

    print("\n=== Authorized data read ===")
    data = await runtime.read_data(
        "k8s-team/k8s-troubleshooter",
        "runbook/kubernetes-incidents",
    )
    print(data.content)


if __name__ == "__main__":
    asyncio.run(main())
