from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

from click.testing import CliRunner

from app.builderops import cli as cli_module
from app.builderops.cli import builderops
from app.builderops.ckm.contracts import ACCESS_POLICY_VERSION, EFFECTIVE_AUDIENCE, REDACTION_PROFILE, CkmContractError, ErrorEnvelope
from app.builderops.ckm.models import MATURITY_DIMENSIONS
from app.builderops.ckm.query_service import CkmQueryService
from app.builderops.ckm.store import CkmStore


def _store(tmp_path: Path) -> tuple[CkmStore, object, object]:
    store = CkmStore(tmp_path / "ckm.sqlite")
    store.ensure_schema()
    confirmed = store.upsert_capability(identity_key="seed:q1b", name="Q1b", definition="query service", lifecycle="confirmed", existence_provenance="test:q1b")
    candidate = store.upsert_capability(identity_key="inferred:q1b", name="candidate", definition="candidate", lifecycle="candidate", existence_provenance="test:candidate")
    return store, confirmed, candidate


def _storage_fingerprint(path: Path) -> tuple[tuple[str, str], ...]:
    related = sorted(path.parent.glob(f"{path.name}*"))
    return tuple((item.name, hashlib.sha256(item.read_bytes()).hexdigest()) for item in related)


def _directory_fingerprint(path: Path) -> tuple[tuple[str, str], ...]:
    return tuple(
        (str(item.relative_to(path)), hashlib.sha256(item.read_bytes()).hexdigest())
        for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file())
    )


def test_list_capabilities_uses_one_read_transaction(tmp_path: Path, monkeypatch) -> None:
    store, _, _ = _store(tmp_path)
    statements: list[str] = []
    connection_uris: list[str] = []
    original_connect = sqlite3.connect

    def traced_connect(*args, **kwargs):
        connection_uris.append(str(args[0]))
        conn = original_connect(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr("app.builderops.ckm.query_service.sqlite3.connect", traced_connect)
    result = CkmQueryService(store.db_path).list_capabilities().to_dict()
    assert result["snapshot"]["completeness"]["complete"] is True
    assert connection_uris == [f"{store.db_path.absolute().as_uri()}?mode=ro"]
    assert [statement for statement in statements if statement.strip().upper() == "BEGIN"] == ["BEGIN"]
    assert not any(statement.strip().upper().split(" ", 1)[0] in {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"} for statement in statements)


def test_exact_id_lookup_and_complete_bounded_capture(tmp_path: Path) -> None:
    store, confirmed, candidate = _store(tmp_path)
    service = CkmQueryService(store.db_path)
    complete = service.list_capabilities().to_dict()
    exact = service.get_capability(confirmed.public_id).to_dict()
    assert [item["public_id"] for item in complete["resources"]] == sorted([confirmed.public_id, candidate.public_id])
    assert exact["resources"][0]["public_id"] == confirmed.public_id
    assert exact["snapshot"]["taxonomy_digest"] == complete["snapshot"]["taxonomy_digest"]
    assert complete["snapshot"]["effective_audience"] == EFFECTIVE_AUDIENCE
    assert complete["snapshot"]["access_policy_version"] == ACCESS_POLICY_VERSION
    assert complete["snapshot"]["redaction_profile"] == REDACTION_PROFILE
    store.tombstone_capability(confirmed.public_id)
    tombstone = service.get_capability(confirmed.public_id).to_dict()
    assert tombstone["error"]["code"] == "tombstoned_resource"
    assert tombstone["error"]["details"] == {"public_id": confirmed.public_id, "successors": []}
    assert "resources" not in tombstone
    split = store.upsert_capability(identity_key="seed:split", name="split", definition="x", lifecycle="confirmed", existence_provenance="test")
    split_successor = store.upsert_capability(identity_key="seed:split-child", name="split-child", definition="x", lifecycle="confirmed", existence_provenance="test")
    split_successor_two = store.upsert_capability(identity_key="seed:split-child-two", name="split-child-two", definition="x", lifecycle="confirmed", existence_provenance="test")
    store.tombstone_capability(split.public_id, successor_public_ids=[split_successor_two.public_id, split_successor.public_id], relation="split_successor")
    split_details = service.get_capability(split.public_id).to_dict()["error"]["details"]
    assert split_details["successors"] == sorted(
        [
            {"successor_public_id": split_successor.public_id, "relation": "split_successor"},
            {"successor_public_id": split_successor_two.public_id, "relation": "split_successor"},
        ],
        key=lambda item: item["successor_public_id"],
    )
    merge_left = store.upsert_capability(identity_key="seed:merge-left", name="merge-left", definition="x", lifecycle="confirmed", existence_provenance="test")
    merge_result = store.upsert_capability(identity_key="seed:merge-result", name="merge-result", definition="x", lifecycle="confirmed", existence_provenance="test")
    store.tombstone_capability(merge_left.public_id, successor_public_ids=[merge_result.public_id], relation="merge_successor")
    assert service.get_capability(merge_left.public_id).to_dict()["error"]["details"]["successors"] == [{"successor_public_id": merge_result.public_id, "relation": "merge_successor"}]
    assert service.get_capability("ckm_capability_unknown").to_dict()["error"]["code"] == "missing_resource"


def test_capability_lookup_requires_active_public_identity(tmp_path: Path) -> None:
    store, confirmed, candidate = _store(tmp_path)
    service = CkmQueryService(store.db_path)
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "UPDATE ckm_public_identity SET status = 'tombstone', tombstoned_at = '2026-07-23T00:00:00Z' WHERE public_id = ?",
            (confirmed.public_id,),
        )
    tombstoned = service.get_capability(confirmed.public_id).to_dict()
    assert tombstoned["error"]["code"] == "tombstoned_resource"
    selected = service.list_resources(
        "capability",
        filters={"public_ids": [candidate.public_id, confirmed.public_id]},
    ).to_dict()
    assert selected["error"]["code"] == "tombstoned_resource"
    assert "resources" not in selected

    with sqlite3.connect(store.db_path) as conn:
        conn.execute("DELETE FROM ckm_public_identity WHERE public_id = ?", (candidate.public_id,))
    missing = service.get_capability(candidate.public_id).to_dict()
    assert missing["error"]["code"] == "missing_resource"
    selected_missing = service.list_resources(
        "capability",
        filters={"public_ids": [candidate.public_id]},
    ).to_dict()
    assert selected_missing["error"]["code"] == "missing_resource"
    assert "resources" not in selected_missing


def test_query_path_is_read_only_and_side_effect_free(tmp_path: Path) -> None:
    store, _, _ = _store(tmp_path)
    before = _storage_fingerprint(store.db_path)
    assert "resources" in CkmQueryService(store.db_path).list_capabilities().to_dict()
    assert _storage_fingerprint(store.db_path) == before
    missing = tmp_path / "missing" / "ckm.sqlite"
    error = CkmQueryService(missing).list_capabilities().to_dict()["error"]
    assert error["code"] == "missing_store" and not missing.parent.exists()
    unsupported = tmp_path / "unsupported.sqlite"
    sqlite3.connect(unsupported).close()
    before_unsupported = _storage_fingerprint(unsupported)
    assert CkmQueryService(unsupported).list_capabilities().to_dict()["error"]["code"] == "unsupported_store"
    assert _storage_fingerprint(unsupported) == before_unsupported
    failed_open = CkmQueryService(
        store.db_path,
        _connection_factory=lambda _: (_ for _ in ()).throw(sqlite3.OperationalError("denied")),
    ).list_capabilities().to_dict()
    assert failed_open["error"]["code"] == "unsupported_store" and "resources" not in failed_open
    linked_path = tmp_path / "linked.sqlite"
    linked_path.symlink_to(store.db_path)
    linked_before = _directory_fingerprint(tmp_path)
    linked_result = CkmQueryService(linked_path).list_capabilities().to_dict()
    assert linked_result["error"]["code"] == "unsupported_store" and "resources" not in linked_result
    assert _directory_fingerprint(tmp_path) == linked_before

    touched = False
    original_connect = sqlite3.connect

    class TouchingSnapshotConnection:
        def __init__(self, conn: sqlite3.Connection) -> None:
            object.__setattr__(self, "_conn", conn)

        def __getattr__(self, name):
            return getattr(self._conn, name)

        def __setattr__(self, name, value) -> None:
            if name == "row_factory":
                self._conn.row_factory = value
            else:
                object.__setattr__(self, name, value)

        def execute(self, statement, parameters=()):
            nonlocal touched
            cursor = self._conn.execute(statement, parameters)
            if not touched and statement.startswith("SELECT name FROM sqlite_master"):
                snapshot_stat = store.db_path.stat()
                os.utime(store.db_path, ns=(snapshot_stat.st_atime_ns, snapshot_stat.st_mtime_ns + 1))
                touched = True
            return cursor

    changing_before = _directory_fingerprint(tmp_path)
    changing_result = CkmQueryService(
        store.db_path,
        _connection_factory=lambda uri: TouchingSnapshotConnection(original_connect(uri, uri=True)),
    ).list_capabilities().to_dict()
    assert touched is True
    assert changing_result["error"]["code"] == "unsupported_store" and "resources" not in changing_result
    assert _directory_fingerprint(tmp_path) == changing_before

    malformed = CkmStore(tmp_path / "malformed.sqlite")
    malformed.ensure_schema()
    malformed_capability = malformed.upsert_capability(
        identity_key="seed:malformed",
        name="malformed",
        definition="corrupt persisted public identity",
        lifecycle="confirmed",
        existence_provenance="test:malformed",
    )
    with sqlite3.connect(malformed.db_path) as conn:
        conn.execute(
            "UPDATE ckm_capability SET public_id = '' WHERE id = ?",
            (malformed_capability.id,),
        )
        conn.commit()
    malformed_before = _storage_fingerprint(malformed.db_path)
    malformed_result = CkmQueryService(malformed.db_path).list_capabilities().to_dict()
    assert malformed_result["error"]["code"] == "unsupported_store"
    assert "resources" not in malformed_result
    assert _storage_fingerprint(malformed.db_path) == malformed_before
    for filename in ("question?name.sqlite", "hash#name.sqlite", "percent%name.sqlite", "space name.sqlite"):
        reserved = CkmStore(tmp_path / filename)
        reserved.ensure_schema()
        reserved.upsert_capability(
            identity_key=f"seed:{filename}",
            name=filename,
            definition="URI-reserved database path",
            lifecycle="confirmed",
            existence_provenance="test:reserved-path",
        )
        reserved_before = _directory_fingerprint(tmp_path)
        reserved_result = CkmQueryService(reserved.db_path).list_capabilities().to_dict()
        assert len(reserved_result["resources"]) == 1
        assert _directory_fingerprint(tmp_path) == reserved_before
    checkpointed = CkmStore(tmp_path / "checkpointed-wal.sqlite")
    checkpointed.ensure_schema()
    checkpointed_capability = checkpointed.upsert_capability(
        identity_key="seed:checkpointed-wal",
        name="checkpointed WAL",
        definition="checkpointed WAL snapshot",
        lifecycle="confirmed",
        existence_provenance="test:checkpointed-wal",
    )
    with sqlite3.connect(checkpointed.db_path) as conn:
        assert conn.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone() == (0, 0, 0)
    for suffix in ("-wal", "-shm"):
        Path(f"{checkpointed.db_path}{suffix}").unlink(missing_ok=True)
    assert checkpointed.db_path.read_bytes()[18:20] == b"\x02\x02"
    checkpointed_before = _directory_fingerprint(tmp_path)
    checkpointed_result = CkmQueryService(checkpointed.db_path).get_capability(checkpointed_capability.public_id).to_dict()
    assert checkpointed_result["error"]["code"] == "unsupported_store"
    assert "resources" not in checkpointed_result
    assert _directory_fingerprint(tmp_path) == checkpointed_before

    live_wal = CkmStore(tmp_path / "live-wal.sqlite")
    live_wal.ensure_schema()
    live_wal.upsert_capability(
        identity_key="seed:before-wal",
        name="before WAL",
        definition="checkpointed row",
        lifecycle="confirmed",
        existence_provenance="test:before-wal",
    )
    writer = sqlite3.connect(live_wal.db_path)
    try:
        assert writer.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
        writer.execute("PRAGMA wal_autocheckpoint = 0")
        recent = live_wal.upsert_capability(
            identity_key="seed:in-wal",
            name="in WAL",
            definition="uncheckpointed row",
            lifecycle="confirmed",
            existence_provenance="test:in-wal",
        )
        assert Path(f"{live_wal.db_path}-wal").stat().st_size > 0
        with sqlite3.connect(f"{live_wal.db_path.absolute().as_uri()}?mode=ro&immutable=1", uri=True) as conn:
            assert conn.execute("SELECT 1 FROM ckm_capability WHERE public_id = ?", (recent.public_id,)).fetchone() is None
        live_wal_before = _directory_fingerprint(tmp_path)
        live_wal_result = CkmQueryService(live_wal.db_path).list_capabilities().to_dict()
        assert live_wal_result["error"]["code"] == "unsupported_store"
        assert "resources" not in live_wal_result
        assert _directory_fingerprint(tmp_path) == live_wal_before
    finally:
        writer.close()


def test_incomplete_or_oversized_snapshot_refuses(tmp_path: Path) -> None:
    store, _, _ = _store(tmp_path)
    service = CkmQueryService(store.db_path, capture_limit=1)
    refusal = service.list_capabilities().to_dict()
    assert refusal["error"]["code"] == "snapshot_too_large" and "resources" not in refusal
    for kwargs, code in (({"access_policy_version": "wrong"}, "unsupported_access_policy"), ({"ckm_schema_version": 999}, "unsupported_version"), ({"history_mode": "as_of"}, "unsupported_historical_semantics"), ({"filters": {"unsupported": "x"}}, "unsupported_filter")):
        payload = CkmQueryService(store.db_path).list_capabilities(**kwargs).to_dict()
        assert payload["error"]["code"] == code and "resources" not in payload
    original = sqlite3.connect

    class IncompleteConnection:
        def __init__(self, conn: sqlite3.Connection) -> None:
            object.__setattr__(self, "_conn", conn)
            object.__setattr__(self, "_count_seen", False)

        def __getattr__(self, name):
            return getattr(self._conn, name)

        def __setattr__(self, name, value) -> None:
            if name == "row_factory":
                self._conn.row_factory = value
            else:
                object.__setattr__(self, name, value)

        def execute(self, statement, parameters=()):
            cursor = self._conn.execute(statement, parameters)
            if statement.startswith("SELECT COUNT(*) FROM ckm_capability"):
                object.__setattr__(self, "_count_seen", True)
            if self._count_seen and statement.startswith("SELECT capability.*"):
                return _RowsCursor(cursor.fetchall()[:-1])
            return cursor

    incomplete = CkmQueryService(
        store.db_path,
        _connection_factory=lambda uri: IncompleteConnection(original(uri, uri=True)),
    ).list_capabilities().to_dict()
    assert incomplete["error"]["code"] == "incomplete_snapshot" and "resources" not in incomplete
    mixed = _mixed_epoch_payload(store.db_path)
    assert mixed["error"]["code"] == "mixed_epoch" and "resources" not in mixed


class _RowsCursor:
    def __init__(self, rows) -> None:
        self._rows = rows

    def fetchall(self):
        return self._rows


class _StateCursor:
    def __init__(self, row) -> None:
        self._row = row

    def fetchone(self):
        return self._row


def _mixed_epoch_payload(db_path: Path) -> dict:
    original = sqlite3.connect

    class MixedEpochConnection:
        def __init__(self, conn: sqlite3.Connection) -> None:
            object.__setattr__(self, "_conn", conn)
            object.__setattr__(self, "_state_reads", 0)

        def __getattr__(self, name):
            return getattr(self._conn, name)

        def __setattr__(self, name, value) -> None:
            if name == "row_factory":
                self._conn.row_factory = value
            else:
                object.__setattr__(self, name, value)

        def execute(self, statement, parameters=()):
            cursor = self._conn.execute(statement, parameters)
            if statement.startswith("SELECT epoch, state_revision FROM ckm_state"):
                object.__setattr__(self, "_state_reads", self._state_reads + 1)
                if self._state_reads == 1:
                    row = cursor.fetchone()
                    return _StateCursor({"epoch": row["epoch"], "state_revision": int(row["state_revision"]) + 1})
            return cursor

    return CkmQueryService(
        db_path,
        _connection_factory=lambda uri: MixedEpochConnection(original(uri, uri=True)),
    ).list_capabilities().to_dict()


def test_mixed_epoch_snapshot_refuses_without_semantic_result(tmp_path: Path) -> None:
    store, _, _ = _store(tmp_path)
    payload = _mixed_epoch_payload(store.db_path)
    assert payload["error"]["code"] == "mixed_epoch" and "resources" not in payload


def test_missing_candidate_completeness_and_access_semantics(tmp_path: Path) -> None:
    store, confirmed, candidate = _store(tmp_path)
    payload = CkmQueryService(store.db_path).list_capabilities().to_dict()
    resources = {item["public_id"]: item for item in payload["resources"]}
    assert resources[candidate.public_id]["candidate"] is True
    assert resources[confirmed.public_id]["candidate"] is False
    assert resources[confirmed.public_id]["values"]["assessment"]["state"] == "unassessed"
    assert resources[candidate.public_id]["values"]["assessment"]["state"] == "unassessed"
    store.append_assessment(
        capability_id=confirmed.id,
        scores={dimension: 0.5 for dimension in MATURITY_DIMENSIONS},
        citations={dimension: [] for dimension in MATURITY_DIMENSIONS},
        aggregate=0.5,
        watermark_set={"test": "assessment"},
    )
    assessed_resources = {
        item["public_id"]: item for item in CkmQueryService(store.db_path).list_capabilities().to_dict()["resources"]
    }
    assert assessed_resources[confirmed.public_id]["values"]["assessment"]["state"] == "unsupported"
    assert assessed_resources[candidate.public_id]["values"]["assessment"]["state"] == "unassessed"
    assert resources[confirmed.public_id]["values"]["boundary_ref"]["state"] == "missing"
    assert payload["snapshot"]["completeness"]["object_classes"][0]["included"] == 2
    empty = CkmStore(tmp_path / "empty.sqlite")
    empty.ensure_schema()
    empty_payload = CkmQueryService(empty.db_path).list_capabilities().to_dict()
    assert empty_payload["resources"] == []
    assert empty_payload["snapshot"]["completeness"]["complete"] is True
    assert empty_payload["snapshot"]["provenance"] == []


def test_cli_json_uses_transport_neutral_service(tmp_path: Path, monkeypatch) -> None:
    store, _, _ = _store(tmp_path)
    runner = CliRunner()
    success = runner.invoke(builderops, ["--db-path", str(store.db_path), "ckm", "query"])
    assert success.exit_code == 0, success.output
    assert json.loads(success.output)["projection"]["authoritative"] is False
    oversized = runner.invoke(builderops, ["--db-path", str(store.db_path), "ckm", "query", "--limit", "1"])
    assert json.loads(oversized.output)["error"]["code"] == "snapshot_too_large"
    missing = runner.invoke(builderops, ["--db-path", str(tmp_path / "missing.sqlite"), "ckm", "query"])
    assert json.loads(missing.output)["error"]["code"] == "missing_store"
    unsupported_path = tmp_path / "unsupported.sqlite"
    sqlite3.connect(unsupported_path).close()
    unsupported = runner.invoke(builderops, ["--db-path", str(unsupported_path), "ckm", "query"])
    assert json.loads(unsupported.output)["error"]["code"] == "unsupported_store"

    class RefusingService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def list_capabilities(self):
            return ErrorEnvelope(CkmContractError("unsupported_access_policy", "policy mismatch", {}))

    monkeypatch.setattr(cli_module, "CkmQueryService", RefusingService)
    policy = runner.invoke(builderops, ["--db-path", str(store.db_path), "ckm", "query"])
    assert json.loads(policy.output)["error"]["code"] == "unsupported_access_policy"

    class MixedEpochService(RefusingService):
        def list_capabilities(self):
            return ErrorEnvelope(CkmContractError("mixed_epoch", "mixed epoch", {}))

    monkeypatch.setattr(cli_module, "CkmQueryService", MixedEpochService)
    mixed = runner.invoke(builderops, ["--db-path", str(store.db_path), "ckm", "query"])
    assert json.loads(mixed.output)["error"]["code"] == "mixed_epoch"


def test_same_snapshot_query_and_versions_are_deterministic(tmp_path: Path) -> None:
    store, _, _ = _store(tmp_path)
    service = CkmQueryService(store.db_path)
    runner = CliRunner()
    first = runner.invoke(builderops, ["--db-path", str(store.db_path), "ckm", "query"])
    second = runner.invoke(builderops, ["--db-path", str(store.db_path), "ckm", "query"])
    assert first.exit_code == second.exit_code == 0
    assert first.output == second.output
    before = service.list_capabilities().to_dict()["snapshot"]["taxonomy_digest"]
    store.upsert_capability(identity_key="seed:topology", name="topology", definition="x", lifecycle="confirmed", existence_provenance="test")
    assert service.list_capabilities().to_dict()["snapshot"]["taxonomy_digest"] != before
