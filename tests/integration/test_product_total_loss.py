"""RSC-02: Product object projection refuses unverified total loss."""

from __future__ import annotations

import uuid
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

from app.ingest.vault_alpha import _VAULT_NOTE_UUID_NAMESPACE


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
        "object_id": str(uuid.uuid5(_VAULT_NOTE_UUID_NAMESPACE, source_identity)),
        "kind": "note",
        "source_ref": source_identity,
        "payload": {
            "title": (
                Path(source_identity).stem.replace("-", " ").title()
            ),
            "review_state": "provisional",
            "episode_ref": "unbound",
            "text": text,
            "replay": product_replay_provenance(
                source_identity=source_identity,
                source_text=text,
            ),
        },
    }


def test_readiness_rejects_persisted_locator_that_disagrees_with_replay(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    source_identity = _write_source(vault_root)
    row = _verified_row(source_identity, "Meaning-bearing Product note.")
    row["source_ref"] = "Notes/other.md"

    result = evaluate_product_store_readiness(vault_root, [row])

    assert result.ready is False


def test_readiness_normalizes_legacy_review_state(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    source_identity = _write_source(vault_root, "Meaning-bearing Product note.")
    (vault_root / source_identity).write_text(
        "---\ntitle: Product\nreview_state: evergreen\n---\n\nMeaning-bearing Product note.\n",
        encoding="utf-8",
    )
    row = _verified_row(source_identity, "Meaning-bearing Product note.")
    row["payload"]["review_state"] = "evergreen"  # type: ignore[index]

    result = evaluate_product_store_readiness(vault_root, [row])

    assert result.ready is True


@pytest.mark.parametrize(
    ("field", "value"),
    [("title", "Wrong title"), ("review_state", "approved"), ("episode_ref", ["episode-1"])],
)
def test_product_readiness_rejects_meaningful_metadata_drift(
    tmp_path: Path, field: str, value: object
) -> None:
    vault_root = tmp_path / "vault"
    source_identity = _write_source(vault_root)
    row = _verified_row(source_identity, "Meaning-bearing Product note.")
    payload = row["payload"]
    assert isinstance(payload, dict)
    payload[field] = value

    result = evaluate_product_store_readiness(vault_root, [row])

    assert result.ready is False
    assert source_identity in result.refused_source_identities


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


def test_product_readiness_ignores_replayless_non_retained_rows(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    source_identity = _write_source(vault_root)
    retained = _verified_row(source_identity, "Meaning-bearing Product note.")
    unrelated = {
        "kind": "note",
        "source_ref": str(vault_root / "Legacy" / "old.md"),
        "payload": {"text": "Legacy projection without replay provenance."},
    }

    result = evaluate_product_store_readiness(vault_root, [retained, unrelated])

    assert result.ready is True


def test_product_readiness_accepts_admitted_empty_source_projection(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    source_identity = _write_source(vault_root, "")
    row = {
        "object_id": str(uuid.uuid5(_VAULT_NOTE_UUID_NAMESPACE, source_identity)),
        "kind": "note",
        "source_ref": source_identity,
        "payload": {
            "title": "Product",
            "review_state": "provisional",
            "episode_ref": "unbound",
            "text": "",
            "replay": product_replay_provenance(
                source_identity=source_identity,
                source_text="",
                allow_empty_source=True,
            ),
        },
    }

    result = evaluate_product_store_readiness(vault_root, [row])

    assert result.ready is True


def test_product_readiness_rejects_wrong_canonical_object_id(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    source_identity = _write_source(vault_root)
    row = _verified_row(source_identity, "Meaning-bearing Product note.")
    row["object_id"] = "00000000-0000-0000-0000-000000000001"

    result = evaluate_product_store_readiness(vault_root, [row])

    assert result.ready is False
    assert source_identity in result.refused_source_identities


def test_product_readiness_rejects_duplicate_retained_uuid_claims(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    first_identity = _write_source(vault_root, "First retained note.")
    shared_uuid = str(uuid.uuid4())
    first = vault_root / first_identity
    second = vault_root / "Notes" / "second.md"
    for path in (first, second):
        path.write_text(
            f"---\nuuid: {shared_uuid}\ntitle: Duplicate\n---\n\n{path.stem} body.\n",
            encoding="utf-8",
        )

    result = evaluate_product_store_readiness(vault_root, [])

    assert result.ready is False
    assert result.state == "refused"
    assert any(
        item.startswith("duplicate-retained-vault-uuid:")
        for item in result.refused_source_identities
    )


def test_product_readiness_dedupes_overlapping_include_folders(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    source_identity = "Notes/Active/product.md"
    layout = vault_root / "⚙️ System" / "vault.layout.md"
    layout.parent.mkdir(parents=True, exist_ok=True)
    layout.write_text(
        "---\nsystem_folder: ⚙️ System\ninclude_folders:\n"
        "  - Notes\n  - Notes/Active\n  - Notes\n---\n",
        encoding="utf-8",
    )
    note = vault_root / source_identity
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\ntitle: Product\n---\n\nMeaning-bearing Product note.\n",
        encoding="utf-8",
    )

    result = evaluate_product_store_readiness(
        vault_root,
        [_verified_row(source_identity, "Meaning-bearing Product note.")],
    )

    assert result.ready is True
    assert result.source_count == 1


def test_product_readiness_loads_canonical_identity_map_once_per_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.rebuildability import product_total_loss

    vault_root = tmp_path / "vault"
    first_identity = _write_source(vault_root, "First retained note.")
    second = vault_root / "Notes" / "second.md"
    second.write_text("---\ntitle: Second\n---\n\nSecond retained note.\n", encoding="utf-8")
    calls: list[tuple[str, ...]] = []

    def fake_map(vault_uuids):  # type: ignore[no-untyped-def]
        values = tuple(vault_uuids)
        calls.append(values)
        return {value: value for value in values}

    monkeypatch.setattr(product_total_loss, "_canonical_object_ids_for_sources", fake_map)

    result = evaluate_product_store_readiness(
        vault_root,
        [
            _verified_row(first_identity, "First retained note."),
            _verified_row("Notes/second.md", "Second retained note."),
        ],
    )

    assert result.ready is True
    assert len(calls) == 1
    assert set(calls[0]) == {
        str(uuid.uuid5(_VAULT_NOTE_UUID_NAMESPACE, first_identity)),
        str(uuid.uuid5(_VAULT_NOTE_UUID_NAMESPACE, "Notes/second.md")),
    }


def test_product_readiness_uses_objects_boundary_for_identity_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from app.rebuildability import product_total_loss

    calls: list[str] = []
    binding = SimpleNamespace(
        backend="pg",
        store=SimpleNamespace(vault_binding_id="binding-for-test"),
    )

    monkeypatch.setattr(product_total_loss, "resolve_object_store_port", lambda: binding)
    monkeypatch.setattr(
        product_total_loss,
        "retained_vault_uuid_to_canonical_id_map",
        lambda *, vault_binding_id: calls.append(vault_binding_id) or {"vault-1": "object-1"},
    )

    assert product_total_loss._canonical_object_ids_for_sources(["vault-1"]) == {
        "vault-1": "object-1"
    }
    assert calls == ["binding-for-test"]


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

    assert canonical_note_replay(
        note, vault_root=vault_root, source_body=""
    ) == product_replay_provenance(
        source_identity="Notes/product.md", source_text="", allow_empty_source=True
    )


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
        "object_id": str(uuid.uuid5(_VAULT_NOTE_UUID_NAMESPACE, source_identity)),
        "kind": "note",
        "payload": {
            "title": "Product",
            "review_state": "provisional",
            "episode_ref": "unbound",
            "content": body,
            "replay": product_replay_provenance(
                source_identity=source_identity,
                source_text=body,
            ),
        },
    }

    assert evaluate_product_store_readiness(vault_root, [row]).ready is True


def test_readiness_preserves_vault_alpha_extracted_body_semantics(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    source_identity = _write_source(vault_root, "---\nA thematic section\n---\n\nMeaning-bearing suffix.")
    body = "---\nA thematic section\n---\n\nMeaning-bearing suffix."
    row = {
        "object_id": str(uuid.uuid5(_VAULT_NOTE_UUID_NAMESPACE, source_identity)),
        "kind": "note",
        "payload": {
            "title": "Product",
            "review_state": "provisional",
            "episode_ref": "unbound",
            "text": body,
            "replay_text_kind": "extracted_body",
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
    monkeypatch.setattr(
        "app.rebuildability.product_total_loss._canonical_object_ids_for_sources",
        lambda values: {value: value for value in values},
    )
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
