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


@pytest.mark.parametrize("legacy_markers", [False, True])
def test_accept_projects_checkbox_and_flips_status_atomically(
    legacy_markers: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import panel as panel_route
    from app.api.routes import standing_questions as standing_question_routes
    from app.panel import checkbox_projection as checkbox_projection_module
    from scripts.yaml_roundtrip import load_frontmatter

    vault, draft_path, outbox, store, question, version = _stage_candidate(tmp_path)
    if legacy_markers:
        draft_text = draft_path.read_text(encoding="utf-8")
        marker = (
            f" <!--ai:option_id=sq_answer_{draft_path.stem}--> "
            "<!--ai:proposed=exp4-->"
        )
        assert marker in draft_text
        draft_path.write_text(draft_text.replace(marker, "", 1), encoding="utf-8")
    candidate = standing_question_routes._candidate_answer(
        {"candidate_answer_ref": question["candidate_answer_ref"]},
        question_id=question["question_id"],
        question_version=version,
        vault_root=vault,
    )
    assert candidate is not None
    assert candidate.state == "pending"
    assert candidate.acceptance_control is not None
    request = CheckboxProjectionRequest.model_validate(candidate.acceptance_control)
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


def test_accept_refuses_candidate_edit_after_checkbox_projection(
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
    load_draft = accept_module._load_draft

    def edit_before_exp4_load(path: Path, **kwargs: Any):
        current = draft_path.read_text(encoding="utf-8")
        draft_path.write_text(current + "\nA manual edit after the approval click.\n", encoding="utf-8")
        return load_draft(path, **kwargs)

    monkeypatch.setattr(accept_module, "_load_draft", edit_before_exp4_load)

    with pytest.raises(HTTPException) as refused:
        asyncio.run(panel_route.panel_checkbox_projection(request, _panel_request(vault)))

    current, _ = store.read_question_with_version(question["question_id"])
    assert refused.value.detail["error"] == "stale_acceptance_control"
    assert current["status"] == "open"
    assert current["candidate_answer_ref"] == question["candidate_answer_ref"]
    assert draft_path.exists()
    assert "A manual edit after the approval click." in draft_path.read_text(encoding="utf-8")
    assert not any(
        record.get("event") == "expansion.create.accepted"
        for record in (
            json.loads(line)
            for line in outbox.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    )


@pytest.mark.parametrize("edit_mode", ["in_place", "atomic_replace"])
def test_accept_preserves_candidate_edit_arriving_after_exp4_load(
    edit_mode: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import panel as panel_route
    from app.expansion import accept as accept_module
    from app.panel import checkbox_projection as checkbox_projection_module
    from app.services.outbox import iter_jsonl_outbox_records
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
    retire = accept_module._retire_loaded_draft_if_unchanged
    marker = f"Manual edit after EXP-4 loaded the approved bytes ({edit_mode})."

    def edit_before_retirement(loaded: Any, *, receipt_id: str) -> str:
        updated = draft_path.read_text(encoding="utf-8") + f"\n{marker}\n"
        if edit_mode == "atomic_replace":
            replacement = draft_path.with_name(f"{draft_path.name}.replacement")
            replacement.write_text(updated, encoding="utf-8")
            replacement.replace(draft_path)
        else:
            draft_path.write_text(updated, encoding="utf-8")
        return retire(loaded, receipt_id=receipt_id)

    monkeypatch.setattr(accept_module, "_retire_loaded_draft_if_unchanged", edit_before_retirement)

    with pytest.raises(HTTPException) as unresolved:
        asyncio.run(panel_route.panel_checkbox_projection(request, _panel_request(vault)))

    answered, _ = store.read_question_with_version(question["question_id"])
    assert unresolved.value.detail["state"] == "acknowledgement_indeterminate"
    assert answered["status"] == "open"
    assert answered["candidate_answer_ref"] == question["candidate_answer_ref"]
    assert draft_path.exists()
    assert marker in draft_path.read_text(encoding="utf-8")
    accepted_event = next(
        record
        for record in iter_jsonl_outbox_records(outbox)
        if record.get("event") == "expansion.create.accepted"
    )
    accepted_path = vault / accepted_event["payload"]["final_note_path"]
    _accepted_frontmatter, accepted_body = load_frontmatter(
        accepted_path.read_text(encoding="utf-8")
    )
    assert marker not in accepted_body


def test_accept_refuses_candidate_owned_by_nested_child_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.standing_questions.review import QuestionReviewError

    vault, draft_path, outbox, store, question, version = _stage_candidate(tmp_path)
    child = vault / "private-child"
    marker = child / "settings" / "vault.md"
    marker.parent.mkdir(parents=True)
    marker.write_text("id: private-child\n", encoding="utf-8")
    child_draft = child / draft_path.name
    child_draft.write_bytes(draft_path.read_bytes())
    draft_path.unlink()
    current, current_version = store.read_question_with_version(question["question_id"])
    store.update_system_fields_if_unchanged(
        question["question_id"],
        current,
        {"candidate_answer_ref": f"vault://private-child/{child_draft.name}"},
        expected_version=current_version,
    )
    updated_question, updated_version = store.read_question_with_version(question["question_id"])
    request = _acceptance_request(
        child_draft, vault=vault, question=updated_question, question_version=updated_version
    )
    monkeypatch.setattr(review_module, "resolve_outbox_path", lambda _value: outbox)

    with pytest.raises(QuestionReviewError) as accept_refused:
        review_module.prepare_question_acceptance(request, vault_root=vault)
    with pytest.raises(QuestionReviewError) as dismiss_refused:
        dismiss_question_candidate(
            question["question_id"],
            vault_root=vault,
            expected_question_version=updated_version,
            write_guard=_guard(),
        )

    still_open, _ = store.read_question_with_version(question["question_id"])
    assert accept_refused.value.detail["error"] == "candidate_outside_vault"
    assert dismiss_refused.value.detail["error"] == "candidate_outside_vault"
    assert still_open["status"] == "open"
    assert still_open["candidate_answer_ref"] == f"vault://private-child/{child_draft.name}"
    assert child_draft.exists()


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


def test_accept_reconciles_matcher_write_that_wins_question_cas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.routes import panel as panel_route
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
    accept = review_module.accept_draft

    def accept_after_matcher_write(candidate_path: Path, **kwargs: Any):
        current, current_version = store.read_question_with_version(question["question_id"])
        entry = {
            "artifact_ref": "note:matched-during-acceptance",
            "source_stream": "vault.activity",
            "matched_at": "2026-10-25T10:05:00Z",
            "confidence_class": "high",
            "provenance_ref": "receipt:matcher-race",
            "quoted_span": "New evidence arrived during acceptance.",
            "content_hash": "2" * 64,
        }
        store.update_system_fields_if_unchanged(
            question["question_id"],
            current,
            {"evidence": [*current["evidence"], entry]},
            expected_version=current_version,
        )
        return accept(candidate_path, **kwargs)

    monkeypatch.setattr(review_module, "accept_draft", accept_after_matcher_write)

    with pytest.raises(HTTPException) as indeterminate:
        asyncio.run(panel_route.panel_checkbox_projection(request, _panel_request(vault)))

    unresolved, new_version = store.read_question_with_version(question["question_id"])
    assert indeterminate.value.detail["state"] == "acknowledgement_indeterminate"
    assert unresolved["status"] == "open"
    assert unresolved["candidate_answer_ref"] == question["candidate_answer_ref"]
    assert unresolved["evidence"][-1]["provenance_ref"] == "receipt:matcher-race"
    assert not draft_path.exists()

    retry = request.model_copy(update={"expected_question_version": new_version})
    recovered = asyncio.run(panel_route.panel_checkbox_projection(retry, _panel_request(vault)))
    answered, _ = store.read_question_with_version(question["question_id"])

    assert recovered.status == "executed"
    assert recovered.receipt is not None
    assert recovered.receipt["idempotent_replay"] is True
    assert answered["status"] == "answered"
    assert answered["candidate_answer_ref"] is None
    assert answered["evidence"][-1]["provenance_ref"] == "receipt:matcher-race"


def test_accept_recovery_preserves_candidate_edit_arriving_after_exp4_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.routes import panel as panel_route
    from app.expansion import accept as accept_module
    from app.expansion.accept import CREATE_ACCEPTED_EVENT
    from app.panel import checkbox_projection as checkbox_projection_module
    from app.services.outbox import iter_jsonl_outbox_records
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
    append_receipt = accept_module.append_jsonl_outbox_event

    def fail_first_acceptance_receipt(path: Path, record: dict, **kwargs: Any) -> bool:
        if record.get("event") == CREATE_ACCEPTED_EVENT:
            raise OSError("injected crash after canonical materialization")
        return append_receipt(path, record, **kwargs)

    monkeypatch.setattr(accept_module, "append_jsonl_outbox_event", fail_first_acceptance_receipt)
    with pytest.raises(HTTPException) as interrupted:
        asyncio.run(panel_route.panel_checkbox_projection(request, _panel_request(vault)))
    assert interrupted.value.detail["state"] == "acknowledgement_indeterminate"
    assert draft_path.exists()

    monkeypatch.setattr(accept_module, "append_jsonl_outbox_event", append_receipt)
    retire = accept_module._retire_loaded_draft_if_unchanged
    marker = "Manual edit after EXP-4 loaded the recovery candidate."

    def edit_before_recovery_retirement(loaded: Any, *, receipt_id: str) -> str:
        draft_path.write_text(
            draft_path.read_text(encoding="utf-8") + f"\n{marker}\n",
            encoding="utf-8",
        )
        return retire(loaded, receipt_id=receipt_id)

    monkeypatch.setattr(
        accept_module,
        "_retire_loaded_draft_if_unchanged",
        edit_before_recovery_retirement,
    )
    with pytest.raises(HTTPException) as unresolved:
        asyncio.run(panel_route.panel_checkbox_projection(request, _panel_request(vault)))

    answered, _ = store.read_question_with_version(question["question_id"])
    assert unresolved.value.detail["state"] == "acknowledgement_indeterminate"
    assert answered["status"] == "open"
    assert answered["candidate_answer_ref"] == question["candidate_answer_ref"]
    assert draft_path.exists()
    assert marker in draft_path.read_text(encoding="utf-8")
    accepted_event = next(
        record
        for record in iter_jsonl_outbox_records(outbox)
        if record.get("event") == CREATE_ACCEPTED_EVENT
    )
    accepted_path = vault / accepted_event["payload"]["final_note_path"]
    _accepted_frontmatter, accepted_body = load_frontmatter(
        accepted_path.read_text(encoding="utf-8")
    )
    assert marker not in accepted_body


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


@pytest.mark.parametrize("failure_kind", ["conflict", "io"])
def test_dismiss_surfaces_indeterminate_after_durable_decline_if_question_cas_fails(
    failure_kind: str,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.knowledge.errors import KnowledgeWriteConflict

    vault, draft_path, outbox, store, question, version = _stage_candidate(tmp_path)
    ledger_path = tmp_path / "declined.jsonl"
    monkeypatch.setenv("DECLINED_LEDGER_PATH", str(ledger_path))
    monkeypatch.setattr(review_module, "resolve_outbox_path", lambda _value: outbox)
    update_review = QuestionStore.update_review_fields_if_unchanged

    def fail_question_ack(*_args: object, **_kwargs: object) -> object:
        if failure_kind == "conflict":
            raise KnowledgeWriteConflict("injected post-decline Question CAS failure")
        raise OSError("injected post-decline Question write failure")

    monkeypatch.setattr(QuestionStore, "update_review_fields_if_unchanged", fail_question_ack)

    with pytest.raises(review_module.QuestionReviewError) as indeterminate:
        dismiss_question_candidate(
            question["question_id"],
            vault_root=vault,
            expected_question_version=version,
            write_guard=_guard(),
        )

    unresolved, _ = store.read_question_with_version(question["question_id"])
    ledger = DeclinedLedger(ledger_path)
    receipt = ledger.get_receipt(draft_path.stem)
    events = [
        json.loads(line)
        for line in outbox.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    decline_event = next(event for event in events if event.get("event") == "expansion.create.declined")

    assert indeterminate.value.detail["error"] == "acknowledgement_indeterminate"
    assert indeterminate.value.detail["state"] == "acknowledgement_indeterminate"
    assert indeterminate.value.detail["decline_receipt_id"]
    assert unresolved["status"] == "open"
    assert unresolved["candidate_answer_ref"] == question["candidate_answer_ref"]
    assert not draft_path.exists()
    assert receipt is not None
    assert receipt.reason == "standing_question_candidate_dismissed"
    assert decline_event["payload"]["draft_id"] == draft_path.stem

    monkeypatch.setattr(QuestionStore, "update_review_fields_if_unchanged", update_review)
    reconciled = dismiss_question_candidate(
        question["question_id"],
        vault_root=vault,
        expected_question_version=version,
        write_guard=_guard(),
    )
    resolved, _ = store.read_question_with_version(question["question_id"])
    assert reconciled["idempotent_replay"] is True
    assert resolved["candidate_answer_ref"] is None
    assert resolved["status"] == "open"


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


def test_close_and_reopen_preserves_existing_standing_answer_ref(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    store = QuestionStore(vault, write_guard=_guard())
    question, _ = store.create_question(
        text="Should this answered question be reopened?",
        scope="work",
        registered_via="explicit",
    )
    question, version = store.read_question_with_version(question["question_id"])
    question, _ = store.update_system_fields_if_unchanged(
        question["question_id"],
        question,
        {"standing_answer_ref": "vault://Answers/current.md"},
        expected_version=version,
    )
    _, version = store.read_question_with_version(question["question_id"])

    transition_question_status(
        question["question_id"],
        vault_root=vault,
        expected_question_version=version,
        status="closed",
        write_guard=_guard(),
    )
    closed, closed_version = store.read_question_with_version(question["question_id"])
    reopened = transition_question_status(
        question["question_id"],
        vault_root=vault,
        expected_question_version=closed_version,
        status="open",
        write_guard=_guard(),
    )
    current, _ = store.read_question_with_version(question["question_id"])

    assert closed["status"] == "closed"
    assert reopened["status"] == "open"
    assert current["standing_answer_ref"] == "vault://Answers/current.md"


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
