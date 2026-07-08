#!/usr/bin/env python3
"""Build a branch-protection and auto-merge guardrail packet."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence


RECOMMENDED_CHECK_ORDER = (
    "pr-contract",
    "Unit tests (not pg)",
    "import-linter",
    "smoke",
    "smoke-docker",
    "CodeQL",
)


@dataclass(frozen=True)
class ObservedCheck:
    name: str
    workflow_name: str
    conclusion: str | None


@dataclass(frozen=True)
class GuardrailPacket:
    branch: str
    branch_protection_active: bool
    repo_auto_merge_allowed: bool
    required_checks_selected: list[str]
    observed_check_evidence: list[ObservedCheck]
    no_pr_merged: bool
    no_existing_pr_auto_merge_enabled: bool
    human_exception_required: bool
    unresolved_blockers: list[str]
    exact_admin_settings_required: list[str]


def _load_json(path: Path | None, default: object) -> object:
    if path is None:
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _protection_active(protection: dict[str, object], status: int) -> bool:
    return status == 200 and bool(protection)


def _repo_auto_merge(repo: dict[str, object]) -> bool:
    return repo.get("allow_auto_merge") is True


def _observed_checks(check_runs_payload: object) -> list[ObservedCheck]:
    payload = _as_dict(check_runs_payload)
    raw_checks = payload.get("check_runs", check_runs_payload)
    checks: list[ObservedCheck] = []
    for item in _as_list(raw_checks):
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        workflow = item.get("workflow_name") or item.get("workflowName")
        conclusion = item.get("conclusion")
        checks.append(
            ObservedCheck(
                name=name if isinstance(name, str) else "unknown",
                workflow_name=workflow if isinstance(workflow, str) else "unknown",
                conclusion=conclusion if isinstance(conclusion, str) else None,
            )
        )
    return sorted(checks, key=lambda check: (check.name, check.workflow_name))


def _recommended_required_checks(observed: list[ObservedCheck]) -> list[str]:
    observed_names = {check.name for check in observed}
    return [name for name in RECOMMENDED_CHECK_ORDER if name in observed_names]


def _blockers(
    *,
    branch_protection_active: bool,
    auto_merge_allowed: bool,
    selected_checks: list[str],
) -> list[str]:
    blockers: list[str] = []
    if not branch_protection_active:
        blockers.append("main branch protection is not active")
    if not auto_merge_allowed:
        blockers.append("repository auto-merge is disabled")
    missing = [name for name in RECOMMENDED_CHECK_ORDER if name not in selected_checks]
    if missing:
        blockers.append("recommended checks lack observed evidence: " + ", ".join(missing))
    return blockers


def _admin_settings(selected_checks: list[str]) -> list[str]:
    checks = ", ".join(selected_checks) if selected_checks else "<observed required checks>"
    return [
        "Protect `main` with required status checks and strict up-to-date branches.",
        f"Set required status checks for `main`: {checks}.",
        "Require pull request before merge with 0 required approvals; do not require routine human review.",
        "Disable force pushes on `main`.",
        "Disable branch deletion for `main`.",
        "Enable repository auto-merge only after `main` protection is active.",
        "Do not enable auto-merge on any existing pull request.",
    ]


def build_packet(
    *,
    repo: dict[str, object],
    main_protection: dict[str, object],
    main_protection_status: int,
    check_runs_payload: object,
    branch: str = "main",
) -> GuardrailPacket:
    active = _protection_active(main_protection, main_protection_status)
    auto_merge = _repo_auto_merge(repo)
    observed = _observed_checks(check_runs_payload)
    selected = _recommended_required_checks(observed)
    blockers = _blockers(
        branch_protection_active=active,
        auto_merge_allowed=auto_merge,
        selected_checks=selected,
    )
    return GuardrailPacket(
        branch=branch,
        branch_protection_active=active,
        repo_auto_merge_allowed=auto_merge,
        required_checks_selected=selected,
        observed_check_evidence=observed,
        no_pr_merged=True,
        no_existing_pr_auto_merge_enabled=True,
        human_exception_required=bool(blockers),
        unresolved_blockers=blockers,
        exact_admin_settings_required=_admin_settings(selected) if blockers else [],
    )


def render_markdown(packet: GuardrailPacket) -> str:
    checks = "\n".join(f"- `{name}`" for name in packet.required_checks_selected) or "- unknown"
    observed = (
        "\n".join(
            f"- `{check.name}` from `{check.workflow_name}`: {check.conclusion or 'unknown'}"
            for check in packet.observed_check_evidence
        )
        or "- none"
    )
    blockers = "\n".join(f"- {item}" for item in packet.unresolved_blockers) or "- none"
    settings = (
        "\n".join(f"- {item}" for item in packet.exact_admin_settings_required) or "- none"
    )
    return "\n".join(
        [
            "# Branch Guardrail Packet",
            "",
            f"- Branch: `{packet.branch}`",
            f"- Branch protection active: `{packet.branch_protection_active}`",
            f"- Repo auto-merge allowed: `{packet.repo_auto_merge_allowed}`",
            f"- No PR merged by this packet: `{packet.no_pr_merged}`",
            f"- No existing PR auto-merge enabled: `{packet.no_existing_pr_auto_merge_enabled}`",
            f"- Human exception required: `{packet.human_exception_required}`",
            "",
            "## Required Checks Selected",
            "",
            checks,
            "",
            "## Observed Check Evidence",
            "",
            observed,
            "",
            "## Unresolved Blockers",
            "",
            blockers,
            "",
            "## Exact Admin Settings Required",
            "",
            settings,
            "",
        ]
    )


def _write_outputs(packet: GuardrailPacket, json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(asdict(packet), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(packet), encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-json", type=Path, required=True)
    parser.add_argument("--main-protection-json", type=Path)
    parser.add_argument("--main-protection-status", type=int, default=404)
    parser.add_argument("--check-runs-json", type=Path, required=True)
    parser.add_argument("--branch", default="main")
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    packet = build_packet(
        repo=_as_dict(_load_json(args.repo_json, {})),
        main_protection=_as_dict(_load_json(args.main_protection_json, {})),
        main_protection_status=args.main_protection_status,
        check_runs_payload=_load_json(args.check_runs_json, {}),
        branch=args.branch,
    )
    _write_outputs(packet, args.output_json, args.output_markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
