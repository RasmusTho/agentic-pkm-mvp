"""Read-only artifact-scoped Find API for Vault Browser find_related (#1282)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app
from tests.api._vault_test_helpers import bind_selected_vault


def _write_note(
    path: Path,
    *,
    title: str,
    uuid: str,
    tags: list[str] | None = None,
    zone: str = "notes",
    source_ref: str | None = None,
    body: str = "Body.\n",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tag_lines = "".join(f"  - {tag}\n" for tag in tags or [])
    source_ref_line = f"source_ref: {source_ref}\n" if source_ref else ""
    path.write_text(
        (
            "---\n"
            f"title: {title}\n"
            f"uuid: {uuid}\n"
            "kind: human_note\n"
            f"zone: {zone}\n"
            f"{source_ref_line}"
            "tags:\n"
            f"{tag_lines}"
            "---\n\n"
            f"{body}"
        ),
        encoding="utf-8",
    )


def test_vault_related_returns_read_only_artifact_scoped_signals(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bind_selected_vault(monkeypatch, tmp_path)
    target_uuid = "00000000-0000-0000-0000-000000001282"
    related_uuid = "00000000-0000-0000-0000-000000001283"
    tag_only_uuid = "00000000-0000-0000-0000-000000001284"
    _write_note(
        tmp_path / "notes" / "current.md",
        title="Current",
        uuid=target_uuid,
        tags=["alpha", "pkm"],
        body="See [[Related Target]] for context.\n",
    )
    _write_note(
        tmp_path / "notes" / "related.md",
        title="Related Target",
        uuid=related_uuid,
        tags=["alpha"],
        body="Backlink to [[Current]].\n",
    )
    _write_note(
        tmp_path / "notes" / "tag-only.md",
        title="Tag Only",
        uuid=tag_only_uuid,
        tags=["pkm"],
        body="Shares only a tag.\n",
    )
    _write_note(
        tmp_path / "other" / "unrelated.md",
        title="Unrelated",
        uuid="00000000-0000-0000-0000-000000001285",
        tags=["other"],
        zone="other",
        body="No relation.\n",
    )

    resp = TestClient(app).get(
        "/api/companion/vault-related",
        params={"note_path": "notes/current.md"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["read_only"] is True
    assert data["data_mode"] == "read_only"
    assert data["scope"] == {
        "note_path": "notes/current.md",
        "artifact_uuid": target_uuid,
    }
    paths = [result["note_path"] for result in data["results"]]
    assert paths[:2] == ["notes/related.md", "notes/tag-only.md"]
    assert "other/unrelated.md" not in paths
    scores = [result["ranking_score"] for result in data["results"]]
    assert scores == sorted(scores, reverse=True)

    related = data["results"][0]
    assert related["data_mode"] == "read_only"
    assert related["artifact_uuid"] == related_uuid
    signals = related["ranking_signals"]
    assert {signal["signal"] for signal in signals} >= {
        "wikilink_outlink",
        "wikilink_backlink",
        "shared_tag",
    }
    for signal in signals:
        assert set(signal) == {"signal", "value", "weight", "provenance"}
        assert signal["weight"] > 0
        assert signal["provenance"]


def test_vault_related_accepts_artifact_uuid_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bind_selected_vault(monkeypatch, tmp_path)
    target_uuid = "00000000-0000-0000-0000-000000001286"
    _write_note(
        tmp_path / "notes" / "current.md",
        title="Current",
        uuid=target_uuid,
        tags=["alpha"],
    )
    _write_note(
        tmp_path / "notes" / "related.md",
        title="Related",
        uuid="00000000-0000-0000-0000-000000001287",
        tags=["alpha"],
    )

    resp = TestClient(app).get(
        "/api/companion/vault-related",
        params={"artifact_uuid": target_uuid},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["scope"]["note_path"] == "notes/current.md"
    assert data["scope"]["artifact_uuid"] == target_uuid
    assert data["results"][0]["note_path"] == "notes/related.md"


def test_vault_related_exposes_link_relation_provenance_for_inspector(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bind_selected_vault(monkeypatch, tmp_path)
    _write_note(
        tmp_path / "notes" / "current.md",
        title="Current",
        uuid="00000000-0000-0000-0000-000000001470",
        body="See [[Related]].\n",
    )
    _write_note(
        tmp_path / "notes" / "related.md",
        title="Related",
        uuid="00000000-0000-0000-0000-000000001471",
        body="Backlink to [[Current]].\n",
    )

    resp = TestClient(app).get(
        "/api/companion/vault-related",
        params={"note_path": "notes/current.md"},
    )

    assert resp.status_code == 200
    signals = resp.json()["results"][0]["ranking_signals"]
    assert signals
    assert {signal["signal"] for signal in signals} >= {
        "wikilink_outlink",
        "wikilink_backlink",
    }
    assert all(signal["provenance"] for signal in signals)


def test_vault_related_requires_artifact_scope(tmp_path: Path, monkeypatch) -> None:
    bind_selected_vault(monkeypatch, tmp_path)

    resp = TestClient(app).get("/api/companion/vault-related")

    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "artifact_scope_required"


def test_vault_related_is_read_only(tmp_path: Path, monkeypatch) -> None:
    bind_selected_vault(monkeypatch, tmp_path)
    note_path = tmp_path / "notes" / "current.md"
    _write_note(
        note_path,
        title="Current",
        uuid="00000000-0000-0000-0000-000000001288",
        tags=["alpha"],
    )
    before = note_path.read_text(encoding="utf-8")

    resp = TestClient(app).post(
        "/api/companion/vault-related",
        json={"note_path": "notes/current.md"},
    )

    assert resp.status_code == 405
    assert note_path.read_text(encoding="utf-8") == before
