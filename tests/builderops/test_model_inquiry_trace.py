from __future__ import annotations

from pathlib import Path
import json

import pytest

from app.builderops.model_inquiry import ModelInquiryService
from app.builderops.models import BuilderOpsValidationError


def test_trace_links_question_turns_and_synthesis(tmp_path: Path) -> None:
    vault = tmp_path / "shared-vault"
    vault.mkdir()
    service = ModelInquiryService(vault)
    source_refs = [{"ref_type": "github_issue", "ref": "#3290"}]
    service.start(
        question="Trace this inquiry",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_trace",
        source_refs=source_refs,
    )
    second = service.commit_turn(
        "inq_test_trace",
        turn_id="turn-b",
        sequence=1,
        role="gpt",
        content="Second turn",
        input_artifact_refs=["turn-a"],
        source_refs=source_refs,
    )
    first = service.commit_turn(
        "inq_test_trace",
        turn_id="turn-a",
        sequence=0,
        role="fable",
        content="First turn",
        input_artifact_refs=["question"],
        source_refs=source_refs,
    )
    synthesis = service.commit_synthesis(
        "inq_test_trace",
        content="Shared synthesis",
        input_artifact_refs=["turn-a", "turn-b"],
        source_refs=source_refs,
    )
    readiness = service.commit_readiness(
        "inq_test_trace",
        outcome="needs_input",
        rationale="One contract question remains.",
        input_artifact_refs=["synthesis"],
        source_refs=source_refs,
    )

    trace = ModelInquiryService(vault).trace("inq_test_trace")

    assert trace["question"]["inquiry_id"] == "inq_test_trace"
    assert trace["turns"] == [first, second]
    assert trace["synthesis"] == synthesis
    assert trace["readiness"] == readiness
    assert trace["source_refs"] == source_refs
    assert trace["completeness"] == {
        "ok": True,
        "question": True,
        "turn_count": 2,
        "synthesis": True,
        "readiness": True,
    }
    assert all(item["content_hash"] for item in [trace["question"], *trace["turns"], synthesis])

    receipt_path = (
        vault
        / "model-inquiries"
        / "inq_test_trace"
        / "receipts"
        / "inquiry-started.json"
    )
    receipt_path.unlink()
    with pytest.raises(BuilderOpsValidationError, match="start receipt is missing"):
        ModelInquiryService(vault).trace("inq_test_trace")


def test_trace_rejects_tampered_derived_artifact(tmp_path: Path) -> None:
    vault = tmp_path / "shared-vault"
    vault.mkdir()
    service = ModelInquiryService(vault)
    refs = [{"ref_type": "github_issue", "ref": "#3290"}]
    service.start(
        question="Validate derived artifacts",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_tamper",
        source_refs=refs,
    )
    service.commit_synthesis(
        "inq_test_tamper",
        content="Original",
        input_artifact_refs=["question"],
        source_refs=refs,
    )
    path = vault / "model-inquiries" / "inq_test_tamper" / "synthesis.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["content"] = "Tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BuilderOpsValidationError, match="synthesis content hash mismatch"):
        service.trace("inq_test_tamper")
    payload["content"] = "Original"
    path.write_text(json.dumps(payload), encoding="utf-8")

    turn = service.commit_turn(
        "inq_test_tamper",
        turn_id="turn-a",
        sequence=0,
        role="reviewer",
        content="Original turn",
        input_artifact_refs=["question"],
        source_refs=refs,
    )
    turn_path = vault / "model-inquiries" / "inq_test_tamper" / "turns" / "000000.json"
    turn["role"] = "tampered-role"
    turn_path.write_text(json.dumps(turn), encoding="utf-8")
    with pytest.raises(BuilderOpsValidationError, match="artifact hash mismatch"):
        service.trace("inq_test_tamper")


def test_receipt_parent_symlink_cannot_escape_vault(tmp_path: Path) -> None:
    vault = tmp_path / "shared-vault"
    outside = tmp_path / "outside"
    vault.mkdir()
    outside.mkdir()
    service = ModelInquiryService(vault)
    refs = [{"ref_type": "github_issue", "ref": "#3290"}]
    service.start(
        question="Stay confined",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_symlink",
        source_refs=refs,
    )
    service.commit_turn(
        "inq_test_symlink",
        turn_id="turn-a",
        sequence=0,
        role="reviewer",
        content="Committed",
        input_artifact_refs=["question"],
        source_refs=refs,
    )
    receipts = vault / "model-inquiries" / "inq_test_symlink" / "receipts"
    (receipts / "inquiry-started.json").unlink()
    receipts.rmdir()
    receipts.symlink_to(outside, target_is_directory=True)

    with pytest.raises(BuilderOpsValidationError, match="parent must not be a symlink"):
        service.commit_terminal_turn_receipt(
            "inq_test_symlink",
            turn_id="turn-a",
            outcome="accepted",
            source_refs=refs,
        )
    assert list(outside.iterdir()) == []
