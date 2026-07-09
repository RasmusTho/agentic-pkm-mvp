"""Runtime-neutral dispatch planning for deliver-issue-set epic runs."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from app.builderops.epic_run_state import validate_run_id

SCHEMA_VERSION = 1
DEFAULT_MAX_PARALLEL = 2
VALID_PATHS = {"inline", "script", "subagent", "skip"}

HANDOFF_RECEIPT_SCHEMA: dict[str, Any] = {
    "schema_name": "subagent_handoff_receipt",
    "required_fields": [
        "role",
        "task",
        "skill_loaded",
        "branch",
        "worktree",
        "actions",
        "ac_verdicts",
        "lifecycle_mutations",
        "validation",
        "owner_doc_result",
        "residual_risk",
        "final_state",
        "next_step",
    ],
}


class EpicDispatchError(ValueError):
    """Raised when dispatch planning input is invalid or unsafe."""


def build_dispatch_plan(
    *,
    epic_issue_number: int,
    run_id: str,
    candidates: Iterable[Mapping[str, Any]],
    max_parallel: int = DEFAULT_MAX_PARALLEL,
    runtime_targets: Iterable[str] = ("codex", "claude"),
    active_leases: Iterable[int | str | Mapping[str, Any]] = (),
    run_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a dry-run worker dispatch plan without external mutations.

    The returned plan is deterministic JSON data. It never claims issues, writes
    GitHub state, starts sub-agents, or creates worktrees. If the caller wants to
    persist the launch decisions, feed ``epic_run_state_update`` to the existing
    ``epic-run-state record`` command.
    """

    normalized_run_id = validate_run_id(run_id)
    normalized_epic = _normalize_positive_int(epic_issue_number, "epic_issue_number")
    normalized_max = _normalize_positive_int(max_parallel, "max_parallel")
    runtimes = _normalize_runtime_targets(runtime_targets)
    lease_issues = _normalize_active_leases(active_leases)
    normalized_candidates = [_normalize_candidate(item) for item in candidates]
    run_state_seen = run_state is not None
    if run_state is not None:
        _validate_run_state_owner(
            run_state,
            epic_issue_number=normalized_epic,
            run_id=normalized_run_id,
        )

    decisions: list[dict[str, Any]] = []
    context_packs: list[dict[str, Any]] = []
    selected_files: set[str] = set()
    selected_owner_docs: set[str] = set()
    selected_validation_resources: set[str] = set()
    selected_count = 0

    for index, candidate in enumerate(normalized_candidates):
        decision = _build_tcd_decision(candidate, runtimes, lease_issues)
        selected_for_dispatch = False
        context_pack_id = None

        if decision["selected_path"] == "subagent" and decision["skip_reason"] is None:
            skip_reason = _parallel_skip_reason(
                candidate,
                selected_count=selected_count,
                max_parallel=normalized_max,
                selected_files=selected_files,
                selected_owner_docs=selected_owner_docs,
                selected_validation_resources=selected_validation_resources,
            )
            if skip_reason is not None:
                decision["selected_path"] = "skip"
                decision["skip_reason"] = skip_reason
            else:
                selected_count += 1
                selected_for_dispatch = True
                context_pack_id = f"ctx-{candidate['issue_number']}"
                context_pack = _build_context_pack(
                    candidate,
                    decision=decision,
                    context_pack_id=context_pack_id,
                    dispatch_slot=selected_count,
                )
                context_packs.append(context_pack)
                selected_files.update(candidate["likely_touched_files"])
                if candidate["owner_doc_writeback_required"]:
                    selected_owner_docs.update(candidate["owner_docs"])
                selected_validation_resources.update(candidate["validation_resources"])

        decision.update(
            {
                "id": f"dispatch-{candidate['issue_number']}",
                "candidate_index": index,
                "issue_number": candidate["issue_number"],
                "title": candidate["title"],
                "selected_for_dispatch": selected_for_dispatch,
                "dispatch_slot": selected_count if selected_for_dispatch else None,
                "context_pack_id": context_pack_id,
            }
        )
        decisions.append(decision)

    return {
        "schema_version": SCHEMA_VERSION,
        "epic_issue_number": normalized_epic,
        "run_id": normalized_run_id,
        "max_parallel": normalized_max,
        "runtime_targets": runtimes,
        "selected_count": selected_count,
        "decisions": decisions,
        "context_packs": context_packs,
        "epic_run_state_update": {
            "dispatch_decisions": [
                _dispatch_state_summary(decision) for decision in decisions
            ]
        },
        "github_mutations": [],
        "agent_spawns": [],
        "source": "builderops.epic_dispatch.dry_run",
        "run_state_seen": run_state_seen,
    }


def _build_tcd_decision(
    candidate: Mapping[str, Any],
    runtimes: list[str],
    active_leases: set[int],
) -> dict[str, Any]:
    issue_number = candidate["issue_number"]
    skip_reason = _claimability_skip_reason(candidate, active_leases)
    selected_path = "skip" if skip_reason is not None else _selected_path(candidate)
    runtime_target = candidate["runtime_hint"] or runtimes[0]
    if runtime_target not in runtimes:
        runtime_target = runtimes[0]
    risk = candidate["risk"]

    if selected_path == "inline":
        skip_reason = skip_reason or "inline-local-cheaper"
    elif selected_path == "script":
        skip_reason = skip_reason or "script-deterministic"

    return {
        "issue_number": issue_number,
        "selected_path": selected_path,
        "expected_value": candidate["expected_value"],
        "runtime_model_hint": {
            "runtime": runtime_target,
            "model_class": _model_class_for(risk),
            "runtime_difference": "invocation-hint-only",
        },
        "budget_class": _budget_class_for(risk, candidate["expected_value"]),
        "stop_condition": candidate["stop_condition"]
        or "Return a subagent_handoff_receipt; stop on claim conflict, branch/worktree drift, missing Verify target, or authority ambiguity.",
        "skip_reason": skip_reason,
    }


def _build_context_pack(
    candidate: Mapping[str, Any],
    *,
    decision: Mapping[str, Any],
    context_pack_id: str,
    dispatch_slot: int,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "context_pack_id": context_pack_id,
        "dispatch_slot": dispatch_slot,
        "issue_contract": {
            "number": candidate["issue_number"],
            "title": candidate["title"],
            "url": candidate["url"],
            "scope": candidate["scope"],
        },
        "runtime": decision["runtime_model_hint"],
        "skill_loaded": ".codex/skills/issue-to-code/SKILL.md",
        "source_anchors": candidate["source_anchors"],
        "owner_docs": sorted(candidate["owner_docs"]),
        "known_constraints": candidate["known_constraints"],
        "branch_worktree_plan": {
            "branch": candidate["branch"],
            "worktree": candidate["worktree"],
            "worker_self_claim": True,
            "coordinator_preclaim": False,
        },
        "validation_ledger": candidate["validation"],
        "publication_closure_expectations": {
            "publish_skill": ".codex/skills/publish-pr/SKILL.md",
            "verification_skill": ".codex/skills/verification-and-closure/SKILL.md",
            "builderops_routing_required": True,
            "github_lifecycle_truth": "Issues/PRs/CI",
            "no_project_or_label_mutation_by_dispatch_planner": True,
        },
        "return_schema": HANDOFF_RECEIPT_SCHEMA,
    }


def _parallel_skip_reason(
    candidate: Mapping[str, Any],
    *,
    selected_count: int,
    max_parallel: int,
    selected_files: set[str],
    selected_owner_docs: set[str],
    selected_validation_resources: set[str],
) -> str | None:
    if selected_count >= max_parallel:
        return "parallel-slot-cap"
    if candidate["dependencies"] and not candidate["dependencies_satisfied"]:
        return "dependency-not-ready"
    if selected_files.intersection(candidate["likely_touched_files"]):
        return "likely-file-conflict"
    if (
        candidate["owner_doc_writeback_required"]
        and selected_owner_docs.intersection(candidate["owner_docs"])
    ):
        return "owner-doc-writeback-conflict"
    if selected_validation_resources.intersection(candidate["validation_resources"]):
        return "validation-resource-conflict"
    return None


def _claimability_skip_reason(
    candidate: Mapping[str, Any],
    active_leases: set[int],
) -> str | None:
    if candidate["issue_number"] in active_leases:
        return "active-lease-conflict"
    if candidate["state"] != "OPEN":
        return "issue-not-open"
    if candidate["project_status"] != "Ready":
        return "project-status-not-ready"
    if "agent:ready" not in candidate["labels"]:
        return "missing-agent-ready-label"
    return None


def _selected_path(candidate: Mapping[str, Any]) -> str:
    preferred = candidate["preferred_path"]
    if preferred:
        if preferred not in VALID_PATHS:
            raise EpicDispatchError(f"preferred_path must be one of {sorted(VALID_PATHS)}")
        return preferred
    if candidate["risk"] in {"high", "critical"}:
        return "subagent"
    if candidate["expected_value"] == "high":
        return "subagent"
    if candidate["scriptable"]:
        return "script"
    if candidate["expected_value"] == "low" or candidate["task_class"] in {
        "mechanical",
        "small-doc",
        "trivial",
    }:
        return "inline"
    return "subagent"


def _dispatch_state_summary(decision: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": decision["id"],
        "issue_number": decision["issue_number"],
        "selected_path": decision["selected_path"],
        "selected_for_dispatch": decision["selected_for_dispatch"],
        "runtime_model_hint": decision["runtime_model_hint"],
        "budget_class": decision["budget_class"],
        "stop_condition": decision["stop_condition"],
        "skip_reason": decision["skip_reason"],
        "context_pack_id": decision["context_pack_id"],
    }


def _normalize_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(candidate, Mapping):
        raise EpicDispatchError("candidate must be an object")
    issue_number = _normalize_positive_int(
        candidate.get("issue_number", candidate.get("number")),
        "issue_number",
    )
    return {
        "issue_number": issue_number,
        "title": _normalize_string(candidate.get("title"), "title"),
        "url": _normalize_optional_string(candidate.get("url")),
        "state": _normalize_string(candidate.get("state", "OPEN"), "state").upper(),
        "labels": set(_normalize_string_list(candidate.get("labels", []), "labels")),
        "project_status": _normalize_string(
            candidate.get("project_status", candidate.get("status", "Ready")),
            "project_status",
        ),
        "risk": _normalize_choice(
            candidate.get("risk", "medium"),
            "risk",
            {"low", "medium", "high", "critical"},
        ),
        "expected_value": _normalize_choice(
            candidate.get("expected_value", "medium"),
            "expected_value",
            {"low", "medium", "high"},
        ),
        "task_class": _normalize_string(candidate.get("task_class", "implementation"), "task_class"),
        "preferred_path": _normalize_optional_string(candidate.get("preferred_path")),
        "runtime_hint": _normalize_optional_string(candidate.get("runtime_hint")),
        "scriptable": bool(candidate.get("scriptable", False)),
        "stop_condition": _normalize_optional_string(candidate.get("stop_condition")),
        "dependencies": [
            _normalize_positive_int(value, "dependencies")
            for value in candidate.get("dependencies", candidate.get("depends_on", []))
        ],
        "dependencies_satisfied": bool(candidate.get("dependencies_satisfied", False)),
        "likely_touched_files": set(
            _normalize_string_list(
                candidate.get("likely_touched_files", []),
                "likely_touched_files",
            )
        ),
        "owner_docs": set(_normalize_string_list(candidate.get("owner_docs", []), "owner_docs")),
        "owner_doc_writeback_required": bool(
            candidate.get("owner_doc_writeback_required", False)
        ),
        "validation_resources": set(
            _normalize_string_list(
                candidate.get(
                    "validation_resources",
                    candidate.get("exclusive_validation_groups", []),
                ),
                "validation_resources",
            )
        ),
        "source_anchors": _normalize_json_list(candidate.get("source_anchors", []), "source_anchors"),
        "known_constraints": _normalize_json_list(
            candidate.get("known_constraints", []),
            "known_constraints",
        ),
        "validation": _normalize_json_list(candidate.get("validation", []), "validation"),
        "scope": _normalize_optional_string(candidate.get("scope"))
        or "Read the issue body and satisfy its bounded Scope and Acceptance Criteria.",
        "branch": _normalize_optional_string(candidate.get("branch"))
        or f"codex/issue-{issue_number}",
        "worktree": _normalize_optional_string(candidate.get("worktree"))
        or f"<dedicated-worktree-for-issue-{issue_number}>",
    }


def _validate_run_state_owner(
    run_state: Mapping[str, Any],
    *,
    epic_issue_number: int,
    run_id: str,
) -> None:
    state_epic = _normalize_positive_int(
        run_state.get("epic_issue_number"),
        "run_state.epic_issue_number",
    )
    state_run_id = _normalize_string(run_state.get("run_id"), "run_state.run_id")
    if state_epic != epic_issue_number:
        raise EpicDispatchError(
            f"run_id {run_id!r} already belongs to epic {state_epic}"
        )
    if state_run_id != run_id:
        raise EpicDispatchError(
            f"loaded run-state id {state_run_id!r} does not match requested run_id {run_id!r}"
        )


def _normalize_active_leases(
    active_leases: Iterable[int | str | Mapping[str, Any]],
) -> set[int]:
    lease_issues: set[int] = set()
    for lease in active_leases:
        if isinstance(lease, Mapping):
            value = lease.get("issue_number", lease.get("issue"))
        else:
            value = lease
        lease_issues.add(_normalize_positive_int(value, "active_leases"))
    return lease_issues


def _normalize_runtime_targets(values: Iterable[str]) -> list[str]:
    runtimes = [_normalize_string(value, "runtime_targets") for value in values]
    if not runtimes:
        raise EpicDispatchError("runtime_targets must not be empty")
    return list(dict.fromkeys(runtimes))


def _normalize_positive_int(value: Any, field: str) -> int:
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EpicDispatchError(f"{field} must be a positive integer")
    return value


def _normalize_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EpicDispatchError(f"{field} must be a non-empty string")
    return value.strip()


def _normalize_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise EpicDispatchError("optional string values must be non-empty strings")
    return value.strip()


def _normalize_choice(value: Any, field: str, allowed: set[str]) -> str:
    normalized = _normalize_string(value, field).lower()
    if normalized not in allowed:
        raise EpicDispatchError(f"{field} must be one of {sorted(allowed)}")
    return normalized


def _normalize_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise EpicDispatchError(f"{field} must be a list")
    return [_normalize_string(item, field) for item in value]


def _normalize_json_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise EpicDispatchError(f"{field} must be a list")
    try:
        return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise EpicDispatchError(f"{field} must be JSON serializable") from exc


def _model_class_for(risk: str) -> str:
    if risk in {"critical", "high"}:
        return "high-reasoning"
    if risk == "low":
        return "low-cost"
    return "standard"


def _budget_class_for(risk: str, expected_value: str) -> str:
    if risk in {"critical", "high"} or expected_value == "high":
        return "high"
    if risk == "low" and expected_value == "low":
        return "low"
    return "medium"


__all__ = [
    "DEFAULT_MAX_PARALLEL",
    "HANDOFF_RECEIPT_SCHEMA",
    "SCHEMA_VERSION",
    "EpicDispatchError",
    "build_dispatch_plan",
]
