from __future__ import annotations

from pathlib import Path
import hashlib
import json
import sqlite3

from app.dispatcher.store import SqliteStore
from app.dispatcher.verification_consumer import (
    CANONICAL_RECEIPT_SCHEMA_PATH,
    load_and_validate_verification_closer_receipt,
)
from app.dispatcher.verification_dispatch import (
    VerificationDispatchLedger,
)
from scripts.build_verification_dispatch_request import build_request


HEAD = "a" * 40
REPO = "RasmusTho/agentic-pkm-mvp"


def verified_attempt_receipt(
    head: str = HEAD,
    *,
    verdict: str = "verified",
    summary: str = "verified fixture",
    receipt_id: str = "fixture-receipt",
) -> dict[str, object]:
    """Canonical validated producer capability for ledger fixture seeding."""
    review_events: list[dict[str, object]] = []
    receipt_ids = [receipt_id]
    if verdict in {"verified", "delivered"}:
        receipt_ids = [receipt_id]
        review_events = [
            {
                "kind": "review",
                "session_id": receipt_id,
                "capability": "gpt-5.6-sol",
                "reasoning_effort": "xhigh",
                "outcome": "clean",
                "finding_id": None,
                "failure_domain": None,
                "mechanism_id": None,
                "progress_intent_id": None,
                "mechanism_path_sha256": None,
                "strongest": True,
            }
        ]
    human_exception: dict[str, object] | None = None
    if verdict == "needs_human":
        human_exception = {
            "failure_class": "authority-critical",
            "original_intent": "verify the fixture",
            "current_state": "authority is unavailable",
            "tried_actions": ["checked fixture authority"],
            "evidence": ["fixture evidence"],
            "why_unsafe": "continuation lacks authority",
            "options": [
                {
                    "id": "stop",
                    "label": "Stop",
                    "consequence": "preserve the safe state",
                },
                {
                    "id": "continue",
                    "label": "Continue",
                    "consequence": "accept the authority risk",
                },
            ],
            "no_action_option": "stop",
            "recommended_option": "stop",
            "recommendation_rationale": "authority is required",
            "consequence_of_doing_nothing": "the run remains safely stopped",
        }
    receipt = load_and_validate_verification_closer_receipt(
        {
            "verdict": verdict,
            "head_sha": head,
            "summary": summary,
            "receipt_ids": receipt_ids,
            "retry_after": None,
            "review_events": review_events,
            "human_exception": human_exception,
        },
        CANONICAL_RECEIPT_SCHEMA_PATH,
        trusted_repository=REPO,
        trusted_evidence_urls=frozenset(),
    )
    return dict(receipt)


def validated_attempt_receipt(
    payload: dict[str, object],
) -> dict[str, object]:
    """Validate a fixture through the real schema/sanitizer producer path."""
    receipt = load_and_validate_verification_closer_receipt(
        payload,
        CANONICAL_RECEIPT_SCHEMA_PATH,
        trusted_repository=REPO,
        trusted_evidence_urls=frozenset(),
    )
    return dict(receipt)


def admit_verification_receipt(
    state,
    run_id: str,
    session_id: str,
    receipt: dict[str, object],
    *,
    holder: str,
    lease_id: str,
):
    """Use the ledger-private run/lease admission boundary in fixtures."""
    return state._admit_validated_verification_receipt(
        run_id,
        session_id,
        receipt,
        holder=holder,
        lease_id=lease_id,
    )


def admitted_verified_attempt_receipt(
    state,
    run_id: str,
    session_id: str,
    *,
    holder: str,
    lease_id: str,
    head: str = HEAD,
    verdict: str = "verified",
    summary: str = "verified fixture",
    receipt_id: str = "fixture-receipt",
):
    return admit_verification_receipt(
        state,
        run_id,
        session_id,
        verified_attempt_receipt(
            head,
            verdict=verdict,
            summary=summary,
            receipt_id=receipt_id,
        ),
        holder=holder,
        lease_id=lease_id,
    )


def downgrade_verification_schema_to_v3(conn: sqlite3.Connection) -> None:
    """Turn a current test database into the exact pre-repair-budget v3 shape."""
    conn.execute("ALTER TABLE verification_attempts DROP COLUMN finding_id")
    conn.execute("ALTER TABLE verification_attempts DROP COLUMN failure_domain")
    conn.execute("ALTER TABLE verification_attempts DROP COLUMN mechanism_id")
    conn.execute("ALTER TABLE verification_runs DROP COLUMN repair_budget_policy")
    conn.execute("ALTER TABLE verification_runs DROP COLUMN closing_authority_json")
    conn.execute(
        "ALTER TABLE verification_runs DROP COLUMN legacy_recovery_audit_json"
    )
    conn.execute("UPDATE dispatcher_meta SET value='3' WHERE key='schema_version'")


def request(head: str = HEAD, *, final_review_rounds: int = 1) -> dict[str, object]:
    result = build_request(
        event={
            "repository": {"full_name": REPO},
            "artifact_workflow_run": {"id": 123, "repository_id": 456},
            "workflow_run": {
                "id": 99,
                "run_attempt": 1,
                "name": "CI Smoke",
                "event": "pull_request",
                "conclusion": "success",
                "head_sha": head,
                "updated_at": "2026-07-13T12:00:00Z",
            },
        },
        pr={
            "number": 3603,
            "state": "open",
            "body": (
                "Governing-Issue: #3603\n\nFixes #3603\n\n"
                f"Final-Review-Rounds: {final_review_rounds}"
            ),
            "base": {"ref": "main"},
            "head": {"ref": "codex/issue-3603", "sha": head},
            "live_closing_issues": [
                {"number": 3603, "repository": REPO},
            ],
        },
        issue={"number": 3603},
    )
    assert result is not None
    return result


def pre_trust_request(head: str = HEAD) -> dict[str, object]:
    """Return the exact producer shape deployed before artifact authority."""
    result = request(head)
    # Historical v1 artifacts retain the retired source identity so migration
    # tests continue to prove they are recognized only as inert audit records.
    result["source_workflow"] = {
        **result["source_workflow"],
        "name": "CI",
    }
    result["contract_version"] = "verification_dispatch_request.v1"
    result.pop("final_review_rounds")
    identity = {
        "contract_version": result["contract_version"],
        "head_sha": result["current_head_sha"],
        "pr_number": result["pr_number"],
        "repository": result["repository"],
        "stage": result["stage"],
    }
    result["idempotency_key"] = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    result.pop("closing_issues")
    result.pop("supporting_issues")
    result.pop("artifact_provenance")
    result["base_ref"] = "main"
    result["head_ref"] = "codex/issue-3603"
    return result


def b4e2310_pre_trust_request(head: str = HEAD) -> dict[str, object]:
    """Return the exact b4e2310 producer shape.

    This shape bound verification artifacts to GitHub provenance
    (``artifact_provenance`` present) but still predates ``supporting_issues``.
    """
    result = request(head)
    result["source_workflow"] = {
        **result["source_workflow"],
        "name": "CI",
    }
    result["contract_version"] = "verification_dispatch_request.v1"
    result.pop("final_review_rounds")
    identity = {
        "contract_version": result["contract_version"],
        "head_sha": result["current_head_sha"],
        "pr_number": result["pr_number"],
        "repository": result["repository"],
        "stage": result["stage"],
    }
    result["idempotency_key"] = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    result.pop("closing_issues")
    result.pop("supporting_issues")
    result["base_ref"] = "main"
    result["head_ref"] = "codex/issue-3603"
    return result


def ledger(tmp_path: Path) -> VerificationDispatchLedger:
    return VerificationDispatchLedger(SqliteStore(tmp_path / "dispatcher.sqlite3"))
