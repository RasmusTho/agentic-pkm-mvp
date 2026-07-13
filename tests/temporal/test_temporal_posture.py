from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from app.temporal.posture import (
    TRUTH_JUDGMENT_COPY,
    derive_temporal_posture,
    render_temporal_signals,
    summarize_temporal_corpus,
)

NOW = datetime(2026, 7, 13, 12, tzinfo=timezone.utc)
POLICY_PATH = Path("config/temporal_posture.v1.json")


def _policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def test_non_allowlisted_kind_has_no_temporal_posture() -> None:
    result = derive_temporal_posture(
        artifact={"kind": "decision_record", "source_updated_at": "2020-01-01T00:00:00Z"},
        policy=_policy(),
        evaluated_at=NOW,
    )

    assert result.overlay is None
    assert result.diagnostic == "kind_not_allowlisted"


def test_posture_derivation_uses_only_explicit_date_evidence() -> None:
    policy = _policy()
    policy["allowlist"][0]["review_interval_days"] = 30
    due = {
        "kind": "external_source",
        "source_updated_at": "2026-06-13T12:00:00Z",
        "ingested_at": "2026-07-13T11:59:00Z",
        "filesystem_mtime": "2026-07-13T11:59:00Z",
    }
    result = derive_temporal_posture(artifact=due, policy=policy, evaluated_at=NOW)

    assert result.overlay is not None
    assert result.overlay.posture == "review_due"
    assert result.overlay.evidence_field == "source_updated_at"
    assert result.overlay.policy_version == "temporal-posture.v1"

    before_boundary = {
        **due,
        "source_updated_at": "2026-06-13T12:00:01Z",
    }
    assert (
        derive_temporal_posture(artifact=before_boundary, policy=policy, evaluated_at=NOW).overlay
        is None
    )

    bad_evidence = (
        {},
        {"source_updated_at": "not-a-date"},
        {"source_updated_at": "2026-06-01T12:00:00"},
        {"source_updated_at": "2026-07-14T12:00:00Z"},
    )
    for fields in bad_evidence:
        artifact = {
            "kind": "external_source",
            "ingested_at": "2020-01-01T00:00:00Z",
            "filesystem_mtime": "2020-01-01T00:00:00Z",
            **fields,
        }
        unknown = derive_temporal_posture(artifact=artifact, policy=policy, evaluated_at=NOW)
        assert unknown.overlay is not None
        assert unknown.overlay.posture == "unknown"
        assert unknown.overlay.reason in {
            "permitted_date_missing",
            "permitted_date_malformed",
            "permitted_date_timezone_ambiguous",
            "permitted_date_in_future",
        }
        assert unknown.overlay.evidence_field in {None, "source_updated_at"}

    malformed_priority = {
        "kind": "external_source",
        "source_updated_at": "not-a-date",
        "source_published_at": "2020-01-01T00:00:00Z",
    }
    no_fallback = derive_temporal_posture(
        artifact=malformed_priority, policy=policy, evaluated_at=NOW
    )
    assert no_fallback.overlay is not None
    assert no_fallback.overlay.posture == "unknown"
    assert no_fallback.overlay.evidence_field == "source_updated_at"


def test_historical_never_ages_into_review_due() -> None:
    artifact = {
        "kind": "historical_external_source",
        "source_published_at": "1900-01-01T00:00:00Z",
    }

    result = derive_temporal_posture(artifact=artifact, policy=_policy(), evaluated_at=NOW)

    assert result.overlay is not None
    assert result.overlay.posture == "historical"
    assert result.overlay.reason == "policy_designated_historical"
    assert result.overlay.evidence_field is None


def test_temporal_posture_is_read_only_and_retrieval_neutral() -> None:
    policy = _policy()
    artifacts = [
        {
            "id": "a",
            "kind": "external_source",
            "source_updated_at": "2020-01-01T00:00:00Z",
            "content": "canonical alpha",
            "score": 0.1,
        },
        {
            "id": "b",
            "kind": "external_source",
            "source_updated_at": "2026-07-12T00:00:00Z",
            "content": "canonical beta",
            "score": 0.9,
        },
    ]
    before = json.dumps(artifacts, sort_keys=True).encode()
    order = [artifact["id"] for artifact in artifacts]

    receipt = summarize_temporal_corpus(artifacts=artifacts, policy=policy, evaluated_at=NOW)

    assert json.dumps(artifacts, sort_keys=True).encode() == before
    assert [artifact["id"] for artifact in artifacts] == order
    assert receipt.artifact_count == 2
    assert receipt.review_due_count == 1


def test_source_drift_and_review_due_are_orthogonal() -> None:
    evaluation = derive_temporal_posture(
        artifact={
            "kind": "external_source",
            "source_updated_at": "2020-01-01T00:00:00Z",
        },
        policy=_policy(),
        evaluated_at=NOW,
    )
    drift = {"classification": "source_drift", "reason": "source hash changed"}

    rendered = render_temporal_signals(evaluation, source_index_drift=drift)

    assert rendered["temporal_posture"]["posture"] == "review_due"
    assert rendered["source_index_drift"] == drift
    assert rendered["source_index_drift"] is not drift
    assert "drift" not in rendered["temporal_posture"]["reason"]


def test_invalid_policy_and_copy_fail_closed() -> None:
    invalid = copy.deepcopy(_policy())
    invalid["allowlist"][0]["review_interval_days"] = 0

    result = derive_temporal_posture(
        artifact={
            "kind": "external_source",
            "source_updated_at": "2020-01-01T00:00:00Z",
        },
        policy=invalid,
        evaluated_at=NOW,
    )
    rendered = render_temporal_signals(result)

    assert result.overlay is None
    assert result.diagnostic == "policy_invalid"
    assert rendered["temporal_posture"] is None
    assert rendered["copy"] == TRUTH_JUDGMENT_COPY
    assert "not a truth judgment" in rendered["copy"].lower()

    forbidden_evidence = copy.deepcopy(_policy())
    forbidden_evidence["allowlist"][0]["permitted_timestamp_fields"] = ["filesystem_mtime"]
    forbidden = derive_temporal_posture(
        artifact={"kind": "external_source", "filesystem_mtime": "2020-01-01T00:00:00Z"},
        policy=forbidden_evidence,
        evaluated_at=NOW,
    )
    assert forbidden.overlay is None
    assert forbidden.diagnostic == "policy_invalid"

    expanded_kind = copy.deepcopy(_policy())
    expanded_kind["allowlist"][0]["kind"] = "decision_record"
    expanded = derive_temporal_posture(
        artifact={"kind": "decision_record", "source_updated_at": "2020-01-01T00:00:00Z"},
        policy=expanded_kind,
        evaluated_at=NOW,
    )
    assert expanded.overlay is None
    assert expanded.diagnostic == "policy_invalid"

    coercive_or_unrepresentable = (
        ("effective_at", 0),
        ("review_interval_days", True),
        ("review_interval_days", 1.0),
        ("review_interval_days", 1_000_000_000),
    )
    for field, value in coercive_or_unrepresentable:
        malformed = copy.deepcopy(_policy())
        if field == "effective_at":
            malformed[field] = value
        else:
            malformed["allowlist"][0][field] = value
        failed_closed = derive_temporal_posture(
            artifact={
                "kind": "external_source",
                "source_updated_at": "2020-01-01T00:00:00Z",
            },
            policy=malformed,
            evaluated_at=NOW,
        )
        assert failed_closed.overlay is None
        assert failed_closed.diagnostic == "policy_invalid"
