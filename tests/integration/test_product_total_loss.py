"""RSC-02: Product object projection refuses unverified total loss."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app
from app.rebuildability import (
    PRODUCT_REPLAY_RECIPE_VERSION,
    ProductReplayRefusal,
    evaluate_product_store_readiness,
    product_replay_provenance,
)


def _write_source(vault_root: Path, text: str = "Meaning-bearing Product note.") -> str:
    path = vault_root / "Notes" / "product.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ntitle: Product\n---\n\n{text}\n", encoding="utf-8")
    return "Notes/product.md"


def _verified_row(source_identity: str, text: str) -> dict[str, object]:
    return {
        "object_id": "00000000-0000-0000-0000-000000000001",
        "kind": "note",
        "source_ref": source_identity,
        "payload": {
            "text": text,
            "replay": product_replay_provenance(
                source_identity=source_identity,
                source_text=text,
            ),
        },
    }


def test_empty_or_corrupt_store_is_unready_until_verified_rebuild(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    source_identity = _write_source(vault_root)

    empty = evaluate_product_store_readiness(vault_root, [])
    assert empty.ready is False
    assert empty.state == "refused"
    assert "reconstruction" in empty.reason

    corrupt = _verified_row(source_identity, "Meaning-bearing Product note.")
    corrupt_payload = corrupt["payload"]
    assert isinstance(corrupt_payload, dict)
    corrupt_payload["replay"] = {
        "source_identity": source_identity,
        "source_generation": "wrong-generation",
        "recipe_version": PRODUCT_REPLAY_RECIPE_VERSION,
    }
    refused = evaluate_product_store_readiness(vault_root, [corrupt])
    assert refused.ready is False
    assert refused.state == "refused"

    verified = evaluate_product_store_readiness(
        vault_root,
        [_verified_row(source_identity, "Meaning-bearing Product note.")],
    )
    assert verified.ready is True
    assert verified.state == "ready"


def test_retained_sources_reproduce_canonical_meaning_after_total_loss(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    source_identity = _write_source(vault_root, "Canonical meaning survives machine loss.")

    result = evaluate_product_store_readiness(
        vault_root,
        [_verified_row(source_identity, "Canonical meaning survives machine loss.")],
    )
    assert result.ready is True
    assert result.source_count == 1
    assert result.projection_count == 1

    changed = _verified_row(source_identity, "Different meaning.")
    original_tuple = product_replay_provenance(
        source_identity=source_identity,
        source_text="Canonical meaning survives machine loss.",
    )
    changed_payload = changed["payload"]
    assert isinstance(changed_payload, dict)
    changed_payload["replay"] = original_tuple
    refused = evaluate_product_store_readiness(vault_root, [changed])
    assert refused.ready is False
    assert source_identity in refused.refused_source_identities


def test_missing_replay_tuple_refuses_without_fallback(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    source_identity = _write_source(vault_root)
    row = {
        "payload": {"text": "Meaning-bearing Product note."},
        "source_ref": source_identity,
    }

    result = evaluate_product_store_readiness(vault_root, [row])
    assert result.ready is False
    assert result.state == "refused"
    assert "projection-row" in result.refused_source_identities

    try:
        product_replay_provenance(source_identity=source_identity, source_text="")
    except ProductReplayRefusal as exc:
        assert "meaning-bearing" in str(exc)
    else:  # pragma: no cover - defensive assertion for the typed refusal contract
        raise AssertionError("empty source must not receive a replay tuple")


def test_selected_postgres_health_refuses_unverified_product_projection(
    tmp_path: Path, monkeypatch
) -> None:
    """The production readiness contract turns the typed refusal into /readyz red."""
    from app.health_contract import HealthContract, HealthStateMachine

    vault_root = tmp_path / "vault"
    source_identity = _write_source(vault_root)
    rows: list[dict[str, object]] = []

    class FakeStore:
        def count_objects(self, kind=None) -> int:
            del kind
            return len(rows)

        def list_objects(self, kind=None, *, limit=None):
            del kind, limit
            return list(rows)

    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    monkeypatch.setattr("app.health_contract.resolve_store_backend", lambda: "pg")
    monkeypatch.setattr("app.health_contract.get_object_store", lambda: FakeStore())
    monkeypatch.setattr("app.health_contract.diagnose_index", lambda: {
        "backend": "mock",
        "expected_identity": None,
        "stored_identity": None,
        "issues": [],
        "warnings": [],
    })
    monkeypatch.setattr(
        "app.health_contract._dead_letter_stats_db",
        lambda _resolution: {
            "dead_lettered_count": 0,
            "oldest_undelivered_age_seconds": 0.0,
        },
    )

    contract = HealthContract(
        state_machine=HealthStateMachine(),
        vault_root_fn=lambda: vault_root,
        db_ping_fn=lambda **_kwargs: (True, "postgres reachable"),
    )
    monkeypatch.setattr("app.api.routes.health_contract.DEFAULT_CONTRACT", contract)
    refused = contract.evaluate()
    assert refused["state"] != "unhealthy"
    assert refused["product_readiness"]["ready"] is False
    assert TestClient(app).get("/readyz").status_code == 503

    rows.append(_verified_row(source_identity, "Meaning-bearing Product note."))
    verified = contract.evaluate()
    assert verified["state"] != "unhealthy"
    assert verified["product_readiness"]["state"] == "ready"
    assert TestClient(app).get("/readyz").status_code == 200
