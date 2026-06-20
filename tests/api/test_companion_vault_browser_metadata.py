"""Vault Browser normalized artifact metadata read model — contract tests.

Covers #1253 Acceptance Criteria:
- AC1: Browser API returns normalized artifact metadata for notes with valid frontmatter.
- AC2: Browser API returns explicit health state for notes with missing/invalid frontmatter.
- AC3: Browser payload distinguishes artifact metadata from vault/channel identity.
- AC6: Existing path/title filtering still works (covered by existing test_companion_vault_browser_api.py).

Server owns frontmatter parsing. Client never receives raw YAML.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app
from tests.api._vault_test_helpers import bind_selected_vault


def _write_note(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _full_frontmatter_note(title: str = "Test Note") -> str:
    return (
        "---\n"
        f"uuid: abc-123\n"
        f"title: {title}\n"
        "kind: human_note\n"
        "zone: active\n"
        "review_state: needs_review\n"
        "trust: assert\n"
        "origin: vault\n"
        "source_ref: notes/test-note.md\n"
        "created: 2026-01-01T00:00:00Z\n"
        "updated: 2026-05-01T00:00:00Z\n"
        "---\n\n"
        "Body text.\n"
    )


def _uuid_only_note(title: str = "UUID Only") -> str:
    return (
        "---\n"
        "uuid: uuid-only-abc\n"
        f"title: {title}\n"
        "---\n\n"
        "Body.\n"
    )


def _no_frontmatter_note(title: str = "No Frontmatter") -> str:
    return f"# {title}\n\nBody with no YAML frontmatter.\n"


def _malformed_frontmatter_note() -> str:
    return (
        "---\n"
        "uuid: [broken\n"
        "title: Broken Note\n"
        "---\n\n"
        "Body.\n"
    )


class TestReadModelReturnsExpectedFieldsForHealthyNote:
    def test_all_core_fields_present_when_frontmatter_complete(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        bind_selected_vault(monkeypatch, tmp_path)
        _write_note(tmp_path / "notes" / "complete.md", _full_frontmatter_note("Complete Note"))

        client = TestClient(app)
        resp = client.get("/api/companion/vault-browser")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["notes"]) == 1
        note = data["notes"][0]

        # Core identity fields
        assert note["uuid"] == "abc-123"
        assert note["title"] == "Complete Note"
        assert note["kind"] == "human_note"
        assert note["zone"] == "active"
        assert note["review_state"] == "needs_review"
        assert note["trust"] == "assert"
        assert note["origin"] == "vault"
        assert note["source_ref"] == "notes/test-note.md"
        # YAML parses ISO datetimes; isoformat() representation may differ from source
        assert note["created"] is not None and "2026-01-01" in note["created"]
        assert note["updated"] is not None and "2026-05-01" in note["updated"]

        # Health state
        assert note["frontmatter_valid"] is True
        assert note["missing_required_fields"] == []

    def test_uuid_only_note_has_health_state_with_missing_fields(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        bind_selected_vault(monkeypatch, tmp_path)
        _write_note(tmp_path / "notes" / "uuid-only.md", _uuid_only_note())

        client = TestClient(app)
        resp = client.get("/api/companion/vault-browser")

        assert resp.status_code == 200
        data = resp.json()
        note = data["notes"][0]

        # uuid is present; other optional fields are absent/null
        assert note["uuid"] == "uuid-only-abc"
        assert note["kind"] is None
        assert note["zone"] == "notes"  # path-derived zone fallback
        assert note["review_state"] is None
        assert note["trust"] is None
        assert note["frontmatter_valid"] is True  # valid YAML, uuid present
        assert note["missing_required_fields"] == []


class TestInvalidFrontmatterSurfacesHealthState:
    def test_blank_uuid_is_invalid_after_normalization(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        bind_selected_vault(monkeypatch, tmp_path)
        _write_note(
            tmp_path / "notes" / "blank-uuid.md",
            "---\nuuid: '   '\ntitle: Blank UUID\n---\n\nBody.\n",
        )
        resp = TestClient(app).get("/api/companion/vault-browser")
        note = resp.json()["notes"][0]
        assert note["uuid"] is None
        assert note["frontmatter_valid"] is False
        assert "uuid" in note["missing_required_fields"]

    def test_no_frontmatter_surfaces_missing_uuid(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        bind_selected_vault(monkeypatch, tmp_path)
        _write_note(tmp_path / "notes" / "no-fm.md", _no_frontmatter_note())

        client = TestClient(app)
        resp = client.get("/api/companion/vault-browser")

        assert resp.status_code == 200
        data = resp.json()
        note = data["notes"][0]

        assert note["uuid"] is None
        assert note["frontmatter_valid"] is False
        assert "uuid" in note["missing_required_fields"]

    def test_malformed_yaml_frontmatter_surfaces_invalid_state(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        bind_selected_vault(monkeypatch, tmp_path)
        _write_note(tmp_path / "notes" / "malformed.md", _malformed_frontmatter_note())

        client = TestClient(app)
        resp = client.get("/api/companion/vault-browser")

        assert resp.status_code == 200
        data = resp.json()
        note = data["notes"][0]

        # YAML parse failure → frontmatter_valid=False, uuid missing
        assert note["frontmatter_valid"] is False
        assert "uuid" in note["missing_required_fields"]

    def test_invalid_frontmatter_does_not_crash(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        bind_selected_vault(monkeypatch, tmp_path)
        _write_note(tmp_path / "notes" / "broken.md", _malformed_frontmatter_note())

        client = TestClient(app)
        resp = client.get("/api/companion/vault-browser")

        # Must not 500 — graceful health state surfacing
        assert resp.status_code == 200


class TestArtifactMetadataDistinctFromVaultIdentity:
    def test_vault_identity_and_artifact_metadata_are_separate_fields(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        bind_selected_vault(monkeypatch, tmp_path)
        _write_note(tmp_path / "notes" / "note.md", _full_frontmatter_note())

        client = TestClient(app)
        resp = client.get("/api/companion/vault-browser")

        assert resp.status_code == 200
        data = resp.json()

        # Vault/channel identity lives at top-level response
        assert "vault_identity" in data
        assert "identity_available" in data
        vi = data["vault_identity"]
        assert "vault_name" in vi
        assert "channel" in vi

        # Artifact metadata lives per-note (separate from vault identity)
        note = data["notes"][0]
        assert "uuid" in note
        assert "kind" in note
        assert "review_state" in note
        assert "trust" in note
        # uuid in note != vault_name in vault_identity (different concepts)
        assert note.get("uuid") != vi.get("vault_name")

    def test_multiple_notes_each_have_independent_metadata(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        bind_selected_vault(monkeypatch, tmp_path)
        _write_note(tmp_path / "a" / "first.md", _full_frontmatter_note("First"))
        _write_note(tmp_path / "b" / "second.md", _no_frontmatter_note("Second"))

        client = TestClient(app)
        resp = client.get("/api/companion/vault-browser")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["notes"]) == 2

        by_path = {n["note_path"]: n for n in data["notes"]}
        first = by_path["a/first.md"]
        second = by_path["b/second.md"]

        assert first["frontmatter_valid"] is True
        assert second["frontmatter_valid"] is False
        assert first["uuid"] == "abc-123"
        assert second["uuid"] is None


class TestZoneProjectionEnvelope:
    """#1554 — every ``zone`` carries a #1488 source/authority/provenance/degradation envelope.

    Verify targets named in #1473 child issue #1554. The Vault Browser metadata test module is the
    nearest-authority home (the issue's literal ``tests/api/test_companion_vault_browser.py`` path
    does not exist; metadata projection tests live here).
    """

    def test_zone_projection_envelope_frontmatter(self, tmp_path: Path, monkeypatch) -> None:
        bind_selected_vault(monkeypatch, tmp_path)
        _write_note(tmp_path / "notes" / "complete.md", _full_frontmatter_note("Complete"))

        note = TestClient(app).get("/api/companion/vault-browser").json()["notes"][0]

        # Frontmatter-authored zone is durable vault metadata, no degradation.
        assert note["zone"] == "active"
        assert note["zone_source"] == "frontmatter.zone"
        assert note["zone_authority_role"] == "durable_vault_metadata"
        assert note["zone_provenance"] == "frontmatter.zone"
        assert note["zone_degradation"] == "none"

    def test_zone_projection_envelope_path_fallback(self, tmp_path: Path, monkeypatch) -> None:
        bind_selected_vault(monkeypatch, tmp_path)
        # uuid-only note: valid frontmatter, no zone key → path-derived fallback.
        _write_note(tmp_path / "Projects" / "foo.md", _uuid_only_note("Foo"))

        note = TestClient(app).get("/api/companion/vault-browser").json()["notes"][0]

        assert note["zone"] == "Projects"  # path-derived value unchanged
        assert note["zone_source"] == "vault_path_segment"
        assert note["zone_authority_role"] == "runtime_projection"
        assert note["zone_provenance"] == "vault_path[0]=Projects"
        assert note["zone_degradation"] == "frontmatter_absent"

    def test_zone_projection_envelope_malformed_frontmatter(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        bind_selected_vault(monkeypatch, tmp_path)
        _write_note(tmp_path / "Inbox" / "broken.md", _malformed_frontmatter_note())

        note = TestClient(app).get("/api/companion/vault-browser").json()["notes"][0]

        # Malformed frontmatter degrades to the path posture; never fabricates a zone.
        assert note["zone"] == "Inbox"
        assert note["zone_source"] == "vault_path_segment"
        assert note["zone_authority_role"] == "runtime_projection"
        assert note["zone_degradation"] == "frontmatter_invalid"

    def test_zone_projection_envelope_no_frontmatter_is_absent_not_invalid(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        bind_selected_vault(monkeypatch, tmp_path)
        _write_note(tmp_path / "Areas" / "plain.md", _no_frontmatter_note("Plain"))

        note = TestClient(app).get("/api/companion/vault-browser").json()["notes"][0]

        assert note["zone"] == "Areas"
        assert note["zone_source"] == "vault_path_segment"
        assert note["zone_degradation"] == "frontmatter_absent"


class TestMissingOptionalFieldsAreNullNotCrash:
    def test_optional_fields_absent_from_frontmatter_are_null(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        bind_selected_vault(monkeypatch, tmp_path)
        # Note has uuid + title only
        _write_note(tmp_path / "notes" / "minimal.md", _uuid_only_note("Minimal"))

        client = TestClient(app)
        resp = client.get("/api/companion/vault-browser")

        assert resp.status_code == 200
        data = resp.json()
        note = data["notes"][0]

        # Optional metadata fields absent from YAML → null, not error
        for field in ("kind", "review_state", "trust", "origin", "source_ref", "created", "updated"):
            assert note[field] is None, f"Expected {field!r} to be null, got {note[field]!r}"
