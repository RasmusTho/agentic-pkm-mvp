from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from app.builderops.cli import builderops
from app.builderops.ckm.ingest_github import ingest_github, normalize_github_payload
from app.builderops.ckm.store import CkmStore


def _store(tmp_path: Path) -> CkmStore:
    return CkmStore(tmp_path / "state" / "builderops.sqlite3")


def _issue(updated_at: str = "2026-07-01T10:00:00Z") -> dict[str, object]:
    return {
        "number": 42,
        "title": "Document CKM #3138",
        "state": "open",
        "updated_at": updated_at,
        "labels": [{"name": "type:task"}],
        "body": "See docs/CAPABILITY_KNOWLEDGE_MODEL/README.md and #3138.",
    }


def _pull(updated_at: str = "2026-07-01T10:01:00Z") -> dict[str, object]:
    return {
        "number": 77,
        "title": "Add CKM adapter",
        "state": "closed",
        "updated_at": updated_at,
        "body": "Fixes #42; see docs/CAPABILITY_KNOWLEDGE_MODEL/GITHUB_ARTIFACT_INGESTION.md",
        "changed_files": ["app/builderops/ckm/ingest_github.py"],
    }


def test_rest_payload_normalization_with_refs() -> None:
    record = normalize_github_payload(_issue(), artifact_kind="issue")
    payload = json.loads(record.provenance)
    assert record.natural_key == "github:issue:42"
    assert record.artifact_kind == "issue"
    assert payload["references"] == ["#3138", "docs/CAPABILITY_KNOWLEDGE_MODEL/README.md"]
    assert payload["labels"] == ["type:task"]


def test_updated_at_cursor_incremental(tmp_path: Path) -> None:
    responses = {"issues": [_issue()], "pulls": [_pull()]}

    def fetch(kind: str, since: str | None) -> list[dict[str, object]]:
        return responses[kind]

    store = _store(tmp_path)
    first = ingest_github(store, fetch=fetch)
    assert first["issues"]["changed"] == 1
    assert first["pull_requests"]["changed"] == 1
    assert ingest_github(store, fetch=fetch)["issues"]["changed"] == 0

    responses["issues"] = [_issue("2026-07-02T10:00:00Z")]
    updated = ingest_github(store, fetch=fetch)
    assert updated["issues"]["changed"] == 1
    assert len([item for item in store.list_artifacts() if item.source == "github_issues"]) == 1


def test_offline_degrade_preserves_watermark_via_entrypoint(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    store.ensure_schema()
    store.set_watermark("github_issues", "2026-07-01T00:00:00Z")

    def unavailable(kind: str, since: str | None) -> list[dict[str, object]]:
        raise FileNotFoundError("gh")

    result = ingest_github(store, fetch=unavailable)
    assert result["status"] == "skipped (gh unavailable)"
    assert store.get_watermark("github_issues") == "2026-07-01T00:00:00Z"

    monkeypatch.setattr("app.builderops.cli.ingest_github", lambda *_args, **_kwargs: result)
    db_path = tmp_path / "cli.sqlite3"
    cli_store = CkmStore(db_path)
    cli_store.ensure_schema()
    runner = CliRunner()
    invocation = runner.invoke(builderops, ["--db-path", str(db_path), "ckm", "ingest", "--source", "github"])
    assert invocation.exit_code == 0
    assert "skipped (gh unavailable)" in invocation.output


def test_rest_only_no_graphql() -> None:
    module = Path(__file__).parents[3] / "app/builderops/ckm/ingest_github.py"
    assert "graphql" not in module.read_text(encoding="utf-8").lower()
