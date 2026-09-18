"""Read-only FCA-06 pilot-plan validation, never live evidence or Start authority.

The plan is a deliberately incomplete preparation artifact. Actual approval,
operation, GitHub and human-outcome receipts must be authenticated by their
existing production readers; populating offline JSON cannot qualify a pilot.
"""

from collections.abc import Mapping
import hashlib
import json
from typing import Any

CONTRACT = "builder_second_consumer_pilot_plan.v1"
HUB = "rasmustho/agentic-pkm-mvp"
CONSUMER = "rasmustho/bifrost"
PREREQUISITES = frozenset({
    "independent_authority", "host_runtime", "host_candidate_preparation",
    "authenticated_m2_ui", "consumer_preparation", "source_admission",
    "credentials", "selected_operation_recovery", "exact_human_approval",
})
EVIDENCE = frozenset({
    "authority_and_host", "consumer_preparation", "source_and_policy",
    "selected_operation_recovery", "approval", "run", "result",
    "independent_readback", "candidate_readiness", "human_trial", "human_acceptance",
})
STEPS = (
    "prepare", "select", "preview", "start", "observe", "reconcile",
    "readback", "try", "accept",
)


def _descriptions(value: Any, keys: frozenset[str] | tuple[str, ...]) -> bool:
    return (
        isinstance(value, dict) and set(value) == set(keys)
        and all(isinstance(item, str) and bool(item.strip()) for item in value.values())
    )


def validate_pilot_plan(value: Any) -> dict[str, Any]:
    """Validate the finite preparation receipt without interpreting evidence as grants.

    Allowed callers are operators and conformance tests. No I/O, effects, state,
    model or clock is consumed. Malformed/unavailable input is explicitly invalid;
    valid input is always incomplete. Its digest identifies bytes semantically,
    not a signer, deployed candidate, human decision or authenticated observation.
    """
    result: dict[str, Any] = {
        "contract": CONTRACT, "authority": "projection_only", "status": "invalid",
        "start_authorized": False, "live_qualification": "incomplete",
        "missing_live_evidence": sorted(EVIDENCE), "errors": [], "plan_sha256": None,
    }
    if not isinstance(value, Mapping):
        result["errors"] = ["plan_unavailable_or_malformed"]
        return result
    required = {
        "contract", "authority", "status", "start_authorized", "parent_issue",
        "repository", "issue_repository", "workflow_repository", "operation",
        "selection", "path_envelope", "prerequisites_before_start", "procedure",
        "expected_receipts", "live_evidence", "source_contracts",
    }
    checks = {
        "closed_plan_shape": set(value) == required,
        "contract": value.get("contract") == CONTRACT,
        "no_authority": value.get("authority") == "preparation_only" and value.get("start_authorized") is False,
        "incomplete": value.get("status") == "incomplete" and value.get("selection") is None,
        "parent": type(value.get("parent_issue")) is int and value.get("parent_issue") == 5399,
        "repository_binding": (value.get("repository"), value.get("issue_repository"), value.get("workflow_repository")) == (CONSUMER, HUB, HUB),
        "operation": value.get("operation") == {"type": "deliver_ready_issue", "contract_version": "fca-issue-delivery.v2", "ddo_required": False},
        "path_envelope": value.get("path_envelope") == {"allowed": "explicit regular non-executable docs/*.md paths", "selected_paths": [], "root_readme_allowed": False},
        "pre_start_prerequisites": _descriptions(value.get("prerequisites_before_start"), PREREQUISITES),
        "ordered_procedure": _descriptions(value.get("procedure"), STEPS) and list(value.get("procedure", {})) == list(STEPS),
        "receipt_contracts": _descriptions(value.get("expected_receipts"), EVIDENCE),
        "no_offline_live_claims": value.get("live_evidence") == dict.fromkeys(EVIDENCE),
        "sources": isinstance(value.get("source_contracts"), list) and bool(value.get("source_contracts"))
        and all(isinstance(ref, str) and ref.startswith("docs/") and " :: " in ref for ref in value.get("source_contracts", [])),
    }
    result["errors"] = [name for name, passed in checks.items() if not passed]
    if not result["errors"]:
        try:
            serialized = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError):
            result["errors"] = ["plan_not_json"]
        else:
            result["plan_sha256"] = hashlib.sha256(serialized.encode()).hexdigest()
            result["status"] = "incomplete"
    return result


def main() -> int:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    args = parser.parse_args()
    try:
        value = json.loads(args.plan.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        value = None
    result = validate_pilot_plan(value)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["status"] == "invalid" else 0


if __name__ == "__main__":
    raise SystemExit(main())
