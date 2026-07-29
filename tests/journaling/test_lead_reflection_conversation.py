from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from app.chat.session_log import load_chat_sessions_for_note
from app.journaling.day_context import assemble_day_context
from app.chat.reflection_conversation import (
    ReflectionConversationService,
    ReflectionSettings,
    build_evening_reflection_offer,
    begin_reflection_from_offer,
)
from app.knowledge_acquisition.candidate_writeback import ARTIFACT_CLASS, DEFAULT_SOURCES_DIR
from app.vault.manager import VaultContext


DAY = date(2026, 7, 15)
NOW = datetime(2026, 7, 15, 20, 30, tzinfo=timezone.utc)


def _vault(tmp_path: Path) -> tuple[Path, VaultContext, Path]:
    root = tmp_path / "vault"
    sources = root / DEFAULT_SOURCES_DIR
    sources.mkdir(parents=True)
    (sources / "capture-one.md").write_text(
        f"""---
artifact_class: {ARTIFACT_CLASS}
created: 2026-07-15T09:00:00Z
provenance:
  content_identity: capture-1
  source_kind: note
---
Capture one
""",
        encoding="utf-8",
    )
    note = root / "Notes" / "Reflection anchor.md"
    note.parent.mkdir(parents=True)
    note.write_text("---\nuuid: reflection-anchor\ntype: note\n---\n\nAnchor.\n", encoding="utf-8")
    return root, VaultContext(status="selected", active_vault_path=str(root)), note


def _service(root: Path, responses: list[str]) -> ReflectionConversationService:
    def llm(_kind: str, _pack: dict[str, object]) -> str:
        return responses.pop(0)

    return ReflectionConversationService(vault_root=root, llm_fn=llm, now_fn=lambda: NOW)


def test_conversation_opens_informed_by_day_context(tmp_path: Path) -> None:
    root, context, note = _vault(tmp_path)
    bundle = assemble_day_context(vault_context=context, for_date=DAY)
    seen: list[dict[str, object]] = []

    def llm(kind: str, pack: dict[str, object]) -> str:
        seen.append(pack)
        if kind.endswith("opening"):
            return "What felt most important about capture-1?"
        return "What made that significant?"

    conversation = ReflectionConversationService(
        vault_root=root, llm_fn=llm, now_fn=lambda: NOW
    ).start(note_path=note, day_context=bundle)

    assert "capture-1" in conversation.opening_turn
    assert "capture-1" in str(seen[0])
    assert "**Agent:**" in conversation.session.log_path.read_text(encoding="utf-8")
    assert (
        ReflectionConversationService(
            vault_root=root, llm_fn=llm, now_fn=lambda: NOW
        ).submit_owner_turn(conversation, "It connected several loose ends.")
        == "What made that significant?"
    )
    transcript = conversation.session.log_path.read_text(encoding="utf-8")
    assert "**Owner:** It connected several loose ends." in transcript
    assert "**Agent:** What made that significant?" in transcript


def test_opening_names_degraded_context_honestly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.journaling import day_context

    root, context, note = _vault(tmp_path)
    monkeypatch.setattr(
        day_context,
        "iter_decision_receipts",
        lambda *_: (_ for _ in ()).throw(RuntimeError("unavailable")),
    )
    bundle = assemble_day_context(vault_context=context, for_date=DAY)

    conversation = _service(root, ["What stands out from what is available?"]).start(
        note_path=note, day_context=bundle
    )

    assert "decision receipts" in conversation.opening_turn.lower()
    assert "don't have" in conversation.opening_turn.lower()


def test_owner_can_stop_conversation_at_any_turn(tmp_path: Path) -> None:
    root, context, note = _vault(tmp_path)
    bundle = assemble_day_context(vault_context=context, for_date=DAY)
    service = _service(root, ["What mattered about capture-1?", "What else?"])

    immediately_stopped = service.start(note_path=note, day_context=bundle)
    service.stop(immediately_stopped, reason="owner_stop")
    immediate_text = immediately_stopped.session.log_path.read_text(encoding="utf-8")
    assert immediately_stopped.owner_turn_count == 0
    assert "Session closed" in immediate_text
    assert "What mattered about capture-1?" in immediate_text

    idle = service.start(note_path=note, day_context=bundle)
    assert service.stop_if_idle(
        idle,
        now=NOW + timedelta(seconds=idle.settings.idle_timeout_seconds + 1),
    )
    assert "idle_timeout" in idle.session.log_path.read_text(encoding="utf-8")


def test_evening_nudge_is_offer_only_never_auto_starts() -> None:
    starts: list[str] = []
    settings = ReflectionSettings(
        evening_nudge_enabled=True,
        evening_nudge_start_hour=20,
        evening_nudge_end_hour=22,
        idle_timeout_seconds=900,
        max_owner_turns=5,
    )

    offer = build_evening_reflection_offer(now=NOW, settings=settings)

    assert offer is not None
    assert offer.tap_required is True
    assert starts == []
    result = begin_reflection_from_offer(offer, start=lambda: starts.append("started") or "session")
    assert result == "session"
    assert starts == ["started"]


def test_reflection_session_uses_existing_chat_surface(tmp_path: Path) -> None:
    root, context, note = _vault(tmp_path)
    bundle = assemble_day_context(vault_context=context, for_date=DAY)

    conversation = _service(root, ["What mattered about capture-1?"]).start(
        note_path=note, day_context=bundle
    )
    _service(root, []).stop(conversation, reason="owner_stop")

    sessions = load_chat_sessions_for_note("reflection-anchor", vault_context=context)
    assert [session.session_id for session in sessions] == [conversation.session.session_id]
    assert conversation.session.log_path.is_relative_to(root / ".chats")


def test_default_reflection_path_requires_provider_when_enforcement_is_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, context, note = _vault(tmp_path)
    bundle = assemble_day_context(vault_context=context, for_date=DAY)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("LLM_PROVIDER_ENFORCE", "1")

    service = ReflectionConversationService(vault_root=root, now_fn=lambda: NOW)

    with pytest.raises(RuntimeError, match="LLM_PROVIDER is required"):
        service.start(note_path=note, day_context=bundle)


def test_real_provider_receives_day_context_and_transcript_in_user_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the provider boundary, not the injected whole-pack test seam."""
    from app.services import llm as llm_module

    root, context, note = _vault(tmp_path)
    bundle = assemble_day_context(vault_context=context, for_date=DAY)
    provider_messages: list[list[dict[str, str]]] = []

    def fake_http_chat(**kwargs: object) -> tuple[str, dict[str, str]]:
        messages = kwargs["messages"]
        assert isinstance(messages, list)
        provider_messages.append(messages)
        response = (
            "What felt most important about that capture?"
            if len(provider_messages) == 1
            else "What made those loose ends connect?"
        )
        return response, {"content": response}

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE", "http://provider.test/chat/completions")
    monkeypatch.setattr(llm_module, "_http_chat", fake_http_chat)
    settings = ReflectionSettings(
        evening_nudge_enabled=False,
        evening_nudge_start_hour=20,
        evening_nudge_end_hour=22,
        idle_timeout_seconds=900,
        max_owner_turns=5,
    )
    service = ReflectionConversationService(
        vault_root=root,
        now_fn=lambda: NOW,
        settings=settings,
    )

    conversation = service.start(note_path=note, day_context=bundle)
    service.submit_owner_turn(conversation, "It connected several loose ends.")

    opening_user = json.loads(provider_messages[0][1]["content"])
    assert opening_user["day_context"]["for_date"] == "2026-07-15"
    assert opening_user["concrete_anchor"] == "capture-1"
    assert "grounded" in opening_user["instruction"]
    followup_user = json.loads(provider_messages[1][1]["content"])
    assert followup_user["transcript"][-1] == {
        "role": "owner",
        "content": "It connected several loose ends.",
    }
    assert followup_user["remaining_owner_turns"] == 4


def test_opening_provider_failure_leaves_no_empty_chat_session(tmp_path: Path) -> None:
    root, context, note = _vault(tmp_path)
    bundle = assemble_day_context(vault_context=context, for_date=DAY)

    def failing_llm(_kind: str, _pack: dict[str, object]) -> str:
        raise RuntimeError("provider unavailable")

    service = ReflectionConversationService(
        vault_root=root,
        llm_fn=failing_llm,
        now_fn=lambda: NOW,
        settings=ReflectionSettings(
            evening_nudge_enabled=False,
            evening_nudge_start_hour=20,
            evening_nudge_end_hour=22,
            idle_timeout_seconds=900,
            max_owner_turns=5,
        ),
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        service.start(note_path=note, day_context=bundle)

    assert not list((root / ".chats").rglob("*.md"))
