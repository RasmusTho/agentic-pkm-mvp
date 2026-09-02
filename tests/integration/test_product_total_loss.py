"""RSC-02: Product object projection refuses unverified total loss."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.rebuildability import (
    PRODUCT_REPLAY_RECIPE_VERSION,
    ProductReplayRefusal,
    evaluate_product_store_readiness,
    product_replay_provenance,
)
from app.write_guard import WriteGuard, WritesBlockedError


def _write_source(vault_root: Path, text: str = "Meaning-bearing Product note.") -> str:
    layout = vault_root / "⚙️ System" / "vault.layout.md"
    layout.parent.mkdir(parents=True, exist_ok=True)
    layout.write_text(
        "---\nsystem_folder: ⚙️ System\ninbox_folder: 📥 Inbox\ndesk_folder: 🛠️ Workbench\n"
        "include_folders:\n  - Notes\n---\n\nProduct total-loss fixture layout.\n",
        encoding="utf-8",
    )
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


def test_product_readiness_ignores_ingest_excluded_files(tmp_path: Path) -> None:
    """The retained inventory is the same candidate set as vault-alpha ingest."""
    vault_root = tmp_path / "vault"
    source_identity = _write_source(vault_root)
    (vault_root / "⚙️ System" / "companions").mkdir(parents=True)
    (vault_root / "⚙️ System" / "companions" / "note.meta.md").write_text(
        "companion", encoding="utf-8"
    )
    (vault_root / "⚙️ System" / "drafts").mkdir(parents=True)
    (vault_root / "⚙️ System" / "drafts" / "candidate.md").write_text(
        "draft", encoding="utf-8"
    )
    (vault_root / "Test").mkdir()
    (vault_root / "Test" / "Alpha-HumanFlows.md").write_text("test note", encoding="utf-8")

    result = evaluate_product_store_readiness(
        vault_root,
        [_verified_row(source_identity, "Meaning-bearing Product note.")],
    )

    assert result.ready is True
    assert result.source_count == 1


def test_product_readiness_ignores_projection_for_source_removed_from_policy(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    source_identity = _write_source(vault_root)
    layout = vault_root / "⚙️ System" / "vault.layout.md"
    layout.write_text(
        "---\nsystem_folder: ⚙️ System\ninbox_folder: 📥 Inbox\n"
        "desk_folder: 🛠️ Workbench\ninclude_folders:\n  - Other\n---\n\n"
        "Source removed from retained policy.\n",
        encoding="utf-8",
    )

    result = evaluate_product_store_readiness(
        vault_root,
        [_verified_row(source_identity, "Meaning-bearing Product note.")],
    )

    assert result.ready is True
    assert result.state == "empty"
    assert result.source_count == 0


def test_source_backed_rebuild_is_reachable_while_unready() -> None:
    """Only the named source-backed reconstruction admission bypasses the guard."""
    from app.write_guard import SOURCE_BACKED_REBUILD_ACTION

    guard = WriteGuard(snapshot_fn=lambda: {"state": "unhealthy", "reason": "unready"})

    guard.assert_writes_allowed(SOURCE_BACKED_REBUILD_ACTION)
    try:
        guard.assert_writes_allowed("ordinary.unrelated_write")
    except WritesBlockedError:
        pass
    else:  # pragma: no cover - guard regression diagnostic
        raise AssertionError("ordinary write must remain guarded while Product is unready")


def test_sync_markdown_requires_explicit_source_backed_rebuild_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The production sync seam guards ordinary UUID repair but admits recovery explicitly."""
    from app.services import vault_sync
    from app.write_guard import SOURCE_BACKED_REBUILD_ACTION

    vault_root = tmp_path / "vault"
    note_path = vault_root / "Notes" / "product.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text("---\ntitle: Product\n---\n\nBody\n", encoding="utf-8")

    blocked_guard = WriteGuard(
        snapshot_fn=lambda: {"state": "unhealthy", "reason": "product projection unready"}
    )
    monkeypatch.setattr(vault_sync, "DEFAULT_WRITE_GUARD", blocked_guard)

    with pytest.raises(WritesBlockedError):
        vault_sync.sync_markdown(str(note_path), vault_root=vault_root)
    assert "uuid:" not in note_path.read_text(encoding="utf-8")

    captured: dict[str, object] = {}

    def fake_write_note_from_absolute(
        path: Path | str, content: str, *, vault_root: Path, action: str
    ) -> None:
        captured.update(vault_root=vault_root, action=action)
        Path(path).write_text(content, encoding="utf-8")

    class RecoveryReached(RuntimeError):
        pass

    monkeypatch.setattr(vault_sync, "write_note_from_absolute", fake_write_note_from_absolute)
    monkeypatch.setattr(
        vault_sync,
        "canonical_note_replay",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RecoveryReached),
    )

    with pytest.raises(RecoveryReached):
        vault_sync.sync_markdown_source_backed_rebuild(
            str(note_path), vault_root=vault_root
        )

    assert captured["action"] == SOURCE_BACKED_REBUILD_ACTION
    assert "uuid:" in note_path.read_text(encoding="utf-8")


def test_canonical_ingest_producers_stamp_replay_tuple(tmp_path: Path) -> None:
    """The three bounded canonical producer payload builders share one valid tuple shape."""
    from app.ingest.vault_alpha import product_replay_for_vault_note as alpha_replay
    from app.ingest.vault_root import product_replay_for_vault_note
    from app.services.vault_sync import canonical_note_replay

    vault_root = tmp_path / "vault"
    note = vault_root / "Notes" / "product.md"
    note.parent.mkdir(parents=True)
    note.write_text("Meaning-bearing Product note.", encoding="utf-8")
    expected = product_replay_provenance(
        source_identity="Notes/product.md", source_text="Meaning-bearing Product note."
    )

    assert alpha_replay(note, vault_root=vault_root) == expected
    assert product_replay_for_vault_note(note, vault_root=vault_root) == expected
    assert canonical_note_replay(note, vault_root=vault_root) == expected


def test_vault_sync_replay_canonicalizes_extracted_thematic_body(tmp_path: Path) -> None:
    from app.rebuildability import canonical_product_body_text
    from app.services.vault_sync import canonical_note_replay

    vault_root = tmp_path / "vault"
    note = vault_root / "thematic.md"
    note.parent.mkdir(parents=True)
    body = "---\nA thematic section\n---\n\nMeaning-bearing suffix."
    note.write_text(f"---\nuuid: thematic-uuid\n---\n\n{body}", encoding="utf-8")

    assert canonical_note_replay(
        note, vault_root=vault_root, source_body=body
    ) == product_replay_provenance(
        source_identity="thematic.md",
        source_text=canonical_product_body_text(body),
    )


def test_readiness_preserves_watcher_extracted_body_semantics(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    source_identity = _write_source(vault_root, "---\nA thematic section\n---\n\nMeaning-bearing suffix.")
    body = "---\nA thematic section\n---\n\nMeaning-bearing suffix."
    row = {
        "kind": "note",
        "payload": {
            "content": body,
            "replay": product_replay_provenance(
                source_identity=source_identity,
                source_text=body,
            ),
        },
    }

    assert evaluate_product_store_readiness(vault_root, [row]).ready is True


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
