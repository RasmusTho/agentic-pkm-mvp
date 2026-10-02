"""Exact, read-only integration reconciliation for promoted eval drafts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

import app.eval.failure_capture as failure_capture
from app.eval.draft_reconciliation import build_reconciliation_report, main
from app.eval.failure_capture import (
    DRAFT_KIND_CLASSIFICATION_CASE,
    DRAFT_KIND_SCHEMA_VIOLATION,
    DRAFT_STATUS_PENDING,
    DRAFT_STATUS_PROMOTED,
    DRAFT_STATUS_REJECTED,
    draft_dead_letter_case,
    draft_unknown_classification_case,
    promote_draft,
    read_draft,
    reject_draft,
)
from app.write_guard import WriteGuard, WritesBlockedError

from tests.api._vault_test_helpers import bind_initialized_vault

pytestmark = pytest.mark.not_pg


@pytest.fixture()
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bind_initialized_vault(monkeypatch, tmp_path)
    return tmp_path


def _draft(vault: Path, kind: str, trace_id: str):
    if kind == DRAFT_KIND_CLASSIFICATION_CASE:
        return draft_unknown_classification_case(
            vault_root=vault,
            utterance=f"unresolved case {trace_id}",
            trace_id=trace_id,
        )
    result = draft_dead_letter_case(
        vault_root=vault,
        topic="ingest.vault.changed",
        reason="schema_violation:missing_required_field",
        event_id=f"event-{trace_id}",
        payload={"trace_id": trace_id},
        trace_id=trace_id,
    )
    assert result is not None
    return result


def _promoted(vault: Path, kind: str, trace_id: str, notes: str | None):
    draft = _draft(vault, kind, trace_id)
    decision = promote_draft(
        vault,
        draft.draft_id,
        decided_by="reviewer@example.test",
        notes=notes,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    return draft, decision


def _repository_root(root: Path, *, cases: list[dict[str, str]]) -> Path:
    repository = root / "repository"
    dataset = repository / "docs" / "eval" / "classification_golden.yaml"
    dataset.parent.mkdir(parents=True)
    dataset.write_text(
        yaml.safe_dump(
            {"schema_version": "classification_case.v1", "cases": cases},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return repository


def test_promoted_unintegrated_draft_is_reported(vault: Path, tmp_path: Path) -> None:
    _draft(vault, DRAFT_KIND_CLASSIFICATION_CASE, "pending")
    rejected = _draft(vault, DRAFT_KIND_SCHEMA_VIOLATION, "rejected")
    reject_draft(
        vault,
        rejected.draft_id,
        decided_by="reviewer@example.test",
        notes="not a valid case",
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )
    promoted, decision = _promoted(
        vault, DRAFT_KIND_CLASSIFICATION_CASE, "promoted", "reviewed by owner"
    )
    repository = _repository_root(tmp_path, cases=[])

    report = build_reconciliation_report(
        vault_root=vault,
        repository_root=repository,
    )

    assert report["promoted_count"] == 1
    assert report["needing_integration_review_count"] == 1
    record = report["drafts"][0]
    assert record["draft_id"] == promoted.draft_id
    assert record["kind"] == DRAFT_KIND_CLASSIFICATION_CASE
    assert record["status"] == DRAFT_STATUS_PROMOTED
    assert record["decision_provenance"] == {
        "decided_by": "reviewer@example.test",
        "decided_at": decision.decided_at,
        "notes": "reviewed by owner",
        "complete": True,
    }
    assert record["needs_integration_review"] is True
    assert record["integration"]["reason"] == "integration_reference_missing"
    assert record["integration"]["verified"] is False
    assert DRAFT_STATUS_PENDING != record["status"]
    assert DRAFT_STATUS_REJECTED != record["status"]


def test_integration_references_resolve_exactly_within_repository(
    vault: Path, tmp_path: Path
) -> None:
    repository = _repository_root(
        tmp_path,
        cases=[{"id": "case-exact"}, {"id": "duplicate-case"}, {"id": "duplicate-case"}],
    )
    fixture = repository / "tests" / "schemas" / "test_contract.py"
    fixture.parent.mkdir(parents=True)
    fixture.write_text(
        "def test_schema_contract():\n    assert True\n"
        "def test_duplicate_target():\n    assert True\n"
        "def test_duplicate_target():\n    assert False\n",
        encoding="utf-8",
    )
    outside_fixture = tmp_path / "outside_fixture.py"
    outside_fixture.write_text("def test_escape():\n    assert True\n", encoding="utf-8")
    (repository / "tests" / "schemas" / "test_symlink.py").symlink_to(outside_fixture)

    expected: dict[str, bool] = {}
    references = {
        "golden exact": (DRAFT_KIND_CLASSIFICATION_CASE, "integration_ref: golden-case:case-exact"),
        "fixture exact": (
            DRAFT_KIND_SCHEMA_VIOLATION,
            "integration_ref: schema-fixture:tests/schemas/test_contract.py::test_schema_contract",
        ),
        "golden wrong kind": (
            DRAFT_KIND_SCHEMA_VIOLATION,
            "draft-kind mismatch check\nintegration_ref: golden-case:case-exact",
        ),
        "fixture wrong kind": (
            DRAFT_KIND_CLASSIFICATION_CASE,
            "draft-kind mismatch check\nintegration_ref: schema-fixture:tests/schemas/test_contract.py::test_schema_contract",
        ),
        "missing target": (DRAFT_KIND_CLASSIFICATION_CASE, "integration_ref: golden-case:missing-case"),
        "ambiguous golden": (
            DRAFT_KIND_CLASSIFICATION_CASE,
            "integration_ref: golden-case:duplicate-case",
        ),
        "malformed": (DRAFT_KIND_CLASSIFICATION_CASE, "integration_ref: golden-case:bad id"),
        "duplicate line": (
            DRAFT_KIND_CLASSIFICATION_CASE,
            "integration_ref: golden-case:case-exact\nintegration_ref: golden-case:case-exact",
        ),
        "escaping path": (
            DRAFT_KIND_SCHEMA_VIOLATION,
            "integration_ref: schema-fixture:tests/../outside.py::test_escape",
        ),
        "symlink path": (
            DRAFT_KIND_SCHEMA_VIOLATION,
            "integration_ref: schema-fixture:tests/schemas/test_symlink.py::test_escape",
        ),
        "missing fixture": (
            DRAFT_KIND_SCHEMA_VIOLATION,
            "integration_ref: schema-fixture:tests/schemas/missing.py::test_missing",
        ),
        "ambiguous fixture": (
            DRAFT_KIND_SCHEMA_VIOLATION,
            "integration_ref: schema-fixture:tests/schemas/test_contract.py::test_duplicate_target",
        ),
    }
    for index, (label, (kind, notes)) in enumerate(references.items()):
        draft, _ = _promoted(vault, kind, f"reference-{index}", notes)
        expected[draft.draft_id] = label in {"golden exact", "fixture exact"}

    report = build_reconciliation_report(vault_root=vault, repository_root=repository)
    observed = {record["draft_id"]: record for record in report["drafts"]}
    assert set(observed) == set(expected)
    for draft_id, verified in expected.items():
        assert observed[draft_id]["integration"]["verified"] is verified
        assert observed[draft_id]["needs_integration_review"] is (not verified)

    reasons = {
        record["decision_provenance"]["notes"]: record["integration"]["reason"]
        for record in report["drafts"]
    }
    assert reasons["integration_ref: golden-case:missing-case"] == "golden_case_not_found"
    assert reasons["integration_ref: golden-case:duplicate-case"] == "golden_case_ambiguous"
    assert reasons[
        "draft-kind mismatch check\nintegration_ref: golden-case:case-exact"
    ] == "integration_reference_kind_mismatch"
    assert reasons["integration_ref: golden-case:bad id"] == "malformed_integration_reference"
    assert reasons[
        "integration_ref: golden-case:case-exact\nintegration_ref: golden-case:case-exact"
    ] == "integration_reference_ambiguous"
    assert reasons[
        "integration_ref: schema-fixture:tests/../outside.py::test_escape"
    ] == "malformed_repository_path"
    assert reasons[
        "integration_ref: schema-fixture:tests/schemas/test_symlink.py::test_escape"
    ] == "symlink_repository_path"
    assert reasons[
        "integration_ref: schema-fixture:tests/schemas/missing.py::test_missing"
    ] == "missing_repository_path"
    assert reasons[
        "integration_ref: schema-fixture:tests/schemas/test_contract.py::test_duplicate_target"
    ] == "schema_fixture_test_ambiguous"
    assert reasons[
        "draft-kind mismatch check\nintegration_ref: schema-fixture:tests/schemas/test_contract.py::test_schema_contract"
    ] == "integration_reference_kind_mismatch"


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def test_reconciliation_entrypoint_is_read_only(
    vault: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = _repository_root(tmp_path, cases=[{"id": "case-read-only"}])
    marker = repository / "fixture-was-executed"
    fixture = repository / "tests" / "schemas" / "test_no_execute.py"
    fixture.parent.mkdir(parents=True)
    fixture.write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n"
        "def test_fixture():\n    assert True\n",
        encoding="utf-8",
    )
    _promoted(
        vault,
        DRAFT_KIND_SCHEMA_VIOLATION,
        "read-only",
        "integration_ref: schema-fixture:tests/schemas/test_no_execute.py::test_fixture",
    )
    vault_before = _snapshot(vault)
    repository_before = _snapshot(repository)

    assert main(
        ["--vault-root", str(vault), "--repository-root", str(repository)]
    ) == 0
    stdout = capsys.readouterr().out
    output = json.loads(stdout)

    assert output["promoted_count"] == 1
    assert output["drafts"][0]["integration"]["verified"] is True
    assert _snapshot(vault) == vault_before
    assert _snapshot(repository) == repository_before
    assert not marker.exists()


def test_promotion_persists_provenance_under_existing_guards(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = _draft(vault, DRAFT_KIND_CLASSIFICATION_CASE, "service-provenance")
    assert draft.draft_path is not None
    draft_path = vault / draft.draft_path
    original_bytes = draft_path.read_bytes()
    captured: dict[str, object] = {}
    original_write = failure_capture.write_note_relative

    def capture_write(*args, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return original_write(*args, **kwargs)

    monkeypatch.setattr(failure_capture, "write_note_relative", capture_write)
    decision = promote_draft(
        vault,
        draft.draft_id,
        decided_by="owner:service",
        notes="adjudicated\nintegration_ref: golden-case:case-exact",
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )

    persisted = read_draft(vault, draft.draft_id)
    assert persisted is not None
    assert persisted.status == DRAFT_STATUS_PROMOTED
    assert persisted.decided_by == "owner:service"
    assert persisted.decided_at == decision.decided_at
    assert persisted.notes == "adjudicated\nintegration_ref: golden-case:case-exact"
    assert captured["expected_version"] == hashlib.sha256(original_bytes).hexdigest()
    assert captured["action"] == failure_capture.FAILURE_CAPTURE_DRAFT_ACTION
    assert captured["writer_identity"] == "eval.failure_capture.decision"

    blocked = _draft(vault, DRAFT_KIND_SCHEMA_VIOLATION, "guard-blocked")
    assert blocked.draft_path is not None
    blocked_path = vault / blocked.draft_path
    blocked_bytes = blocked_path.read_bytes()
    with pytest.raises(WritesBlockedError):
        promote_draft(
            vault,
            blocked.draft_id,
            decided_by="owner:service",
            notes="must not persist",
            write_guard=WriteGuard(
                lambda: {"state": "safe_mode", "reason": "operator hold"}
            ),
        )
    assert blocked_path.read_bytes() == blocked_bytes
    unchanged = read_draft(vault, blocked.draft_id)
    assert unchanged is not None and unchanged.status == DRAFT_STATUS_PENDING
    assert unchanged.decided_by is None
    assert unchanged.decided_at is None
    assert unchanged.notes is None


def test_api_conflict_is_not_reported_as_a_success(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from app.api.app import app

    draft = _draft(vault, DRAFT_KIND_CLASSIFICATION_CASE, "api-conflict")
    assert draft.draft_path is not None
    draft_path = vault / draft.draft_path
    original_write = failure_capture.write_note_relative

    def race_before_write(note_rel_path: str, content: str, **kwargs: object):
        target = Path(str(kwargs["vault_root"])) / note_rel_path
        target.write_bytes(target.read_bytes() + b"\nconcurrent edit\n")
        return original_write(note_rel_path, content, **kwargs)

    monkeypatch.setattr(failure_capture, "write_note_relative", race_before_write)
    response = TestClient(app).post(
        f"/api/eval-drafts/{draft.draft_id}/decision",
        json={
            "action": "promote",
            "decided_by": "owner:api",
            "notes": "must not report success",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "eval_draft_decision_refused"
    persisted = read_draft(vault, draft.draft_id)
    assert persisted is not None and persisted.status == DRAFT_STATUS_PENDING
    assert persisted.decided_by is None
    assert persisted.notes is None
    assert b"concurrent edit" in draft_path.read_bytes()
