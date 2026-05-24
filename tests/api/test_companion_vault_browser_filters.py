"""Vault Browser deterministic metadata filters — contract tests.

Covers #1254 Acceptance Criteria:
- AC1: Browser supports filtering by kind.
- AC2: Browser supports filtering by zone.
- AC3: Browser supports filtering by review_state.
- AC4: Browser supports filtering by trust.
- AC7: Existing path/title search remains available and deterministic.

Filters are server-side and deterministic. No opaque ranking. No semantic retrieval.
Filtering distinguishes missing/unknown from valid values.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app


def _write_note(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _human_note(uuid: str = "uuid-human") -> str:
    return (
        "---\n"
        f"uuid: {uuid}\n"
        "kind: human_note\n"
        "zone: active\n"
        "review_state: needs_review\n"
        "trust: assert\n"
        "---\n\nBody.\n"
    )


def _companion_note(uuid: str = "uuid-companion") -> str:
    return (
        "---\n"
        f"uuid: {uuid}\n"
        "kind: companion_note\n"
        "zone: semi_active\n"
        "review_state: reviewed\n"
        "trust: suggest\n"
        "---\n\nBody.\n"
    )


def _no_fm_note() -> str:
    return "# Plain Note\n\nNo frontmatter.\n"


class TestFilterByKind:
    def test_filter_kind_returns_only_matching_notes(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
        monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
        _write_note(tmp_path / "a" / "human.md", _human_note("uuid-h"))
        _write_note(tmp_path / "b" / "companion.md", _companion_note("uuid-c"))

        client = TestClient(app)
        resp = client.get("/api/companion/vault-browser", params={"kind": "human_note"})

        assert resp.status_code == 200
        data = resp.json()
        kinds = [n.get("kind") for n in data["notes"]]
        assert all(k == "human_note" for k in kinds)
        assert len(data["notes"]) == 1

    def test_filter_kind_empty_result_when_no_match(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
        monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
        _write_note(tmp_path / "a" / "human.md", _human_note())

        client = TestClient(app)
        resp = client.get("/api/companion/vault-browser", params={"kind": "system_note"})

        assert resp.status_code == 200
        assert resp.json()["notes"] == []

    def test_filter_kind_missing_excluded_by_explicit_filter(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Notes with missing kind (no frontmatter) are excluded when kind filter active."""
        monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
        monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
        _write_note(tmp_path / "a" / "with-kind.md", _human_note())
        _write_note(tmp_path / "b" / "no-kind.md", _no_fm_note())

        client = TestClient(app)
        resp = client.get("/api/companion/vault-browser", params={"kind": "human_note"})

        assert resp.status_code == 200
        paths = [n["note_path"] for n in resp.json()["notes"]]
        assert "a/with-kind.md" in paths
        assert "b/no-kind.md" not in paths


class TestFilterByZone:
    def test_filter_zone_active(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
        monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
        _write_note(tmp_path / "a" / "active.md", _human_note())
        _write_note(tmp_path / "b" / "semi.md", _companion_note())

        client = TestClient(app)
        resp = client.get("/api/companion/vault-browser", params={"zone": "active"})

        assert resp.status_code == 200
        data = resp.json()
        zones = [n.get("zone") for n in data["notes"]]
        assert all(z == "active" for z in zones)
        assert len(data["notes"]) == 1

    def test_filter_zone_semi_active(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
        monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
        _write_note(tmp_path / "a" / "active.md", _human_note())
        _write_note(tmp_path / "b" / "semi.md", _companion_note())

        client = TestClient(app)
        resp = client.get("/api/companion/vault-browser", params={"zone": "semi_active"})

        assert resp.status_code == 200
        data = resp.json()
        zones = [n.get("zone") for n in data["notes"]]
        assert all(z == "semi_active" for z in zones)
        assert len(data["notes"]) == 1


class TestFilterByReviewState:
    def test_filter_review_state_needs_review(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
        monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
        _write_note(tmp_path / "a" / "needs-review.md", _human_note())
        _write_note(tmp_path / "b" / "reviewed.md", _companion_note())

        client = TestClient(app)
        resp = client.get(
            "/api/companion/vault-browser", params={"review_state": "needs_review"}
        )

        assert resp.status_code == 200
        data = resp.json()
        states = [n.get("review_state") for n in data["notes"]]
        assert all(s == "needs_review" for s in states)
        assert len(data["notes"]) == 1

    def test_filter_review_state_reviewed(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
        monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
        _write_note(tmp_path / "a" / "needs-review.md", _human_note())
        _write_note(tmp_path / "b" / "reviewed.md", _companion_note())

        client = TestClient(app)
        resp = client.get(
            "/api/companion/vault-browser", params={"review_state": "reviewed"}
        )

        assert resp.status_code == 200
        data = resp.json()
        states = [n.get("review_state") for n in data["notes"]]
        assert all(s == "reviewed" for s in states)
        assert len(data["notes"]) == 1


class TestFilterByTrust:
    def test_filter_trust_assert(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
        monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
        _write_note(tmp_path / "a" / "assert.md", _human_note())
        _write_note(tmp_path / "b" / "suggest.md", _companion_note())

        client = TestClient(app)
        resp = client.get("/api/companion/vault-browser", params={"trust": "assert"})

        assert resp.status_code == 200
        data = resp.json()
        trusts = [n.get("trust") for n in data["notes"]]
        assert all(t == "assert" for t in trusts)
        assert len(data["notes"]) == 1

    def test_filter_trust_suggest(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
        monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
        _write_note(tmp_path / "a" / "assert.md", _human_note())
        _write_note(tmp_path / "b" / "suggest.md", _companion_note())

        client = TestClient(app)
        resp = client.get("/api/companion/vault-browser", params={"trust": "suggest"})

        assert resp.status_code == 200
        data = resp.json()
        trusts = [n.get("trust") for n in data["notes"]]
        assert all(t == "suggest" for t in trusts)
        assert len(data["notes"]) == 1


class TestActiveFiltersInResponse:
    def test_active_filters_returned_in_response(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
        monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
        _write_note(tmp_path / "a" / "note.md", _human_note())

        client = TestClient(app)
        resp = client.get(
            "/api/companion/vault-browser",
            params={"kind": "human_note", "review_state": "needs_review"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "active_filters" in data
        assert "human_note" in data["active_filters"].get("kind", [])
        assert "needs_review" in data["active_filters"].get("review_state", [])

    def test_no_active_filters_when_none_specified(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
        monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
        _write_note(tmp_path / "a" / "note.md", _human_note())

        client = TestClient(app)
        resp = client.get("/api/companion/vault-browser")

        assert resp.status_code == 200
        data = resp.json()
        assert "active_filters" in data
        assert data["active_filters"] == {}


class TestTextSearchAndFiltersCompose:
    def test_q_filter_composes_with_kind_filter(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
        monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
        _write_note(tmp_path / "notes" / "human-alpha.md", _human_note("uuid-ha"))
        _write_note(tmp_path / "notes" / "human-beta.md", _human_note("uuid-hb"))
        _write_note(tmp_path / "companion" / "companion-alpha.md", _companion_note("uuid-ca"))

        client = TestClient(app)
        resp = client.get(
            "/api/companion/vault-browser",
            params={"q": "alpha", "kind": "human_note"},
        )

        assert resp.status_code == 200
        data = resp.json()
        # Only human_note matching "alpha" in path
        assert len(data["notes"]) == 1
        assert data["notes"][0]["note_path"] == "notes/human-alpha.md"
