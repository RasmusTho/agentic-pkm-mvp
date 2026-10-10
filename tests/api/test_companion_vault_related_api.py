"""Read-only artifact-scoped Find API for Vault Browser find_related (#1282)."""

from __future__ import annotations

from pathlib import Path

import pytest
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


@pytest.mark.parametrize("system_dir", ["⚙️ System", "00 Infrastructure/System"])
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("alias", [False, True])
def test_vault_related_uuid_scope_prefers_genuine_human_source_over_companion(
    tmp_path: Path, monkeypatch, system_dir: str, legacy: bool, alias: bool
) -> None:
    bind_selected_vault(monkeypatch, tmp_path)
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", system_dir)
    target_uuid = "00000000-0000-0000-0000-000000005933"
    human_path = "🧠 Notes/human.md"
    companion_path = f"{'_system' if legacy else system_dir}/companions/{target_uuid}.md"
    _write_note(tmp_path / human_path, title="Human source", uuid=target_uuid)
    _write_note(tmp_path / companion_path, title="Continuity", uuid=target_uuid)
    if alias:
        (tmp_path / "a-companion.md").symlink_to(tmp_path / companion_path)
        companion_path = "a-companion.md"
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.md")}
    client = TestClient(app)

    response = client.get("/api/companion/vault-related", params={"artifact_uuid": target_uuid})
    assert response.status_code == 200
    assert response.json()["scope"] == {"note_path": human_path, "artifact_uuid": target_uuid}
    assert response.json()["read_only"] is True

    matching = client.get(
        "/api/companion/vault-related",
        params={"note_path": human_path, "artifact_uuid": target_uuid},
    )
    assert matching.status_code == 200
    inspection = client.get("/api/companion/vault-related", params={"note_path": companion_path})
    assert inspection.status_code == 200
    assert inspection.json()["scope"] == {"note_path": companion_path, "artifact_uuid": None}
    assert inspection.json()["data_mode"] == "read_only"
    mismatch = client.get(
        "/api/companion/vault-related",
        params={"note_path": companion_path, "artifact_uuid": target_uuid},
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["error"] == "artifact_scope_mismatch"
    assert {path: path.read_bytes() for path in tmp_path.rglob("*.md")} == before


@pytest.mark.parametrize("include_path", [False, True])
def test_vault_related_rejects_ambiguous_human_uuid_scope(
    tmp_path: Path, monkeypatch, include_path: bool
) -> None:
    bind_selected_vault(monkeypatch, tmp_path)
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "00 Infrastructure/System")
    target_uuid = "duplicate-human-5933"
    for note_path in ("notes/first.md", "notes/second.md", "00 Infrastructure/System/companions/retained.md"):
        _write_note(tmp_path / note_path, title="Duplicate", uuid=target_uuid)
    params = {"artifact_uuid": target_uuid}
    if include_path:
        params["note_path"] = "notes/first.md"

    response = TestClient(app).get("/api/companion/vault-related", params=params)

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "artifact_uuid_conflict"
    assert response.json()["detail"]["artifact_uuid"] == target_uuid


@pytest.mark.parametrize("artifact_uuid", ["companion-only-5933", "missing-5933"])
def test_vault_related_rejects_uuid_without_genuine_human_source(
    tmp_path: Path, monkeypatch, artifact_uuid: str
) -> None:
    bind_selected_vault(monkeypatch, tmp_path)
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "00 Infrastructure/System")
    _write_note(
        tmp_path / "00 Infrastructure/System/companions/retained.md",
        title="Continuity", uuid="companion-only-5933",
    )

    response = TestClient(app).get("/api/companion/vault-related", params={"artifact_uuid": artifact_uuid})

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "artifact_not_found"


def test_vault_related_preserves_uninitialized_deep_human_and_uuidless_path_reads(
    tmp_path: Path, monkeypatch
) -> None:
    bind_selected_vault(monkeypatch, tmp_path)
    monkeypatch.delenv("VAULT_SYSTEM_DIR_REL", raising=False)
    _write_note(tmp_path / "notes/deep/human.md", title="Human", uuid="deep-human-5933")
    uuidless = tmp_path / "notes/deep/uuidless.md"
    uuidless.write_text("# UUID-less human\n\nBody.\n", encoding="utf-8")
    before = uuidless.read_bytes()
    client = TestClient(app)

    human = client.get("/api/companion/vault-related", params={"artifact_uuid": "deep-human-5933"})
    inspection = client.get("/api/companion/vault-related", params={"note_path": "notes/deep/uuidless.md"})

    assert human.status_code == 200
    assert human.json()["scope"]["note_path"] == "notes/deep/human.md"
    assert inspection.status_code == 200
    assert inspection.json()["scope"]["artifact_uuid"] is None
    assert uuidless.read_bytes() == before


@pytest.mark.parametrize("note_path", [None, "notes/human.md", "a-alias.md"])
def test_vault_related_human_symlink_alias_is_one_uuid_source(
    tmp_path: Path, monkeypatch, note_path: str | None
) -> None:
    bind_selected_vault(monkeypatch, tmp_path)
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "00 Infrastructure/System")
    _write_note(tmp_path / "notes/human.md", title="Human", uuid="human-alias-5933")
    (tmp_path / "a-alias.md").symlink_to(tmp_path / "notes/human.md")
    companion = tmp_path / "00 Infrastructure/System/companions/retained.md"
    companion.parent.mkdir(parents=True)
    companion.symlink_to(tmp_path / "notes/human.md")
    params = {"artifact_uuid": "human-alias-5933"}
    if note_path:
        params["note_path"] = note_path

    response = TestClient(app).get("/api/companion/vault-related", params=params)

    assert response.status_code == 200
    assert response.json()["scope"] == {"note_path": "notes/human.md", "artifact_uuid": "human-alias-5933"}
    mismatch = TestClient(app).get(
        "/api/companion/vault-related",
        params={"note_path": companion.relative_to(tmp_path).as_posix(), "artifact_uuid": "human-alias-5933"},
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["error"] == "artifact_scope_mismatch"
