from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.builderops.ckm.observation_capture import (
    OBSERVATION_SCHEMA_VERSION,
    OBSERVATION_TABLE,
    RETENTION_DAYS,
    RETENTION_POLICY_VERSION,
    QueryObservationError,
    QueryObservationInput,
    QueryObservationStore,
    observation_store_path,
)
from app.builderops.ckm.query_service import CkmQueryService
from app.builderops.ckm.store import CkmStore

OBSERVED_AT = "2026-07-22T10:00:00Z"
SECRET = "customer Alice /vault/private/strategy.md citation-secret"


def _store(tmp_path: Path) -> CkmStore:
    store = CkmStore(tmp_path / "ckm.sqlite")
    store.ensure_schema()
    store.upsert_capability(
        identity_key="seed:observation",
        name=SECRET,
        definition=SECRET,
        lifecycle="confirmed",
        existence_provenance=SECRET,
    )
    return store


def _metadata(**overrides: object) -> QueryObservationInput:
    values: dict[str, object] = {
        "query_family": "capability_list",
        "resource_type": "capability",
        "filter_kinds": ("none",),
        "latency_ms": 12.0,
    }
    values.update(overrides)
    return QueryObservationInput(**values)  # type: ignore[arg-type]


def _rows(store: QueryObservationStore) -> list[sqlite3.Row]:
    with sqlite3.connect(store.path) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            f"SELECT * FROM {OBSERVATION_TABLE} ORDER BY observed_at, observation_id"
        ).fetchall()


def _fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_query_observation_schema_excludes_sensitive_payloads(tmp_path: Path) -> None:
    ckm = _store(tmp_path)
    outcome = CkmQueryService(ckm.db_path).list_capabilities()
    observations = QueryObservationStore(ckm.db_path)
    observations.capture(
        outcome,
        event_kind="supported_result",
        metadata=_metadata(),
        observed_at=OBSERVED_AT,
    )

    assert observations.path == tmp_path / "ckm-query-observations.sqlite"
    row = _rows(observations)[0]
    payload = json.loads(row["observation_json"])
    serialized = json.dumps(payload, sort_keys=True)
    assert SECRET not in serialized
    assert not any(
        forbidden in serialized
        for forbidden in ("display_name", "definition", "path", "citation", "resources")
    )
    assert set(payload) == {
        "authority",
        "outcome",
        "performance",
        "projection",
        "query",
        "snapshot_digest",
        "versions",
    }
    assert row["schema_version"] == OBSERVATION_SCHEMA_VERSION
    assert row["policy_version"] == RETENTION_POLICY_VERSION

    malformed_ckm = tmp_path / "malformed.sqlite"
    malformed_path = observation_store_path(malformed_ckm)
    with sqlite3.connect(malformed_path) as connection:
        connection.execute(f"CREATE TABLE {OBSERVATION_TABLE} (observation_id TEXT)")
    with pytest.raises(QueryObservationError, match="does not match version 1") as exc_info:
        QueryObservationStore(malformed_ckm).initialize()
    assert exc_info.value.code == "observation_store_unsupported"

    extra_ckm = tmp_path / "extra.sqlite"
    extra = QueryObservationStore(extra_ckm)
    extra.initialize()
    with sqlite3.connect(extra.path) as connection:
        connection.execute(f"ALTER TABLE {OBSERVATION_TABLE} ADD COLUMN raw_query TEXT")
    with pytest.raises(QueryObservationError) as extra_exc:
        extra.initialize()
    assert extra_exc.value.code == "observation_store_unsupported"
    assert extra_exc.value.details == {
        "missing_columns": [],
        "unexpected_columns": ["raw_query"],
    }


def test_supported_refused_and_accepted_question_events_are_distinct(tmp_path: Path) -> None:
    ckm = _store(tmp_path)
    service = CkmQueryService(ckm.db_path)
    observations = QueryObservationStore(ckm.db_path)
    supported = service.list_capabilities()
    refused = service.list_capabilities(filters={"unsupported": "x"})
    historical = service.list_capabilities(history_mode="as_of")

    observations.capture(supported, event_kind="supported_result", metadata=_metadata(), observed_at=OBSERVED_AT)
    observations.capture(refused, event_kind="typed_refusal", metadata=_metadata(), observed_at="2026-07-22T10:00:01Z")
    observations.capture(
        historical,
        event_kind="unsupported_history_request",
        metadata=_metadata(query_family="historical_request", filter_kinds=("history_mode",)),
        observed_at="2026-07-22T10:00:02Z",
    )
    observations.capture(
        None,
        event_kind="accepted_question",
        metadata=_metadata(
            query_family="accepted_question",
            question_kind="historical_change_question",
            human_authority="owner_accepted",
            source_authority_kind="github_issue",
            source_authority_ref="issue:#3780",
        ),
        observed_at="2026-07-22T10:00:03Z",
    )

    rows = _rows(observations)
    assert {row["event_kind"] for row in rows} == {
        "supported_result",
        "typed_refusal",
        "unsupported_history_request",
        "accepted_question",
    }
    payloads = {row["event_kind"]: json.loads(row["observation_json"]) for row in rows}
    assert payloads["typed_refusal"]["outcome"]["refusal_kind"] == "unsupported_filter"
    assert payloads["unsupported_history_request"]["outcome"]["refusal_kind"] == "unsupported_historical_semantics"
    assert "accepted_question" in payloads["accepted_question"]


def test_observation_is_bounded_bound_and_non_replayable(tmp_path: Path) -> None:
    ckm = _store(tmp_path)
    outcome = CkmQueryService(ckm.db_path).list_capabilities()
    observations = QueryObservationStore(ckm.db_path)
    first = observations.capture(outcome, event_kind="supported_result", metadata=_metadata(), observed_at=OBSERVED_AT)
    retry = observations.capture(outcome, event_kind="supported_result", metadata=_metadata(), observed_at=OBSERVED_AT)
    later = observations.capture(outcome, event_kind="supported_result", metadata=_metadata(), observed_at="2026-07-22T10:00:01Z")

    assert retry.observation_id == first.observation_id
    assert later.observation_id != first.observation_id
    assert len(_rows(observations)) == 2
    replayed = observations.replay(first.observation_id)
    assert replayed["query"]["digest"] == outcome.query_digest
    assert "resources" not in replayed

    with pytest.raises(QueryObservationError) as latency_exc:
        observations.capture(
            outcome,
            event_kind="supported_result",
            metadata=_metadata(latency_ms=float("nan")),
            observed_at="2026-07-22T10:00:02Z",
        )
    assert latency_exc.value.code == "invalid_observation"

    collision_ckm = tmp_path / "collision.sqlite"
    collision = QueryObservationStore(collision_ckm)
    prepared = collision._prepare(  # noqa: SLF001 - exact persisted collision fixture
        outcome,
        event_kind="supported_result",
        metadata=_metadata(),
        observed_at=OBSERVED_AT,
        supersedes_observation_id=None,
    )
    collision.initialize()
    corrupt = list(prepared.row())
    corrupt[4] = "f" * 64
    with sqlite3.connect(collision.path) as connection:
        connection.execute(
            f"INSERT INTO {OBSERVATION_TABLE} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            corrupt,
        )
    with pytest.raises(QueryObservationError) as collision_exc:
        collision.capture(
            outcome,
            event_kind="supported_result",
            metadata=_metadata(),
            observed_at=OBSERVED_AT,
        )
    assert collision_exc.value.code == "observation_identity_collision"


def test_observation_runs_only_after_query_path_returns(tmp_path: Path) -> None:
    ckm = _store(tmp_path)
    before = _fingerprint(ckm.db_path)
    outcome = CkmQueryService(ckm.db_path).list_capabilities()
    assert not observation_store_path(ckm.db_path).exists()
    assert _fingerprint(ckm.db_path) == before

    QueryObservationStore(ckm.db_path).capture(
        outcome,
        event_kind="supported_result",
        metadata=_metadata(),
        observed_at=OBSERVED_AT,
    )
    assert observation_store_path(ckm.db_path).exists()
    for path in (
        Path("app/builderops/ckm/query_service.py"),
        Path("app/builderops/ckm/store.py"),
        Path("app/builderops/ckm/contracts.py"),
    ):
        assert "observation_capture" not in path.read_text()


def test_observation_has_no_authority_or_ckm_side_effect(tmp_path: Path) -> None:
    ckm = _store(tmp_path)
    outcome = CkmQueryService(ckm.db_path).list_capabilities()
    state_before = ckm.state_identity()
    fingerprint_before = _fingerprint(ckm.db_path)
    observations = QueryObservationStore(ckm.db_path)
    receipt = observations.capture(outcome, event_kind="supported_result", metadata=_metadata(), observed_at=OBSERVED_AT)

    assert ckm.state_identity() == state_before
    assert _fingerprint(ckm.db_path) == fingerprint_before
    payload = observations.replay(receipt.observation_id)
    assert payload["projection"] == {
        "authoritative": False,
        "authority_effects": "none",
        "status": "derived_projection",
    }
    assert payload["authority"] == {
        "automatic_action": False,
        "effect": "none",
        "m2_authorized": False,
        "o2_authorized": False,
    }


def test_observation_failure_preserves_returned_query_semantics(tmp_path: Path) -> None:
    ckm = _store(tmp_path)
    outcome = CkmQueryService(ckm.db_path).list_capabilities()
    returned = outcome.to_dict()
    observations = QueryObservationStore(ckm.db_path)
    observations.initialize()
    with sqlite3.connect(observations.path) as connection:
        connection.execute(
            f"CREATE TRIGGER fail_observation BEFORE INSERT ON {OBSERVATION_TABLE} "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        )
    with pytest.raises(QueryObservationError) as exc_info:
        observations.capture(outcome, event_kind="supported_result", metadata=_metadata(), observed_at=OBSERVED_AT)
    assert exc_info.value.code == "observation_persistence_failed"
    assert outcome.to_dict() == returned
    assert _rows(observations) == []


def test_accepted_question_records_authority_without_enabling_history(tmp_path: Path) -> None:
    ckm = _store(tmp_path)
    observations = QueryObservationStore(ckm.db_path)
    raw_source = "private-owner-record:#3780"
    receipt = observations.capture(
        None,
        event_kind="accepted_question",
        metadata=_metadata(
            query_family="accepted_question",
            question_kind="historical_change_question",
            human_authority="owner_accepted",
            source_authority_kind="owner_decision",
            source_authority_ref=raw_source,
        ),
        observed_at=OBSERVED_AT,
    )
    payload = observations.replay(receipt.observation_id)
    accepted = payload["accepted_question"]
    assert accepted["human_authority"] == "owner_accepted"
    assert accepted["source_authority_kind"] == "owner_decision"
    assert accepted["source_authority_digest"] == hashlib.sha256(
        json.dumps(raw_source, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    assert accepted["history_support_enabled"] is False
    assert raw_source not in _rows(observations)[0]["observation_json"]
    assert payload["authority"]["m2_authorized"] is False
    assert payload["authority"]["o2_authorized"] is False


def test_observation_retention_requires_accepted_policy(tmp_path: Path) -> None:
    ckm = _store(tmp_path)
    outcome = CkmQueryService(ckm.db_path).list_capabilities()
    observations = QueryObservationStore(ckm.db_path)
    receipt = observations.capture(outcome, event_kind="supported_result", metadata=_metadata(), observed_at=OBSERVED_AT)
    row = _rows(observations)[0]
    expected_expiry = datetime.fromisoformat(OBSERVED_AT.replace("Z", "+00:00")) + timedelta(days=RETENTION_DAYS)
    assert row["expires_at"] == expected_expiry.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    assert observations.storage_usage()["count"] == 1
    secret_reason = "operator deleted /vault/private/customer.md"
    with pytest.raises(QueryObservationError) as reason_exc:
        observations.prune(
            [receipt.observation_id],
            reason=secret_reason,
            at="2026-07-23T10:00:00Z",
            previewed_observation_ids=[receipt.observation_id],
        )
    assert reason_exc.value.code == "invalid_prune_reason"
    assert secret_reason not in observations.path.read_bytes().decode(
        "utf-8", errors="ignore"
    )
    with pytest.raises(QueryObservationError) as exc_info:
        observations.prune([receipt.observation_id], reason="operator_pruned", at="2026-07-23T10:00:00Z")
    assert exc_info.value.code == "prune_preview_required"
    preview = observations.preview_prune(now="2026-07-23T10:00:00Z", earlier_than_365_days=True)
    assert preview == [{"observation_id": receipt.observation_id, "reason": "explicit_operator_prune_preview"}]
    with pytest.raises(QueryObservationError) as expiry_exc:
        observations.prune(
            [receipt.observation_id],
            reason="retention_expired",
            at="2026-07-23T10:00:00Z",
            previewed_observation_ids=[receipt.observation_id],
        )
    assert expiry_exc.value.code == "retention_not_expired"
    unchanged = _rows(observations)[0]
    assert unchanged["observation_json"] is not None
    assert unchanged["semantic_digest"]
    observations.prune(
        [receipt.observation_id],
        reason="operator_pruned",
        at="2026-07-23T10:00:00Z",
        previewed_observation_ids=[receipt.observation_id],
    )
    removed = _rows(observations)[0]
    assert removed["observation_json"] is None
    assert removed["semantic_digest"] == ""
    assert json.loads(removed["lifecycle_marker_json"])["payload_removed"] is True
    with pytest.raises(QueryObservationError) as retry_exc:
        observations.capture(
            outcome,
            event_kind="supported_result",
            metadata=_metadata(),
            observed_at=OBSERVED_AT,
        )
    assert retry_exc.value.code == "observation_unavailable"
    after_retry = _rows(observations)
    assert len(after_retry) == 1
    assert after_retry[0]["observation_json"] is None
    assert after_retry[0]["semantic_digest"] == ""

    expiring = observations.capture(
        outcome,
        event_kind="supported_result",
        metadata=_metadata(),
        observed_at="2026-07-22T10:00:01Z",
    )
    expiring_row = {
        row["observation_id"]: row for row in _rows(observations)
    }[expiring.observation_id]
    observations.prune(
        [expiring.observation_id],
        reason="retention_expired",
        at=expiring_row["expires_at"],
    )
    expired = {row["observation_id"]: row for row in _rows(observations)}[
        expiring.observation_id
    ]
    assert expired["lifecycle"] == "retention_expired"
    assert expired["observation_json"] is None
    assert expired["semantic_digest"] == ""


def test_observation_correction_and_deletion_preserve_lifecycle_truth(tmp_path: Path) -> None:
    ckm = _store(tmp_path)
    outcome = CkmQueryService(ckm.db_path).list_capabilities()
    observations = QueryObservationStore(ckm.db_path)
    original = observations.capture(outcome, event_kind="supported_result", metadata=_metadata(), observed_at=OBSERVED_AT)
    successor = observations.correct(
        original.observation_id,
        outcome,
        event_kind="supported_result",
        metadata=_metadata(latency_ms=110.0),
        observed_at="2026-07-22T10:01:00Z",
    )
    retry = observations.correct(
        original.observation_id,
        outcome,
        event_kind="supported_result",
        metadata=_metadata(latency_ms=110.0),
        observed_at="2026-07-22T10:01:00Z",
    )
    assert retry == successor
    original_retry = observations.capture(
        outcome,
        event_kind="supported_result",
        metadata=_metadata(),
        observed_at=OBSERVED_AT,
    )
    assert original_retry.observation_id == original.observation_id
    assert original_retry.lifecycle == "superseded"
    assert original_retry.payload_available is True
    rows = {row["observation_id"]: row for row in _rows(observations)}
    assert rows[original.observation_id]["lifecycle"] == "superseded"
    assert rows[successor.observation_id]["supersedes_observation_id"] == original.observation_id
    assert observations.replay(original.observation_id)["performance"]["latency_bucket"] == "10_to_99ms"

    observations.delete(successor.observation_id, at="2026-07-22T10:02:00Z")
    deleted = {row["observation_id"]: row for row in _rows(observations)}[successor.observation_id]
    assert deleted["lifecycle"] == "required_deletion"
    assert deleted["observation_json"] is None
    assert deleted["semantic_digest"] == ""
    with pytest.raises(QueryObservationError) as retry_exc:
        observations.correct(
            original.observation_id,
            outcome,
            event_kind="supported_result",
            metadata=_metadata(latency_ms=110.0),
            observed_at="2026-07-22T10:01:00Z",
        )
    assert retry_exc.value.code == "observation_unavailable"
    assert len(_rows(observations)) == 2
    with pytest.raises(QueryObservationError) as exc_info:
        observations.replay(successor.observation_id)
    assert exc_info.value.code == "observation_unavailable"
