"""Read-path identity for create-once notes without a frontmatter uuid (#5660).

A workspace read must never rewrite a create-once note (ADR-0055 note class) and
must not fail because the identity backfill write would be refused. Rewritable
notes keep the existing uuid backfill.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.services.note_uuid as note_uuid_module
from app.api.app import app
from app.ingest.vault_alpha import resolve_vault_note_identity
from app.rebuildability.product_total_loss import parse_bounded_frontmatter
from tests.api._vault_test_helpers import bind_initialized_vault


def _workspace(client: TestClient, note_path: str):
    return client.get("/api/companion/workspace", params={"note_path": note_path})


def _spy_backfill_writes(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    calls: list[Path] = []
    real_write = note_uuid_module.write_note_from_absolute

    def _spy(path, content, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(Path(path))
        return real_write(path, content, **kwargs)

    monkeypatch.setattr(note_uuid_module, "write_note_from_absolute", _spy)
    return calls


def test_workspace_read_of_create_once_note_without_uuid_succeeds_without_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bind_initialized_vault(monkeypatch, tmp_path)
    note = tmp_path / "Sources" / "130-oled-ar-glasses.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    original = "---\ntitle: OLED AR glasses\n---\n\n# OLED AR glasses\n\nSource body.\n"
    note.write_text(original, encoding="utf-8")
    original_stat = note.stat()
    writes = _spy_backfill_writes(monkeypatch)
    client = TestClient(app)

    first = _workspace(client, "Sources/130-oled-ar-glasses.md")
    second = _workspace(client, "Sources/130-oled-ar-glasses.md")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert writes == []
    assert note.read_text(encoding="utf-8") == original
    assert note.stat().st_mtime_ns == original_stat.st_mtime_ns

    frontmatter, body, _ = parse_bounded_frontmatter(original)
    expected = resolve_vault_note_identity(
        note, vault_root=tmp_path, frontmatter=frontmatter, body=body
    ).note_uuid
    artifact = first.json()["artifact"]
    assert artifact["artifact_id"] == expected
    assert artifact["identity_source"] == "recovery_candidate"
    assert artifact["identity_state"] == "recovered"
    assert second.json()["artifact"]["artifact_id"] == expected


def test_rewritable_note_still_gets_uuid_backfill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bind_initialized_vault(monkeypatch, tmp_path)
    note = tmp_path / "notes" / "uuidless.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("---\ntitle: UUIDless\n---\n\n# UUIDless\n\nBody.\n", encoding="utf-8")
    writes = _spy_backfill_writes(monkeypatch)

    resp = _workspace(TestClient(app), "notes/uuidless.md")

    assert resp.status_code == 200, resp.text
    artifact = resp.json()["artifact"]
    assert artifact["identity_source"] == "uuid_healing"
    assert artifact["identity_state"] == "healed"
    assert artifact["artifact_id"]
    assert len(writes) == 1
    assert f"uuid: {artifact['artifact_id']}" in note.read_text(encoding="utf-8")


_PANEL_SOURCE = (
    "---\n"
    "title: Panel source\n"
    "---\n\n"
    "# Panel source\n\n"
    "%% AI:Start %%\n"
    "## AI-instruktion\n"
    "Do the thing.\n"
    "## AI-åtgärder\n"
    "- [ ] Send email <!--ai:option_id=opt_abc--> <!--ai:id=send.email--> <!--ai:proposed=979-->\n"
    "%% AI:End %%\n"
)


def test_checkbox_projection_refuses_uuidless_create_once_note_without_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recovered (never written) identity must not authorize a mutation (#5663 P1)."""
    import app.panel.checkbox_projection as projection_module
    from app.api.routes.artifacts import _content_hash
    from app.panel.checkbox_projection import extract_panel_selectable_options
    from app.write_guard import DEFAULT_WRITE_GUARD

    bind_initialized_vault(monkeypatch, tmp_path)
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "rule")
    projection_module._idempotency_store.clear()
    monkeypatch.setattr(projection_module._service, "_guard", DEFAULT_WRITE_GUARD)
    monkeypatch.setattr(projection_module, "run_panel_note_execution", lambda *a, **k: None)
    note = tmp_path / "Sources" / "panel-source.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(_PANEL_SOURCE, encoding="utf-8")
    original_bytes = note.read_bytes()
    client = TestClient(app)

    workspace = _workspace(client, "Sources/panel-source.md")
    assert workspace.status_code == 200, workspace.text
    # The read path never offers a mutation affordance for an unwritten identity.
    assert workspace.json()["panel"]["selectable_options"] == []

    frontmatter, body, _ = parse_bounded_frontmatter(_PANEL_SOURCE)
    recovered_id = resolve_vault_note_identity(
        note, vault_root=tmp_path, frontmatter=frontmatter, body=body
    ).note_uuid
    option = extract_panel_selectable_options(
        _PANEL_SOURCE,
        artifact_id=recovered_id,
        note_path="Sources/panel-source.md",
        content_hash=_content_hash(_PANEL_SOURCE),
    )[0]
    resp = client.post(
        "/api/panel/checkbox-projection",
        json={
            "artifact_id": recovered_id,
            "note_path": "Sources/panel-source.md",
            "panel_id": option.panel_id,
            "option_id": option.option_id,
            "expected_content_hash": option.content_hash,
            "expected_source_hash": option.source_hash,
            "idempotency_key": "idem-create-once",
        },
    )
    projection_module._idempotency_store.clear()

    assert resp.status_code != 200, resp.text
    assert note.read_bytes() == original_bytes
