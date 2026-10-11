from __future__ import annotations

from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import tests.journaling.live_journaling_acceptance as live
from app.chat.reflection_conversation import (
    ReflectionConversationService,
    ReflectionSettings,
)
from app.domain.commitments import CommitmentRecord
from app.journaling.draft import draft_journal_entry
from app.journaling.review import process_journal_reviews_tick
from app.knowledge_acquisition.candidate_writeback import DEFAULT_SOURCES_DIR
from app.reasoning.schema import ReasoningOutput
from app.receipts.decision_receipt_log import append_decision_receipt
from app.services.commitment_persistence import commitment_artifact_path, persist_commitment
from app.journaling.review import JournalReviewState
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard
from scripts.yaml_roundtrip import dump_frontmatter


DAY = date(2026, 10, 11)
SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64


def _private_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)


def _manifest_payload(tmp_path: Path) -> tuple[Path, dict[str, object], Path]:
    vault = (tmp_path / "vault").resolve()
    output = (tmp_path / "evidence").resolve()
    vault.mkdir()
    output.mkdir()
    anchor = vault / "Notes" / "Evening.md"
    anchor.parent.mkdir()
    anchor.write_text("---\nuuid: evening\ntype: note\n---\nEvening\n", encoding="utf-8")
    marker = {
        "run_id": "jrnl-acceptance-1",
        "fixture_id": "jrnl-fixture-1",
        "actor_id": live.SYNTHETIC_ACTOR_ID,
        "channel": "test",
        "for_date": DAY.isoformat(),
    }
    _private_json(vault / ".journal-acceptance-fixture.json", marker)
    payload: dict[str, object] = {
        "channel": "test",
        "expected_sha": SHA,
        "observed_sha": SHA,
        "expected_image_digest": DIGEST,
        "observed_image_digest": DIGEST,
        "run_id": marker["run_id"],
        "fixture_id": marker["fixture_id"],
        "actor_id": marker["actor_id"],
        "for_date": marker["for_date"],
        "vault_root": str(vault),
        "anchor_note": "Notes/Evening.md",
        "outbox_path": str(output / "journal-review-outbox.jsonl"),
        "output_dir": str(output),
        "effect_budget": dict(live.REQUIRED_EFFECT_BUDGET),
    }
    manifest_path = tmp_path / "manifest.json"
    _private_json(manifest_path, payload)
    return manifest_path, payload, vault


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_preflight_rejects_unknown_identity_before_product_write(tmp_path: Path) -> None:
    manifest_path, payload, vault = _manifest_payload(tmp_path)
    before = _tree(vault)
    payload["observed_sha"] = "c" * 40
    _private_json(manifest_path, payload)

    with pytest.raises(live.QualificationRefused, match="source_identity_mismatch"):
        live.load_manifest(manifest_path, today=DAY)

    assert _tree(vault) == before
    assert not (tmp_path / "evidence" / "journal-review-outbox.jsonl").exists()


def test_required_scenarios_and_actual_proof_gate_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, _payload, _vault = _manifest_payload(tmp_path)
    manifest = live.load_manifest(manifest_path, today=DAY)
    incomplete = SimpleNamespace(
        sections={
            "commitments": SimpleNamespace(status="available", items=(object(),)),
            "decision_receipts": SimpleNamespace(status="available", items=()),
            "captures": SimpleNamespace(status="available", items=(object(),)),
        }
    )
    monkeypatch.setattr(live, "assemble_day_context", lambda **_kwargs: incomplete)

    report = live.run_qualified_journey(manifest)

    assert report.feature_acceptance == "BLOCKED"
    assert [item.name for item in report.scenarios] == list(live.REQUIRED_SCENARIOS)
    assert report.scenarios[1].outcome == "blocked"
    assert all(item.outcome != "passed" for item in report.scenarios[2:])


def _install_successful_product_seams(
    monkeypatch: pytest.MonkeyPatch,
    manifest: live.QualifiedManifest,
    *,
    mutate_primary_on_second_draft: bool = False,
) -> dict[str, int]:
    calls = {"assemble": 0, "conversations": 0, "drafts": 0, "review": 0}
    bundle = SimpleNamespace(
        sections={
            name: SimpleNamespace(status="available", items=(object(),))
            for name in ("commitments", "decision_receipts", "captures")
        }
    )

    def assemble(**_kwargs: object) -> object:
        calls["assemble"] += 1
        return bundle

    class FakeConversationService:
        def __init__(self, *, vault_root: Path) -> None:
            assert vault_root == manifest.vault_root

        def start(self, *, note_path: Path, day_context: object) -> object:
            assert note_path == manifest.vault_root / manifest.anchor_note
            assert day_context is bundle
            calls["conversations"] += 1
            session_id = f"session-{calls['conversations']}"
            transcript = manifest.vault_root / ".chats" / f"{session_id}.md"
            transcript.parent.mkdir(exist_ok=True)
            transcript.write_text("**Agent:** Opening\n", encoding="utf-8")
            return SimpleNamespace(
                session=SimpleNamespace(session_id=session_id, log_path=transcript),
                owner_turn_count=0,
                closed=False,
            )

        def submit_owner_turn(self, conversation: object, text: str) -> str | None:
            if text == "/stop":
                conversation.closed = True
                return None
            conversation.owner_turn_count += 1
            with conversation.session.log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"**Owner:** {text}\n**Agent:** Follow-up\n")
            return "Follow-up"

    def draft(**kwargs: object) -> object:
        calls["drafts"] += 1
        is_addendum = calls["drafts"] == 2
        if is_addendum and mutate_primary_on_second_draft:
            canonical = manifest.vault_root / "1_Calendar" / "Daily" / f"{DAY}.md"
            canonical.write_text(canonical.read_text(encoding="utf-8") + "changed\n")
        name = f"{DAY}{'-addendum' if is_addendum else ''}.md"
        relative = Path("_system") / "drafts" / "journal" / name
        path = manifest.vault_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        session_id = str(kwargs["session_id"])
        frontmatter = {
            "uuid": f"draft-{calls['drafts']}",
            "journal_candidate_type": "addendum" if is_addendum else "primary",
            "derived_by": "conversation",
            "authority_state": "proposal",
            "sources": [f"session:{session_id}", "Sources/capture.md"],
        }
        label = (
            "Accept and append this addendum to today's journal"
            if is_addendum
            else "Accept this draft as today's journal entry"
        )
        body = (
            "Reflection.[^conversation-1] Context.[^context-1]\n\n"
            f"[^conversation-1]: session:{session_id}\n"
            "[^context-1]: Sources/capture.md\n\n"
            "## AI-åtgärder\n\n"
            f"- [ ] {label}\n"
        )
        path.write_text(dump_frontmatter(frontmatter, body), encoding="utf-8")
        return SimpleNamespace(path=relative.as_posix(), is_addendum=is_addendum)

    def review_tick(**kwargs: object) -> object:
        calls["review"] += 1
        outbox = Path(str(kwargs["outbox_path"]))
        outbox.write_text('{"event":"journal.entry.accepted"}\n', encoding="utf-8")
        canonical_rel = Path("1_Calendar") / "Daily" / f"{DAY}.md"
        canonical = manifest.vault_root / canonical_rel
        canonical.parent.mkdir(parents=True, exist_ok=True)
        canonical.write_text(
            dump_frontmatter(
                {
                    "authority_state": "accepted",
                    "acceptance_receipt_id": "journal-accept-1",
                    "accepted_by": "human",
                },
                "Accepted synthetic journal.\n",
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(
            errors=(),
            results=(
                SimpleNamespace(
                    state=JournalReviewState.FULLY_MATERIALIZED,
                    action="accept",
                    receipt_id="journal-accept-1",
                    canonical_path=canonical_rel.as_posix(),
                ),
            ),
        )

    monkeypatch.setattr(live, "assemble_day_context", assemble)
    monkeypatch.setattr(live, "ReflectionConversationService", FakeConversationService)
    monkeypatch.setattr(live, "draft_journal_entry", draft)
    monkeypatch.setattr(live, "process_journal_reviews_tick", review_tick)
    return calls


def _seed_real_day_context(manifest: live.QualifiedManifest) -> None:
    context = VaultContext(status="selected", active_vault_path=str(manifest.vault_root))
    guard = WriteGuard(lambda: {"state": "healthy"})
    commitment = CommitmentRecord(
        "acceptance-commitment",
        "next_action",
        "done",
        summary="Finished the synthetic acceptance task",
    )
    persist_commitment(commitment, vault_context=context, write_guard=guard)
    changed = datetime.combine(
        manifest.for_date,
        datetime.min.time(),
        tzinfo=timezone.utc,
    ).replace(hour=12)
    commitment_path = manifest.vault_root / commitment_artifact_path(
        commitment.commitment_id,
        manifest.vault_root,
    )
    os.utime(commitment_path, (changed.timestamp(), changed.timestamp()))
    append_decision_receipt(
        object_id="acceptance-object",
        key="review",
        value={},
        trace_id="acceptance-trace",
        created_at=changed,
        vault_root=manifest.vault_root,
        vault_uuid="synthetic-vault",
    )
    sources = manifest.vault_root / DEFAULT_SOURCES_DIR
    sources.mkdir()
    (sources / "capture.md").write_text(
        f"""---
artifact_class: youtube_source_note
created: {changed.isoformat()}
provenance:
  content_identity: sha256:acceptance-capture
  source_kind: synthetic
  url: https://example.test/journal-acceptance
---
Synthetic capture.
""",
        encoding="utf-8",
    )


def _install_real_product_seams(
    monkeypatch: pytest.MonkeyPatch,
    manifest: live.QualifiedManifest,
) -> None:
    responses = iter(
        (
            "What felt most important about that?",
            "What will you remember from it?",
            "What felt most important in the second reflection?",
            "What changed since the first one?",
        )
    )
    fixed_now = datetime.combine(
        manifest.for_date,
        datetime.min.time(),
        tzinfo=timezone.utc,
    ).replace(hour=20)
    settings = ReflectionSettings(
        evening_nudge_enabled=False,
        evening_nudge_start_hour=20,
        evening_nudge_end_hour=22,
        idle_timeout_seconds=900,
        max_owner_turns=5,
    )
    guard = WriteGuard(lambda: {"state": "healthy"})

    def conversation_factory(*, vault_root: Path) -> ReflectionConversationService:
        return ReflectionConversationService(
            vault_root=vault_root,
            llm_fn=lambda _kind, _pack: next(responses),
            now_fn=lambda: fixed_now,
            settings=settings,
        )

    def real_draft(**kwargs: object) -> object:
        return draft_journal_entry(
            **kwargs,  # type: ignore[arg-type]
            write_guard=guard,
            reasoning_fn=lambda _ids, trace_id=None: ReasoningOutput(),
            now=fixed_now,
        )

    def real_review(**kwargs: object) -> object:
        return process_journal_reviews_tick(
            **kwargs,  # type: ignore[arg-type]
            write_guard=guard,
            now=fixed_now,
        )

    monkeypatch.setattr(live, "ReflectionConversationService", conversation_factory)
    monkeypatch.setattr(live, "draft_journal_entry", real_draft)
    monkeypatch.setattr(live, "process_journal_reviews_tick", real_review)


def test_runner_binds_production_artifacts_and_synthetic_actor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, _payload, _vault = _manifest_payload(tmp_path)
    manifest = live.load_manifest(manifest_path, today=DAY)
    calls = _install_successful_product_seams(monkeypatch, manifest)

    report = live.run_qualified_journey(manifest)

    assert report.feature_acceptance == "PASS", report.as_payload()
    assert report.actor_id == live.SYNTHETIC_ACTOR_ID
    assert all(item.outcome == "passed" for item in report.scenarios)
    assert calls == {"assemble": 1, "conversations": 2, "drafts": 2, "review": 1}
    assert report.effects == live.REQUIRED_EFFECT_BUDGET
    assert report.artifacts["acceptance_receipt_id"] == "journal-accept-1"
    assert report.artifacts["primary_transcript_sha256"]
    assert report.artifacts["addendum_candidate_sha256"]


def test_current_full_day_context_reports_exact_source_admission_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, _payload, _vault = _manifest_payload(tmp_path)
    manifest = live.load_manifest(manifest_path, today=DAY)
    _seed_real_day_context(manifest)
    _install_real_product_seams(monkeypatch, manifest)

    report = live.run_qualified_journey(manifest)

    assert report.feature_acceptance == "FAIL"
    assert report.limitation is not None
    assert "JournalDraftBlockedError" in report.limitation
    assert "provenance_unverified" in report.limitation
    assert report.effects == {
        "conversation_sessions": 1,
        "candidate_writes": 0,
        "actor_checkbox_writes": 0,
        "canonical_accepts": 0,
    }


def test_second_session_proves_primary_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, _payload, _vault = _manifest_payload(tmp_path)
    manifest = live.load_manifest(manifest_path, today=DAY)
    _install_successful_product_seams(
        monkeypatch,
        manifest,
        mutate_primary_on_second_draft=True,
    )

    report = live.run_qualified_journey(manifest)

    assert report.feature_acceptance == "FAIL"
    by_name = {item.name: item for item in report.scenarios}
    assert by_name["never_overwrite"].outcome == "failed"
    assert "accepted primary bytes changed" in by_name["never_overwrite"].detail
    assert report.artifacts["canonical_before_sha256"] != report.artifacts.get(
        "canonical_after_sha256"
    )


def test_receipt_is_private_atomic_and_cannot_be_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, _payload, _vault = _manifest_payload(tmp_path)
    manifest = live.load_manifest(manifest_path, today=DAY)
    _install_successful_product_seams(monkeypatch, manifest)
    report = live.run_qualified_journey(manifest)

    path = live.write_receipt(report, output_dir=manifest.output_dir)

    assert path.parent == manifest.output_dir
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text(encoding="utf-8"))["schema"] == live.RECEIPT_SCHEMA
    with pytest.raises(live.QualificationRefused, match="already_exists"):
        live.write_receipt(report, output_dir=manifest.output_dir)


@pytest.mark.parametrize("channel", ["prod", "staging", ""])
def test_manifest_refuses_non_dev_test_channels(
    tmp_path: Path, channel: str
) -> None:
    manifest_path, payload, _vault = _manifest_payload(tmp_path)
    payload["channel"] = channel
    _private_json(manifest_path, payload)
    with pytest.raises(live.QualificationRefused, match="only_dev_and_test"):
        live.load_manifest(manifest_path, today=DAY)

