"""Walk one declaration through every layer Contexture provides.

The point of the walk is that the declaration in `engineering_team.py` is
written once and never mentions an agent runtime, yet it produces a Claude Code
surface, a Codex surface, a Cursor surface, a progressively disclosed context,
and an authorization boundary.
"""

from __future__ import annotations

import asyncio
import json
import tempfile

from contexture import (
    CapabilityDeniedError,
    CapabilitySelection,
    CompileRequest,
    ConfirmationRequired,
)
from contexture.targets import all_adapters, plan, render_all

from examples.engineering_team import (
    REPO_README_URI,
    RUNBOOK_URI,
    EngineeringTeam,
    build_demo_environment,
)

RULE = "=" * 72


def _section(title: str) -> None:
    print(f"\n{RULE}\n{title}\n{RULE}")


def _show(title: str, payload: object) -> None:
    print(f"\n--- {title} ---")
    if isinstance(payload, str):
        print(payload)
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))


def show_declaration() -> None:
    _section("1. What the business declared")

    declaration = EngineeringTeam.declaration
    assert declaration is not None
    print(f"\nclass {declaration.owner} -> role {declaration.name!r}")
    print(f"description: {declaration.description}")
    print("\nmembers declared in the class body:")
    for member in declaration.members:
        kind = type(member.value).__name__
        print(f"  {member.attribute:<16} {kind:<12} (from {member.declared_by})")


def show_targets() -> None:
    _section("2. The same declaration, rendered for three agent runtimes")

    root = EngineeringTeam()
    surfaces = render_all(root, all_adapters())

    for name, rendered in surfaces.items():
        print(f"\n{name}  ({len(rendered)} artifacts, digest {rendered.digest[:12]})")
        for path in rendered.paths:
            print(f"    {path}")
        for note in rendered.notes:
            print(f"    ! {note}")

    _show(
        "Claude Code CLAUDE.md",
        surfaces["claude-code"].get("CLAUDE.md").content,
    )
    _show(
        "Claude Code .mcp.json",
        surfaces["claude-code"].get(".mcp.json").content,
    )

    with tempfile.TemporaryDirectory() as directory:
        computed = plan(surfaces["claude-code"], directory)
        print(f"\ninstall plan against an empty tree: {computed.summary()}")


def show_progressive_disclosure() -> None:
    _section("3. Progressive disclosure over the same objects")

    runtime = build_demo_environment().runtime

    _show(
        "Root role: children are route cards only",
        runtime.compile("engineering-team").to_dict(),
    )
    _show(
        "Troubleshooter with two capabilities activated",
        runtime.compile(
            "engineering-team/k8s-troubleshooter",
            CompileRequest(
                selection=CapabilitySelection(
                    skill_names=("inspect-pod-failure",),
                    tool_refs=("production-kubernetes/get_pod_logs",),
                    resource_refs=(f"production-kubernetes/{RUNBOOK_URI}",),
                )
            ),
        ).to_dict()["activated_capabilities"],
    )


async def show_execution() -> None:
    _section("4. Execution, checked against the same grants")

    runtime = build_demo_environment().runtime

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
    _show("Granted read-only tool call", outcome.content[0]["text"])

    read = await runtime.read_resource(
        "engineering-team/k8s-troubleshooter",
        f"production-kubernetes/{RUNBOOK_URI}",
    )
    _show("Granted resource read (content arrives only here)", read.text)

    try:
        await runtime.read_resource(
            "engineering-team/k8s-troubleshooter",
            f"github-cloud/{REPO_README_URI}",
        )
    except CapabilityDeniedError as exc:
        _show("Cross-server denial", f"CapabilityDeniedError: {exc}")

    try:
        await runtime.call_tool(
            "engineering-team/k8s-operator",
            "production-kubernetes/delete_pod",
            {"namespace": "payments", "pod": "payment-service-1"},
        )
    except ConfirmationRequired as exc:
        _show("Write tool held for approval", f"ConfirmationRequired: {exc}")

    approved = await runtime.call_tool(
        "engineering-team/k8s-operator",
        "production-kubernetes/delete_pod",
        {"namespace": "payments", "pod": "payment-service-1"},
        approved=True,
    )
    _show("Approved write tool call", approved.content[0]["text"])

    try:
        await runtime.call_tool(
            "engineering-team/k8s-troubleshooter",
            "production-kubernetes/delete_pod",
            {"namespace": "payments", "pod": "payment-service-1"},
            approved=True,
        )
    except CapabilityDeniedError as exc:
        _show("Ungranted tool denied even when approved", f"{exc}")


async def main() -> None:
    show_declaration()
    show_targets()
    show_progressive_disclosure()
    await show_execution()


if __name__ == "__main__":
    asyncio.run(main())
