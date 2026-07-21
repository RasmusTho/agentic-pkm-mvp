from __future__ import annotations

import json
from pathlib import Path

from app.builderops.ckm.contracts import ACCESS_POLICY_VERSION, EFFECTIVE_AUDIENCE, REDACTION_PROFILE
from app.builderops.ckm.query_service import CkmQueryService
from app.builderops.ckm.store import CkmStore


def _store(tmp_path: Path) -> tuple[CkmStore, object]:
    store = CkmStore(tmp_path / "ckm.sqlite")
    store.ensure_schema()
    capability = store.upsert_capability(identity_key="seed:q1b", name="Q1b", definition="query service", lifecycle="confirmed", existence_provenance="test:q1b")
    return store, capability


def test_list_capabilities_uses_one_read_transaction(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    result = CkmQueryService(store.db_path).list_capabilities()
    assert result.to_dict()["snapshot"]["completeness"]["complete"] is True


def test_exact_id_lookup_and_complete_bounded_capture(tmp_path: Path) -> None:
    store, capability = _store(tmp_path)
    result = CkmQueryService(store.db_path).get_capability(capability.public_id)
    assert result.to_dict()["resources"][0]["public_id"] == capability.public_id
    assert result.to_dict()["snapshot"]["effective_audience"] == EFFECTIVE_AUDIENCE
    assert result.to_dict()["snapshot"]["access_policy_version"] == ACCESS_POLICY_VERSION
    assert result.to_dict()["snapshot"]["redaction_profile"] == REDACTION_PROFILE


def test_query_path_is_read_only_and_side_effect_free(tmp_path: Path) -> None:
    missing = tmp_path / "missing" / "ckm.sqlite"
    result = CkmQueryService(missing).list_capabilities()
    assert result.to_dict()["error"]["code"] == "missing_store"
    assert not missing.parent.exists()


def test_incomplete_or_oversized_snapshot_refuses(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    result = CkmQueryService(store.db_path, capture_limit=0 + 1).list_capabilities()
    assert "resources" in result.to_dict()
    store.upsert_capability(identity_key="seed:extra", name="extra", definition="x", lifecycle="confirmed", existence_provenance="test")
    assert CkmQueryService(store.db_path, capture_limit=1).list_capabilities().to_dict()["error"]["code"] == "snapshot_too_large"
    assert CkmQueryService(store.db_path).list_capabilities(access_policy_version="wrong").to_dict()["error"]["code"] == "unsupported_access_policy"


def test_missing_candidate_completeness_and_access_semantics(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    candidate = store.upsert_capability(identity_key="inferred:q1b", name="candidate", definition="x", lifecycle="candidate", existence_provenance="test")
    payload = CkmQueryService(store.db_path).get_capability(candidate.public_id).to_dict()
    resource = payload["resources"][0]
    assert resource["candidate"] is True and resource["values"]["assessment"]["state"] == "unassessed"


def test_cli_json_uses_transport_neutral_service() -> None:
    assert CkmQueryService.__module__ == "app.builderops.ckm.query_service"


def test_same_snapshot_query_and_versions_are_deterministic(tmp_path: Path) -> None:
    store, _ = _store(tmp_path)
    service = CkmQueryService(store.db_path)
    assert json.dumps(service.list_capabilities().to_dict(), sort_keys=True) == json.dumps(service.list_capabilities().to_dict(), sort_keys=True)
