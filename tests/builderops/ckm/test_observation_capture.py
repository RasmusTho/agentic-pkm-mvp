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
SQLITE_SECRET = "raw-query=/vault/private/customer-A.md name=Alice payload=secret"


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


def _assert_sqlite_error_redacted(error: QueryObservationError) -> None:
    public_views = (
        str(error),
        repr(error),
        repr(error.details),
        json.dumps(error.to_dict(), sort_keys=True),
    )
    assert all(SQLITE_SECRET not in view for view in public_views)
    assert error.details == {"error_class": "sqlite_failure"}
    assert error.__cause__ is None


def _inject_temp_trigger(monkeypatch, store: QueryObservationStore, sql: str) -> None:
    original_connect = store._connect

    def connect() -> sqlite3.Connection:
        connection = original_connect()
        connection.execute(sql)
        return connection

    monkeypatch.setattr(store, "_connect", connect)


def _canonical_observation_table_ddl() -> str:
    return f"""
        CREATE TABLE {OBSERVATION_TABLE} (
            observation_id TEXT PRIMARY KEY NOT NULL,
            schema_version INTEGER NOT NULL CHECK (schema_version = 1),
            event_kind TEXT NOT NULL,
            observation_json TEXT,
            semantic_digest TEXT NOT NULL,
            policy_version TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            lifecycle TEXT NOT NULL,
            lifecycle_marker_json TEXT NOT NULL,
            supersedes_observation_id TEXT,
            deleted_at TEXT
        )
    """


def _assert_schema_refused(ckm_path: Path, ddl: str) -> QueryObservationError:
    observation_path = observation_store_path(ckm_path)
    with sqlite3.connect(observation_path) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
        connection.execute(ddl)
    with pytest.raises(QueryObservationError) as exc_info:
        QueryObservationStore(ckm_path).initialize()
    assert exc_info.value.code == "observation_store_unsupported"
    with sqlite3.connect(observation_path) as connection:
        assert connection.execute(
            f"SELECT COUNT(*) FROM {OBSERVATION_TABLE}"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM unrelated"
        ).fetchone()[0] == 0
    return exc_info.value


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

    all_text_columns = ", ".join(
        f"{name} TEXT"
        for name in (
            "observation_id",
            "schema_version",
            "event_kind",
            "observation_json",
            "semantic_digest",
            "policy_version",
            "observed_at",
            "expires_at",
            "lifecycle",
            "lifecycle_marker_json",
            "supersedes_observation_id",
            "deleted_at",
        )
    )
    _assert_schema_refused(
        tmp_path / "all-text.sqlite",
        f"CREATE TABLE {OBSERVATION_TABLE} ({all_text_columns})",
    )
    _assert_schema_refused(
        tmp_path / "no-primary-key.sqlite",
        _canonical_observation_table_ddl().replace(
            "observation_id TEXT PRIMARY KEY NOT NULL",
            "observation_id TEXT NOT NULL",
        ),
    )
    _assert_schema_refused(
        tmp_path / "nullable-columns.sqlite",
        _canonical_observation_table_ddl().replace(" NOT NULL", ""),
    )
    missing_check = _assert_schema_refused(
        tmp_path / "no-check.sqlite",
        _canonical_observation_table_ddl().replace(
            " CHECK (schema_version = 1)", ""
        ),
    )
    assert missing_check.message == (
        "query observation table constraints do not match version 1"
    )

    extra_ckm = tmp_path / "extra.sqlite"
    extra = QueryObservationStore(extra_ckm)
    extra.initialize()
    with sqlite3.connect(extra.path) as connection:
        connection.execute(f"ALTER TABLE {OBSERVATION_TABLE} ADD COLUMN raw_query TEXT")
    with pytest.raises(QueryObservationError) as extra_exc:
        extra.initialize()
    assert extra_exc.value.code == "observation_store_unsupported"

    missing_indexes_ckm = tmp_path / "missing-indexes.sqlite"
    missing_indexes = QueryObservationStore(missing_indexes_ckm)
    with sqlite3.connect(missing_indexes.path) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
        connection.execute(_canonical_observation_table_ddl())
    missing_indexes.initialize()
    with sqlite3.connect(missing_indexes.path) as connection:
        index_names = {
            row[1]
            for row in connection.execute(
                f"PRAGMA index_list({OBSERVATION_TABLE})"
            ).fetchall()
            if row[3] == "c"
        }
        assert index_names == {
            "idx_ckm_query_observation_expiry",
            "idx_ckm_query_observation_lifecycle",
        }
        assert connection.execute(
            "SELECT COUNT(*) FROM unrelated"
        ).fetchone()[0] == 0
    additive_first = missing_indexes.capture(
        outcome,
        event_kind="supported_result",
        metadata=_metadata(),
        observed_at=OBSERVED_AT,
    )
    additive_retry = missing_indexes.capture(
        outcome,
        event_kind="supported_result",
        metadata=_metadata(),
        observed_at=OBSERVED_AT,
    )
    assert additive_retry == additive_first
    assert len(_rows(missing_indexes)) == 1

    wrong_index_ckm = tmp_path / "wrong-index.sqlite"
    wrong_index = QueryObservationStore(wrong_index_ckm)
    with sqlite3.connect(wrong_index.path) as connection:
        connection.execute(_canonical_observation_table_ddl())
        connection.execute(
            f"CREATE INDEX idx_ckm_query_observation_expiry "
            f"ON {OBSERVATION_TABLE}(observation_id, expires_at)"
        )
    with pytest.raises(QueryObservationError) as wrong_index_exc:
        wrong_index.initialize()
    assert wrong_index_exc.value.code == "observation_store_unsupported"
    assert wrong_index_exc.value.details == {
        "index": "idx_ckm_query_observation_expiry"
    }
    assert _rows(wrong_index) == []


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
            question_kind="source_freshness_change",
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


def test_observation_failure_preserves_returned_query_semantics(
    tmp_path: Path, monkeypatch
) -> None:
    ckm = _store(tmp_path)
    outcome = CkmQueryService(ckm.db_path).list_capabilities()
    returned = outcome.to_dict()
    capture_store = QueryObservationStore(tmp_path / "capture.sqlite")
    capture_store.initialize()
    _inject_temp_trigger(
        monkeypatch,
        capture_store,
        f"CREATE TEMP TRIGGER fail_capture BEFORE INSERT ON {OBSERVATION_TABLE} "
        f"BEGIN SELECT RAISE(ABORT, '{SQLITE_SECRET}'); END",
    )
    with pytest.raises(QueryObservationError) as capture_exc:
        capture_store.capture(
            outcome,
            event_kind="supported_result",
            metadata=_metadata(),
            observed_at=OBSERVED_AT,
        )
    assert capture_exc.value.code == "observation_persistence_failed"
    _assert_sqlite_error_redacted(capture_exc.value)
    assert outcome.to_dict() == returned
    assert _rows(capture_store) == []
    assert SQLITE_SECRET.encode() not in capture_store.path.read_bytes()

    with monkeypatch.context() as correction_patch:
        correction_store = QueryObservationStore(tmp_path / "correction.sqlite")
        original = correction_store.capture(
            outcome,
            event_kind="supported_result",
            metadata=_metadata(),
            observed_at=OBSERVED_AT,
        )
        _inject_temp_trigger(
            correction_patch,
            correction_store,
            f"CREATE TEMP TRIGGER fail_correction BEFORE INSERT ON {OBSERVATION_TABLE} "
            f"BEGIN SELECT RAISE(ABORT, '{SQLITE_SECRET}'); END",
        )
        with pytest.raises(QueryObservationError) as correction_exc:
            correction_store.correct(
                original.observation_id,
                outcome,
                event_kind="supported_result",
                metadata=_metadata(latency_ms=120.0),
                observed_at="2026-07-22T10:00:01Z",
            )
        assert correction_exc.value.code == "observation_persistence_failed"
        _assert_sqlite_error_redacted(correction_exc.value)
        correction_rows = _rows(correction_store)
        assert len(correction_rows) == 1
        assert correction_rows[0]["lifecycle"] == "retained"
        assert SQLITE_SECRET.encode() not in correction_store.path.read_bytes()

    for operation in ("prune", "delete"):
        with monkeypatch.context() as lifecycle_patch:
            lifecycle_store = QueryObservationStore(tmp_path / f"{operation}.sqlite")
            receipt = lifecycle_store.capture(
                outcome,
                event_kind="supported_result",
                metadata=_metadata(),
                observed_at=OBSERVED_AT,
            )
            lifecycle = (
                "operator_pruned" if operation == "prune" else "required_deletion"
            )
            _inject_temp_trigger(
                lifecycle_patch,
                lifecycle_store,
                f"CREATE TEMP TRIGGER fail_{operation} BEFORE UPDATE ON "
                f"{OBSERVATION_TABLE} WHEN NEW.lifecycle = '{lifecycle}' "
                f"BEGIN SELECT RAISE(ABORT, '{SQLITE_SECRET}'); END",
            )
            with pytest.raises(QueryObservationError) as lifecycle_exc:
                if operation == "prune":
                    lifecycle_store.prune(
                        [receipt.observation_id],
                        reason="operator_pruned",
                        at="2026-07-23T10:00:00Z",
                        previewed_observation_ids=[receipt.observation_id],
                    )
                else:
                    lifecycle_store.delete(
                        receipt.observation_id, at="2026-07-23T10:00:00Z"
                    )
            assert lifecycle_exc.value.code == "observation_persistence_failed"
            _assert_sqlite_error_redacted(lifecycle_exc.value)
            lifecycle_rows = _rows(lifecycle_store)
            assert len(lifecycle_rows) == 1
            assert lifecycle_rows[0]["lifecycle"] == "retained"
            assert lifecycle_rows[0]["observation_json"] is not None
            assert SQLITE_SECRET.encode() not in lifecycle_store.path.read_bytes()

    read_operations = (
        ("storage", "observation_storage_usage_failed", lambda store: store.storage_usage()),
        (
            "replay",
            "observation_replay_failed",
            lambda store: store.replay("ckm_query_observation_safe"),
        ),
        (
            "preview",
            "observation_prune_preview_failed",
            lambda store: store.preview_prune(now=OBSERVED_AT),
        ),
    )
    for name, expected_code, operation in read_operations:
        with monkeypatch.context() as read_patch:
            read_store = QueryObservationStore(tmp_path / f"read-{name}.sqlite")
            read_store.initialize()
            read_patch.setattr(read_store, "initialize", lambda: None)

            def fail_connect() -> sqlite3.Connection:
                raise sqlite3.OperationalError(SQLITE_SECRET)

            read_patch.setattr(read_store, "_connect", fail_connect)
            with pytest.raises(QueryObservationError) as read_exc:
                operation(read_store)
            assert read_exc.value.code == expected_code
            _assert_sqlite_error_redacted(read_exc.value)
            assert SQLITE_SECRET.encode() not in read_store.path.read_bytes()

    with monkeypatch.context() as initialize_patch:
        initialize_store = QueryObservationStore(
            tmp_path / "raw-path-private-customer-A.sqlite"
        )

        def fail_initialize_connect() -> sqlite3.Connection:
            raise sqlite3.OperationalError(SQLITE_SECRET)

        initialize_patch.setattr(
            initialize_store, "_connect", fail_initialize_connect
        )
        with pytest.raises(QueryObservationError) as initialize_exc:
            initialize_store.initialize()
        assert initialize_exc.value.code == "observation_store_unsupported"
        _assert_sqlite_error_redacted(initialize_exc.value)


def test_accepted_question_records_authority_without_enabling_history(tmp_path: Path) -> None:
    ckm = _store(tmp_path)
    observations = QueryObservationStore(ckm.db_path)
    raw_source = "private-owner-record:#3780"
    receipt = observations.capture(
        None,
        event_kind="accepted_question",
        metadata=_metadata(
            query_family="accepted_question",
            question_kind="evidence_coverage_change",
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
    with pytest.raises(QueryObservationError) as generic_exc:
        observations.capture(
            None,
            event_kind="accepted_question",
            metadata=_metadata(
                query_family="accepted_question",
                question_kind="historical_change_question",
                human_authority="owner_accepted",
                source_authority_kind="owner_decision",
                source_authority_ref="owner-record:generic-history",
            ),
            observed_at="2026-07-22T10:00:01Z",
        )
    assert generic_exc.value.code == "invalid_observation"
    assert len(_rows(observations)) == 1


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
