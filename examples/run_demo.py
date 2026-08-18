"""Run the progressive compilation and MCP execution demonstration."""

from __future__ import annotations

import asyncio
import json

from role_runtime import (
    CapabilityDeniedError,
    CapabilitySelection,
    CompileRequest,
    ConfirmationRequired,
)

from examples.engineering_team import build_demo_environment


def _show(title: str, payload: object) -> None:
    print(f"\n=== {title} ===")
    if isinstance(payload, str):
        print(payload)
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))


async def main() -> None:
    environment = build_demo_environment()
    runtime = environment.runtime

    _show(
        "Root role: only child routes are visible",
        runtime.compile("engineering-team").to_dict(),
    )

    _show(
        "Troubleshooter: selected capabilities activated",
        runtime.compile(
            "engineering-team/k8s-troubleshooter",
            CompileRequest(
                selection=CapabilitySelection(
                    skill_names=("inspect-pod-failure",),
                    tool_refs=("production-kubernetes/get_pod_logs",),
                    resource_refs=(
                        "production-kubernetes/resource://kubernetes/runbook/incidents",
                    ),
                )
            ),
        ).to_dict(),
    )

    outcome = await runtime.call_tool(
        "engineering-team/k8s-troubleshooter",
        "production-kubernetes/get_pod_logs",
        {
            "namespace": "payments",
            "pod": "payment-service-7b9c8f6d5d-q2x7k",
            "container": "payment-service",
            "previous": True,
        },
    )
    _show("Authorized read-only tool call", outcome.raw)

    read = await runtime.read_resource(
        "engineering-team/k8s-troubleshooter",
        "production-kubernetes/resource://kubernetes/runbook/incidents",
    )
    _show("Authorized resource read (content loaded by Runtime)", read.text)

    try:
        await runtime.read_resource(
            "engineering-team/k8s-troubleshooter",
            "github-cloud/resource://github/payments-api/README.md",
        )
    except CapabilityDeniedError as exc:
        _show(
            "Cross-server denial: troubleshooter has no GitHub binding",
            f"CapabilityDeniedError: {exc}",
        )

    liaison_read = await runtime.read_resource(
        "engineering-team/github-liaison",
        "github-cloud/resource://github/payments-api/README.md",
    )
    _show("GitHub liaison reads its own repository resource", liaison_read.text)

    try:
        await runtime.call_tool(
            "engineering-team/github-liaison",
            "github-cloud/create_issue",
            {
                "repository": "payments/payments-api",
                "title": "payment-service CrashLoopBackOff",
                "body": "Connection refused in current logs; see runbook.",
            },
        )
    except ConfirmationRequired as exc:
        _show("Write tool blocked until approved", f"ConfirmationRequired: {exc}")

    approved = await runtime.call_tool(
        "engineering-team/github-liaison",
        "github-cloud/create_issue",
        {
            "repository": "payments/payments-api",
            "title": "payment-service CrashLoopBackOff",
            "body": "Connection refused in current logs; see runbook.",
        },
        approved=True,
    )
    _show("Approved write tool call", approved.raw)

    try:
        await runtime.call_tool(
            "engineering-team/k8s-troubleshooter",
            "production-kubernetes/delete_pod",
            {"namespace": "payments", "pod": "payment-service-1"},
        )
    except CapabilityDeniedError as exc:
        _show("Ungranted tool denied at the Runtime", f"CapabilityDeniedError: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
