from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.expansion.create import CreateRequest, OutputKind, SourceInput, run_create_pass
from app.panel.checkbox_projection import (
    CheckboxProjectionRequest,
    CheckboxProjectionService,
    extract_panel_selectable_options,
)
from app.proposals.declined_ledger import DeclinedLedger
from app.standing_questions import review as review_module
from app.standing_questions.question_store import (
    HumanOwnedFieldMutationError,
    QuestionStore,
)
from app.standing_questions.review import dismiss_question_candidate, transition_question_status
from app.write_guard import WriteGuard


def _guard() -> WriteGuard:
    return WriteGuard(snapshot_fn=lambda: {"state": "healthy", "reason": None})


def _stage_candidate(tmp_path: Path, *, question_text: str = "Will the index move?") -> tuple[Path, Path, Path, QuestionStore, dict, str]:
    vault = tmp_path / "vault"
    vault.mkdir()
    store = QuestionStore(vault, write_guard=_guard())
    question, _ = store.create_question(
        text=question_text,
        scope="work",
        registered_via="explicit",
    )
    draft_id = uuid4().hex
    outbox = tmp_path / "receipts.jsonl"
    report = run_create_pass(
        CreateRequest(
            kind=OutputKind.ANSWER_NOTE,
            title="Index answer",
            sources=(
                SourceInput(
                    object_id="source-a",
                    note_path="notes/source-a.md",
                    text="The index remains local.",
                    quoted_spans=("The index remains local.",),
                    language="en",
                    review_state="reviewed",
                ),
            ),
            question=question_text,
        ),
        vault_root=vault,
        outbox_path=outbox,
        write_guard=_guard(),
        draft_id=draft_id,
        draft_frontmatter_enricher=lambda _draft: {"question_id": question["question_id"]},
    )
    assert report.draft_path is not None
    draft_path = vault / report.draft_path
    current, version = store.read_question_with_version(question["question_id"])
    store.update_system_fields_if_unchanged(
        question["question_id"],
        current,
        {"candidate_answer_ref": f"vault://{report.draft_path}"},
        expected_version=version,
    )
    observed, observed_version = store.read_question_with_version(question["question_id"])
    return vault, draft_path, outbox, store, observed, observed_version


def _acceptance_request(
    draft_path: Path,
    *,
    vault: Path,
    question: dict,
    question_version: str,
) -> CheckboxProjectionRequest:
    note_path = draft_path.relative_to(vault).as_posix()
    raw = draft_path.read_text(encoding="utf-8")
    options = extract_panel_selectable_options(
        raw,
        artifact_id=draft_path.stem,
        note_path=note_path,
    )
    assert len(options) == 1
    option = options[0]
    return CheckboxProjectionRequest(
        artifact_id=option.artifact_id,
        note_path=note_path,
        panel_id=option.panel_id,
        option_id=option.option_id,
        expected_content_hash=option.content_hash,
        expected_source_hash=option.source_hash,
        idempotency_key=f"sq-test-{uuid4().hex}",
        review_question_id=question["question_id"],
        expected_question_version=question_version,
    )


def _panel_request(vault: Path | None) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(compatibility_write_root=vault))


def test_accept_projects_checkbox_and_flips_status_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.routes import panel as panel_route
    from app.panel import checkbox_projection as checkbox_projection_module
    from scripts.yaml_roundtrip import load_frontmatter

    vault, draft_path, outbox, store, question, version = _stage_candidate(tmp_path)
    request = _acceptance_request(
        draft_path, vault=vault, question=question, question_version=version
    )
    service = CheckboxProjectionService(write_guard=_guard())
    monkeypatch.setattr(checkbox_projection_module, "resolve_optional_vault_root", lambda: vault)
    monkeypatch.setattr(panel_route.checkbox_projection_module, "_service", service)
    monkeypatch.setattr(review_module, "resolve_outbox_path", lambda _value: outbox)

    response = asyncio.run(
        panel_route.panel_checkbox_projection(request, _panel_request(vault))
    )

    updated, _ = store.read_question_with_version(question["question_id"])
    assert response.status == "executed"
    assert response.receipt is not None
    assert updated["status"] == "answered"
    assert updated["candidate_answer_ref"] is None
    assert updated["standing_answer_ref"]
    answer_path = vault / updated["standing_answer_ref"].removeprefix("vault://")
    answer_frontmatter, _ = load_frontmatter(answer_path.read_text(encoding="utf-8"))
    assert answer_frontmatter["authority_state"] == "accepted"
    assert answer_frontmatter["acceptance_receipt_id"] == response.receipt["authority_receipt_id"]
    assert not draft_path.exists()

    replay = asyncio.run(
        panel_route.panel_checkbox_projection(request, _panel_request(vault))
    )
    assert replay.status == "executed"
    assert replay.receipt is not None
    assert replay.receipt["idempotent_replay"] is True


def test_accept_refuses_without_a_sealed_vault_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.routes import panel as panel_route
    from fastapi import HTTPException

    vault, draft_path, _outbox, store, question, version = _stage_candidate(tmp_path)
    request = _acceptance_request(
        draft_path, vault=vault, question=question, question_version=version
    )
    service = CheckboxProjectionService(write_guard=_guard())
    projected: list[bool] = []
    monkeypatch.setattr(
        service,
        "project",
        lambda *_args, **_kwargs: projected.append(True),
    )
    monkeypatch.setattr(panel_route.checkbox_projection_module, "_service", service)

    with pytest.raises(HTTPException) as refused:
        asyncio.run(panel_route.panel_checkbox_projection(request, _panel_request(None)))

    current = store.read_question(question["question_id"])
    assert refused.value.detail["error"] == "capability_not_ready"
    assert projected == []
    assert draft_path.exists()
    assert current["status"] == "open"
    assert current["candidate_answer_ref"]


def test_atomic_acceptance_publication_leaves_no_partial_canonical_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.routes import panel as panel_route
    from app.expansion import accept as accept_module
    from app.panel import checkbox_projection as checkbox_projection_module
    from fastapi import HTTPException

    vault, draft_path, outbox, store, question, version = _stage_candidate(tmp_path)
    request = _acceptance_request(
        draft_path, vault=vault, question=question, question_version=version
    )
    service = CheckboxProjectionService(write_guard=_guard())
    monkeypatch.setattr(checkbox_projection_module, "resolve_optional_vault_root", lambda: vault)
    monkeypatch.setattr(panel_route.checkbox_projection_module, "_service", service)
    monkeypatch.setattr(review_module, "resolve_outbox_path", lambda _value: outbox)
    projection = service.project(request, execute_runtime=False)
    assert projection.status == "projected"
    original_link = accept_module.os.link

    def fail_publication(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("injected failure before atomic publication")

    monkeypatch.setattr(accept_module.os, "link", fail_publication)
    with pytest.raises(HTTPException) as refused:
        asyncio.run(panel_route.panel_checkbox_projection(request, _panel_request(vault)))

    unresolved, _ = store.read_question_with_version(question["question_id"])
    assert refused.value.detail["state"] == "acknowledgement_indeterminate"
    assert unresolved["status"] == "open"
    assert unresolved["candidate_answer_ref"]
    assert draft_path.exists()
    assert not list(vault.rglob("*.tmp"))

    monkeypatch.setattr(accept_module.os, "link", original_link)
    recovered = asyncio.run(panel_route.panel_checkbox_projection(request, _panel_request(vault)))
    answered, _ = store.read_question_with_version(question["question_id"])
    assert recovered.status == "executed"
    assert answered["status"] == "answered"
    assert not draft_path.exists()


def test_acceptance_retry_removes_only_its_leftover_linked_temp_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.routes import panel as panel_route
    from app.panel import checkbox_projection as checkbox_projection_module
    from fastapi import HTTPException
    from scripts.yaml_roundtrip import load_frontmatter

    vault, draft_path, outbox, store, question, version = _stage_candidate(tmp_path)
    request = _acceptance_request(
        draft_path, vault=vault, question=question, question_version=version
    )
    service = CheckboxProjectionService(write_guard=_guard())
    monkeypatch.setattr(checkbox_projection_module, "resolve_optional_vault_root", lambda: vault)
    monkeypatch.setattr(panel_route.checkbox_projection_module, "_service", service)
    monkeypatch.setattr(review_module, "resolve_outbox_path", lambda _value: outbox)
    assert service.project(request, execute_runtime=False).status == "projected"
    original_unlink = Path.unlink

    def fail_temp_cleanup(path: Path, *args: Any, **kwargs: Any) -> None:
        if path.suffix == ".tmp":
            raise OSError("injected crash before linked-temp cleanup")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_temp_cleanup)
    with pytest.raises(HTTPException) as interrupted:
        asyncio.run(panel_route.panel_checkbox_projection(request, _panel_request(vault)))
    assert interrupted.value.detail["state"] == "acknowledgement_indeterminate"
    assert store.read_question(question["question_id"])["status"] == "open"
    assert draft_path.exists()

    accepted_paths = [
        path
        for path in vault.rglob("*.md")
        if (load_frontmatter(path.read_text(encoding="utf-8"))[0] or {}).get("authority_state")
        == "accepted"
    ]
    temp_aliases = list(vault.rglob("*.tmp"))
    assert len(accepted_paths) == 1
    assert len(temp_aliases) == 1
    assert accepted_paths[0].stat().st_ino == temp_aliases[0].stat().st_ino
    assert accepted_paths[0].stat().st_nlink == 2

    monkeypatch.setattr(Path, "unlink", original_unlink)
    recovered = asyncio.run(panel_route.panel_checkbox_projection(request, _panel_request(vault)))
    answered, _ = store.read_question_with_version(question["question_id"])
    assert recovered.status == "executed"
    assert answered["status"] == "answered"
    assert not list(vault.rglob("*.tmp"))
    assert accepted_paths[0].stat().st_nlink == 1


def test_accept_recovers_exact_checked_projection_after_lost_ack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.routes import panel as panel_route
    from app.panel import checkbox_projection as checkbox_projection_module

    vault, draft_path, outbox, store, question, version = _stage_candidate(tmp_path)
    request = _acceptance_request(
        draft_path, vault=vault, question=question, question_version=version
    )
    service = CheckboxProjectionService(write_guard=_guard())
    monkeypatch.setattr(checkbox_projection_module, "resolve_optional_vault_root", lambda: vault)
    monkeypatch.setattr(panel_route.checkbox_projection_module, "_service", service)
    monkeypatch.setattr(review_module, "resolve_outbox_path", lambda _value: outbox)

    projection = service.project(request, execute_runtime=False)
    assert projection.status == "projected"
    still_open, _ = store.read_question_with_version(question["question_id"])
    assert still_open["status"] == "open"

    response = asyncio.run(
        panel_route.panel_checkbox_projection(request, _panel_request(vault))
    )
    updated, _ = store.read_question_with_version(question["question_id"])
    assert response.status == "executed"
    assert updated["status"] == "answered"
    assert updated["candidate_answer_ref"] is None


def test_exp4_success_with_question_cas_failure_is_indeterminate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.routes import panel as panel_route
    from app.api.routes import standing_questions as question_routes
    from app.knowledge.errors import KnowledgeWriteConflict
    from app.panel import checkbox_projection as checkbox_projection_module
    from app.services.outbox import iter_jsonl_outbox_records
    from fastapi import HTTPException

    vault, draft_path, outbox, store, question, version = _stage_candidate(tmp_path)
    request = _acceptance_request(
        draft_path, vault=vault, question=question, question_version=version
    )
    service = CheckboxProjectionService(write_guard=_guard())
    monkeypatch.setattr(checkbox_projection_module, "resolve_optional_vault_root", lambda: vault)
    monkeypatch.setattr(panel_route.checkbox_projection_module, "_service", service)
    monkeypatch.setattr(review_module, "resolve_outbox_path", lambda _value: outbox)

    successful_ack = QuestionStore.update_review_fields_if_unchanged

    def fail_ack(*_args: object, **_kwargs: object) -> object:
        raise KnowledgeWriteConflict("injected post-materialization Question CAS failure")

    monkeypatch.setattr(QuestionStore, "update_review_fields_if_unchanged", fail_ack)
    with pytest.raises(HTTPException) as refused:
        asyncio.run(panel_route.panel_checkbox_projection(request, _panel_request(vault)))

    unresolved, _ = store.read_question_with_version(question["question_id"])
    candidate = question_routes._candidate_answer(
        {
            **unresolved,
            "candidate_answer_ref": unresolved["candidate_answer_ref"],
        },
        question_id=question["question_id"],
        question_version="current-version",
        vault_root=vault,
    )
    assert refused.value.status_code == 409
    assert refused.value.detail["state"] == "acknowledgement_indeterminate"
    assert unresolved["status"] == "open"
    assert unresolved["candidate_answer_ref"]
    assert not draft_path.exists()
    assert candidate is not None
    assert candidate.state == "acknowledgement_indeterminate"

    accepted_event = next(
        record
        for record in iter_jsonl_outbox_records(outbox)
        if record.get("event") == "expansion.create.accepted"
    )
    accepted_path = vault / accepted_event["payload"]["final_note_path"]
    accepted_bytes = accepted_path.read_bytes()
    accepted_path.write_bytes(accepted_bytes + b"\nchanged after receipt")
    monkeypatch.setattr(QuestionStore, "update_review_fields_if_unchanged", successful_ack)
    with pytest.raises(HTTPException) as modified:
        asyncio.run(panel_route.panel_checkbox_projection(request, _panel_request(vault)))
    unresolved_again, _ = store.read_question_with_version(question["question_id"])
    assert modified.value.detail["state"] == "acknowledgement_indeterminate"
    assert unresolved_again["status"] == "open"

    accepted_path.write_bytes(accepted_bytes)
    reconciled = asyncio.run(
        panel_route.panel_checkbox_projection(request, _panel_request(vault))
    )
    answered, _ = store.read_question_with_version(question["question_id"])
    assert reconciled.status == "executed"
    assert reconciled.receipt is not None
    assert reconciled.receipt["idempotent_replay"] is True
    assert answered["status"] == "answered"
    assert answered["candidate_answer_ref"] is None


def test_exp4_recovers_materialization_before_acceptance_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.routes import panel as panel_route
    from app.expansion import accept as accept_module
    from app.panel import checkbox_projection as checkbox_projection_module
    from app.expansion.accept import CREATE_ACCEPTED_EVENT
    from app.services.outbox import iter_jsonl_outbox_records
    from fastapi import HTTPException

    vault, draft_path, outbox, store, question, version = _stage_candidate(tmp_path)
    request = _acceptance_request(
        draft_path, vault=vault, question=question, question_version=version
    )
    service = CheckboxProjectionService(write_guard=_guard())
    monkeypatch.setattr(checkbox_projection_module, "resolve_optional_vault_root", lambda: vault)
    monkeypatch.setattr(panel_route.checkbox_projection_module, "_service", service)
    monkeypatch.setattr(review_module, "resolve_outbox_path", lambda _value: outbox)
    append_receipt = accept_module.append_jsonl_outbox_event

    def fail_first_acceptance_receipt(path: Path, record: dict, **kwargs: Any) -> bool:
        if record.get("event") == CREATE_ACCEPTED_EVENT:
            raise OSError("injected crash after canonical materialization")
        return append_receipt(path, record, **kwargs)

    monkeypatch.setattr(accept_module, "append_jsonl_outbox_event", fail_first_acceptance_receipt)
    with pytest.raises(HTTPException) as refused:
        asyncio.run(panel_route.panel_checkbox_projection(request, _panel_request(vault)))

    unresolved, _ = store.read_question_with_version(question["question_id"])
    assert refused.value.status_code == 409
    assert refused.value.detail["state"] == "acknowledgement_indeterminate"
    assert unresolved["status"] == "open"
    assert unresolved["candidate_answer_ref"]
    assert draft_path.exists()
    from scripts.yaml_roundtrip import load_frontmatter

    accepted_paths = [
        path
        for path in vault.glob("*.md")
        if (load_frontmatter(path.read_text(encoding="utf-8"))[0] or {}).get("authority_state")
        == "accepted"
    ]
    assert len(accepted_paths) == 1
    accepted_bytes = accepted_paths[0].read_bytes()
    from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter

    partial_frontmatter, accepted_body = load_frontmatter(accepted_bytes.decode("utf-8"))
    partial_frontmatter.pop("accepted_at", None)
    accepted_paths[0].write_text(
        dump_frontmatter(partial_frontmatter, accepted_body),
        encoding="utf-8",
    )

    monkeypatch.setattr(accept_module, "append_jsonl_outbox_event", append_receipt)
    with pytest.raises(HTTPException) as partial:
        asyncio.run(panel_route.panel_checkbox_projection(request, _panel_request(vault)))
    assert partial.value.detail["state"] == "acknowledgement_indeterminate"
    assert store.read_question(question["question_id"])["status"] == "open"

    accepted_paths[0].write_bytes(accepted_bytes + b"\nchanged after materialization")
    with pytest.raises(HTTPException) as modified:
        asyncio.run(panel_route.panel_checkbox_projection(request, _panel_request(vault)))
    still_open, _ = store.read_question_with_version(question["question_id"])
    assert modified.value.detail["state"] == "acknowledgement_indeterminate"
    assert still_open["status"] == "open"

    accepted_paths[0].write_bytes(accepted_bytes)
    successful_ack = QuestionStore.update_review_fields_if_unchanged

    def fail_question_ack(*_args: Any, **_kwargs: Any) -> object:
        raise OSError("injected Question acknowledgement failure")

    monkeypatch.setattr(QuestionStore, "update_review_fields_if_unchanged", fail_question_ack)
    with pytest.raises(HTTPException) as ack_failure:
        asyncio.run(panel_route.panel_checkbox_projection(request, _panel_request(vault)))
    assert ack_failure.value.detail["state"] == "acknowledgement_indeterminate"
    assert not draft_path.exists()

    monkeypatch.setattr(QuestionStore, "update_review_fields_if_unchanged", successful_ack)
    receipt_records = [
        json.loads(line)
        for line in outbox.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    accepted_record = next(
        record for record in receipt_records if record.get("event") == CREATE_ACCEPTED_EVENT
    )
    expected_trace_id = accepted_record["trace_id"]
    accepted_record["trace_id"] = "corrupted-trace"
    outbox.write_text(
        "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in receipt_records),
        encoding="utf-8",
    )
    with pytest.raises(HTTPException) as trace_refused:
        asyncio.run(panel_route.panel_checkbox_projection(request, _panel_request(vault)))
    assert trace_refused.value.detail["state"] == "acknowledgement_indeterminate"
    assert store.read_question(question["question_id"])["status"] == "open"

    accepted_record["trace_id"] = expected_trace_id
    outbox.write_text(
        "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in receipt_records),
        encoding="utf-8",
    )
    recovered = asyncio.run(
        panel_route.panel_checkbox_projection(request, _panel_request(vault))
    )
    answered, _ = store.read_question_with_version(question["question_id"])
    accepted_events = [
        record
        for record in iter_jsonl_outbox_records(outbox)
        if record.get("event") == CREATE_ACCEPTED_EVENT
    ]
    assert recovered.status == "executed"
    assert recovered.receipt is not None
    assert answered["status"] == "answered"
    assert answered["candidate_answer_ref"] is None
    assert not draft_path.exists()
    assert len(accepted_events) == 1


def test_dismiss_declines_without_closing_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, draft_path, outbox, store, question, version = _stage_candidate(tmp_path)
    ledger_path = tmp_path / "declined.jsonl"
    monkeypatch.setenv("DECLINED_LEDGER_PATH", str(ledger_path))
    monkeypatch.setattr(review_module, "resolve_outbox_path", lambda _value: outbox)

    result = dismiss_question_candidate(
        question["question_id"],
        vault_root=vault,
        expected_question_version=version,
        write_guard=_guard(),
    )

    updated, _ = store.read_question_with_version(question["question_id"])
    ledger = DeclinedLedger(ledger_path)
    declined_id = draft_path.stem
    assert result["status"] == "open"
    assert updated["status"] == "open"
    assert updated["candidate_answer_ref"] is None
    assert result["decline_receipt_id"]
    assert not draft_path.exists()
    assert ledger.is_declined(declined_id)
    assert not ledger.is_declined("materially-different-future-draft")


def test_explicit_close_and_reopen(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    store = QuestionStore(vault, write_guard=_guard())
    question, _ = store.create_question(
        text="Should this question be closed?",
        scope="work",
        registered_via="explicit",
    )
    _, version = store.read_question_with_version(question["question_id"])

    closed = transition_question_status(
        question["question_id"],
        vault_root=vault,
        expected_question_version=version,
        status="closed",
        write_guard=_guard(),
    )
    closed_question, closed_version = store.read_question_with_version(question["question_id"])
    with pytest.raises(review_module.QuestionReviewError, match="changed"):
        transition_question_status(
            question["question_id"],
            vault_root=vault,
            expected_question_version=version,
            status="open",
            write_guard=_guard(),
        )
    reopened = transition_question_status(
        question["question_id"],
        vault_root=vault,
        expected_question_version=closed_version,
        status="open",
        write_guard=_guard(),
    )

    assert closed["status"] == "closed"
    assert closed_question["status"] == "closed"
    assert reopened["status"] == "open"
    with pytest.raises(HumanOwnedFieldMutationError):
        store.update_system_fields(question["question_id"], {"status": "closed"})


def test_ui_never_writes_authority_fields_directly() -> None:
    from companion_ui.workspace.standing_question_review import standing_question_review_script

    script = standing_question_review_script()
    assert "'/api/panel/checkbox-projection'" in script
    assert "'/api/standing-questions/'" in script
    assert "standing_answer_ref:" not in script
    assert "candidate_answer_ref:" not in script
    assert "status: 'answered'" not in script
    assert "JSON.stringify(payload)" in script
    assert "textContent" in script
