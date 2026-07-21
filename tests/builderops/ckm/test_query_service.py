from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from click.testing import CliRunner

from app.builderops.cli import builderops
from app.builderops.ckm.contracts import ACCESS_POLICY_VERSION, EFFECTIVE_AUDIENCE, REDACTION_PROFILE
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


def test_incomplete_or_oversized_snapshot_refuses(tmp_path: Path) -> None:
    store, _, _ = _store(tmp_path)
    service = CkmQueryService(store.db_path, capture_limit=1)
    refusal = service.list_capabilities().to_dict()
    assert refusal["error"]["code"] == "snapshot_too_large" and "resources" not in refusal
    for kwargs, code in (({"access_policy_version": "wrong"}, "unsupported_access_policy"), ({"ckm_schema_version": 999}, "unsupported_version"), ({"history_mode": "as_of"}, "unsupported_historical_semantics")):
        payload = CkmQueryService(store.db_path).list_capabilities(**kwargs).to_dict()
        assert payload["error"]["code"] == code and "resources" not in payload


def test_missing_candidate_completeness_and_access_semantics(tmp_path: Path) -> None:
    store, confirmed, candidate = _store(tmp_path)
    payload = CkmQueryService(store.db_path).list_capabilities().to_dict()
    resources = {item["public_id"]: item for item in payload["resources"]}
    assert resources[candidate.public_id]["candidate"] is True
    assert resources[confirmed.public_id]["candidate"] is False
    assert resources[confirmed.public_id]["values"]["assessment"]["state"] == "unassessed"
    assert resources[confirmed.public_id]["values"]["boundary_ref"]["state"] == "missing"
    assert payload["snapshot"]["completeness"]["object_classes"][0]["included"] == 2


def test_cli_json_uses_transport_neutral_service(tmp_path: Path) -> None:
    store, _, _ = _store(tmp_path)
    result = CliRunner().invoke(builderops, ["--db-path", str(store.db_path), "ckm", "query"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["projection"]["authoritative"] is False


def test_same_snapshot_query_and_versions_are_deterministic(tmp_path: Path) -> None:
    store, _, _ = _store(tmp_path)
    service = CkmQueryService(store.db_path)
    assert json.dumps(service.list_capabilities().to_dict(), sort_keys=True) == json.dumps(service.list_capabilities().to_dict(), sort_keys=True)
    before = service.list_capabilities().to_dict()["snapshot"]["taxonomy_digest"]
    store.upsert_capability(identity_key="seed:topology", name="topology", definition="x", lifecycle="confirmed", existence_provenance="test")
    assert service.list_capabilities().to_dict()["snapshot"]["taxonomy_digest"] != before
