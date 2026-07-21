from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from click.testing import CliRunner

from app.builderops import cli as cli_module
from app.builderops.cli import builderops
from app.builderops.ckm.contracts import ACCESS_POLICY_VERSION, EFFECTIVE_AUDIENCE, REDACTION_PROFILE, CkmContractError, ErrorEnvelope
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


def test_list_capabilities_uses_one_read_transaction(tmp_path: Path, monkeypatch) -> None:
    store, _, _ = _store(tmp_path)
    statements: list[str] = []
    original_connect = sqlite3.connect

    def traced_connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr("app.builderops.ckm.query_service.sqlite3.connect", traced_connect)
    result = CkmQueryService(store.db_path).list_capabilities().to_dict()
    assert result["snapshot"]["completeness"]["complete"] is True
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
            if self._count_seen and statement.startswith("SELECT * FROM ckm_capability"):
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
