from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Any

from fastapi.testclient import TestClient
import pytest

from app.api.app import app
from app.api.routes import ask, companion, vault_resolution
import app.chat.session_log as session_log
from tests.voice.conftest import WAV, ask_state


@pytest.mark.parametrize("retained", [False, True])
def test_concurrent_http_selection_waits_for_voice_ask_and_transcript(
    voice_vault: Path,
    voice_success: None,
    monkeypatch: pytest.MonkeyPatch,
    retained: bool,
) -> None:
    """A real sync selection worker cannot move the vault mid voice effect."""
    manager = vault_resolution.get_vault_manager()
    other = voice_vault.parent / "other-vault"
    manager.initialize_vault(other, vault_name="other", remember=False)
    manager.select_vault(voice_vault, remember=False)
    monkeypatch.setattr(companion, "get_vault_manager", lambda: manager)
    voice_client = TestClient(app)
    selection_client = TestClient(app)
    form: dict[str, str] = {}
    if retained:
        first = voice_client.post(
            "/api/ask/voice", files={"audio": ("question.wav", WAV, "audio/wav")}
        )
        assert first.status_code == 200, first.text
        assert first.json()["session_error"] is None
        form["session_id"] = first.json()["session_id"]
        form["end_session"] = "true"
    before = {
        p: p.read_bytes()
        for vault in (voice_vault, other)
        for p in vault.rglob("*")
        if p.is_file() and not p.is_relative_to(vault / ".chats")
    }
    ask_started = Event()
    finish_ask = Event()
    selection_attempted = Event()
    selection_inside = Event()
    original_select = manager.select_vault
    original_inner_select = manager._select_vault_locked
    original_create = session_log.write_note_relative
    original_append = session_log.append_note_relative
    original_plan = ask.build_tts_plan
    write_calls: list[str] = []

    def select(path: Path, *, remember: bool = True):
        selection_attempted.set()
        return original_select(path, remember=remember)

    def inner_select(path: Path, *, remember: bool):
        selection_inside.set()
        return original_inner_select(path, remember=remember)

    def grounded_fixture(*_, **__):
        ask_started.set()
        assert finish_ask.wait(10), "test did not release the ASK worker"
        root = vault_resolution.resolve_active_vault_root(require_initialized=True)
        return ask_state(f"Answer from {root.name}")

    def assert_selection_stable() -> None:
        assert not selection_inside.wait(0.25), "selection entered during transcript I/O"
        assert vault_resolution.resolve_active_vault_root(require_initialized=True) == voice_vault

    def create(relative_path: str, *args: Any, **kwargs: Any):
        assert_selection_stable()
        write_calls.append("create_once")
        result = original_create(relative_path, *args, **kwargs)
        assert_selection_stable()
        return result

    def append(relative_path: str, *args: Any, **kwargs: Any):
        assert_selection_stable()
        write_calls.append("append")
        result = original_append(relative_path, *args, **kwargs)
        assert_selection_stable()
        return result

    def speech_plan(**kwargs: Any):
        # The selection request must enter before derived TTS planning: the
        # effect window owns retrieval/transcript publication, not speech.
        assert selection_inside.wait(10), "voice kept the selector locked during TTS"
        return original_plan(**kwargs)

    monkeypatch.setattr(manager, "select_vault", select)
    monkeypatch.setattr(manager, "_select_vault_locked", inner_select)
    monkeypatch.setattr(ask, "run_ask_graph", grounded_fixture)
    monkeypatch.setattr(session_log, "write_note_relative", create)
    monkeypatch.setattr(session_log, "append_note_relative", append)
    monkeypatch.setattr(ask, "build_tts_plan", speech_plan)
    with ThreadPoolExecutor(max_workers=2) as pool:
        turn = pool.submit(
            voice_client.post,
            "/api/ask/voice",
            files={"audio": ("question.wav", WAV, "audio/wav")},
            data=form,
        )
        try:
            assert ask_started.wait(10), "voice request did not enter ASK"
            selection = pool.submit(
                selection_client.post,
                "/api/companion/vault/select",
                json={"path": str(other), "remember": False},
            )
            assert selection_attempted.wait(10), "selection worker did not call the real manager"
            crossed_effect_window = selection_inside.wait(1)
            if crossed_effect_window:
                # On the unfenced implementation, positively wait for actual
                # B selection before releasing ASK; this makes the red leak
                # deterministic rather than relying on scheduler timing.
                response = selection.result(timeout=10)
                assert response.status_code == 200, response.text
                assert manager.context.active_vault_path == str(other)
        finally:
            finish_ask.set()
        voice_response = turn.result(timeout=10)
        selection_response = selection.result(timeout=10)

    assert voice_response.status_code == selection_response.status_code == 200
    assert voice_response.json()["session_error"] is None
    transcripts = list((voice_vault / ".chats").glob("**/*.md"))
    assert voice_response.json()["answer"] == "Answer from voice-vault", (
        "concurrent selection changed retrieval while recording still targets vault A: "
        f"answer={voice_response.json().get('answer')!r}, "
        f"selection_entered_during_ask={crossed_effect_window}, "
        f"vault_a_transcripts={len(transcripts)}"
    )
    assert not crossed_effect_window
    assert write_calls == (["append", "append"] if retained else ["create_once", "append"])
    assert manager.context.active_vault_path == str(other)
    assert transcripts and all("Answer from other-vault" not in p.read_text() for p in transcripts)
    assert not (other / ".chats").exists()
    assert all(p.read_bytes() == content for p, content in before.items())
    assert not (voice_vault / ".canvas-sessions").exists()
    assert not (other / ".canvas-sessions").exists()
    lost = voice_client.post(
        "/api/ask/voice",
        files={"audio": ("question.wav", WAV, "audio/wav")},
        data={"session_id": voice_response.json()["session_id"]},
    )
    assert lost.status_code == 409
    assert lost.json()["detail"]["error"] == "voice_session_context_lost"


def test_lazy_restore_waits_for_selection_window_and_exception_releases_it(
    voice_vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = vault_resolution.get_vault_manager()
    attempted = Event()
    loaded = Event()
    original_load = manager.app_local_store.load

    def load():
        loaded.set()
        return original_load()

    def restore():
        attempted.set()
        return manager.load_last_active()

    monkeypatch.setattr(manager.app_local_store, "load", load)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(RuntimeError, match="effect failed"):
            with manager.selection_window():
                future = pool.submit(restore)
                assert attempted.wait(10)
                assert not loaded.wait(0.25)
                assert manager.context.active_vault_path == str(voice_vault)
                raise RuntimeError("effect failed")
        future.result(timeout=10)
    assert loaded.is_set()


def test_concurrent_first_getters_share_one_manager(
    voice_vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.vault.manager as manager_module

    manager = vault_resolution.get_vault_manager()
    first_construction = Event()
    release_construction = Event()
    second_getter = Event()
    duplicate_construction = Event()

    def construct():
        if first_construction.is_set():
            duplicate_construction.set()
        first_construction.set()
        assert release_construction.wait(10)
        return manager

    def get_second():
        second_getter.set()
        return manager_module.get_vault_manager()

    monkeypatch.setattr(manager_module, "_GLOBAL_MANAGER", None)
    monkeypatch.setattr(manager_module, "VaultManager", construct)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(manager_module.get_vault_manager)
        try:
            assert first_construction.wait(10)
            second = pool.submit(get_second)
            assert second_getter.wait(10)
            assert not duplicate_construction.wait(0.25)
        finally:
            release_construction.set()
        assert first.result(timeout=10) is manager
        assert second.result(timeout=10) is manager
