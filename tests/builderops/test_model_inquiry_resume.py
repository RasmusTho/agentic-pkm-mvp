from __future__ import annotations

from pathlib import Path
import json
import hashlib

from app.builderops.model_inquiry import ModelInquiryService


def test_resume_skips_committed_turn(tmp_path: Path) -> None:
    vault = tmp_path / "shared-vault"
    vault.mkdir()
    source_refs = [{"ref_type": "github_issue", "ref": "#3290"}]
    service = ModelInquiryService(vault)
    service.start(
        question="Resume safely",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_resume",
        source_refs=source_refs,
    )
    turn_a = service.commit_turn(
        "inq_test_resume",
        turn_id="turn-a",
        sequence=0,
        role="fable",
        content="Committed A",
        input_artifact_refs=["question"],
        source_refs=source_refs,
    )
    service.commit_turn(
        "inq_test_resume",
        turn_id="turn-b",
        sequence=1,
        role="gpt",
        content="Unreceipted B",
        input_artifact_refs=["turn-a"],
        source_refs=source_refs,
    )
    receipt = service.commit_terminal_turn_receipt(
        "inq_test_resume",
        turn_id="turn-a",
        outcome="accepted",
        source_refs=source_refs,
    )

    resumed = ModelInquiryService(vault).resume("inq_test_resume")

    assert resumed["skipped_turn_ids"] == ["turn-a"]
    assert resumed["pending_turn_ids"] == ["turn-b"]
    assert resumed["terminal_receipt_ids"] == [receipt["id"]]
    assert resumed["next_sequence"] == 2
    assert receipt["turn_content_hash"] == turn_a["content_hash"]

    receipt_path = (
        vault
        / "model-inquiries"
        / "inq_test_resume"
        / "receipts"
        / "turn-turn-a-terminal.json"
    )
    tampered = json.loads(receipt_path.read_text(encoding="utf-8"))
    tampered["action"] = "failed"
    canonical = {key: value for key, value in tampered.items() if key != "artifact_hash"}
    tampered["artifact_hash"] = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    receipt_path.write_text(json.dumps(tampered), encoding="utf-8")
    resumed = ModelInquiryService(vault).resume("inq_test_resume")
    assert resumed["skipped_turn_ids"] == []
    assert resumed["pending_turn_ids"] == ["turn-a", "turn-b"]
