"""Acquisition-time governed interest overlay wiring (#5747).

These tests drive the production acquisition seams (``acquire_youtube``,
``acquire_metadata_only`` and ``assemble_candidate`` -> ``write_candidate_note``)
against vaults whose profile state comes from the real ProfileAgent propose ->
checked confirmation -> governed write -> receipt path.  Source egress and LLM
extractors are stubbed exactly as ``test_acquire.py`` does; the overlay producer
itself must need no stub because it is local and deterministic.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import pytest
import yaml

from app import objects as object_store_module
from app.components.llm import constrained as constrained_module
from app.components.llm import router as router_module
from app.knowledge.profile_consumer_projection import rebuild_profile_projection
from app.knowledge_acquisition import candidate_writeback
from app.knowledge_acquisition import extraction_registry
from app.knowledge_acquisition import interest_overlay as overlay_module
from app.knowledge_acquisition import youtube_plugin as plugin
from app.knowledge_acquisition.acquire import acquire_metadata_only, acquire_youtube
from app.knowledge_acquisition.candidate_writeback import (
    assemble_candidate,
    render_candidate_note,
    write_candidate_note,
)
from app.knowledge_acquisition.extraction_registry import clear_registry
from app.knowledge_acquisition.extractors import claims_extractor, summary_extractor, synthesis_extractor
from app.knowledge_acquisition.interest_overlay import NO_PROFILE_LINES, propose_local_connections
from app.knowledge_acquisition.normalize import normalize
from app.knowledge_acquisition.replay import run_replay
from app.knowledge_acquisition.note_renderer import EVIDENCE_HEADING, PROPOSALS_HEADING
from app.stores import reset_store_backends
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard
from tests.knowledge_acquisition.test_interest_overlay import (
    _OTHER_SCOPE,
    _PROFILE_LINE,
    _SCOPE,
    _approved_vault,
    _new_profile_note,
    _propose,
)

pytestmark = pytest.mark.not_pg

VIDEO_ID = "abcdefghijk"
VIDEO_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"
_MATCHING_CUE = "Local-first knowledge tools keep every file on your machine."
_CAPTION_BODY = (
    "WEBVTT\n\n"
    "00:00:00.000 --> 00:00:02.000\n"
    "Hello world\n\n"
    "00:00:02.000 --> 00:00:06.000\n"
    f"{_MATCHING_CUE}\n"
)
_RAW_RECORD = {
    "source_kind": "youtube_url",
    "item_ref": VIDEO_ID,
    "url": VIDEO_URL,
    "content_identity": "sha256:overlay-wiring-fixture-identity",
    "acquisition_method": "captions_manual",
    "caption_language": "en",
    "caption_body": _CAPTION_BODY,
    "metadata": {"title": "Overlay Wiring Video", "channel": "Test Channel", "chapters": []},
    "provenance": {"source_kind": "youtube_url", "url": VIDEO_URL, "creator": "Test Channel"},
}


class _FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]]):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _FakeOutboxConn:
    def __init__(self) -> None:
        self.rows: dict[str, Any] = {}

    def execute(self, sql: str, params: tuple = ()) -> _FakeCursor:
        text = " ".join(sql.lower().split())
        if text.startswith("insert into outbox (id,"):
            row_id = params[0]
            if row_id in self.rows:
                return _FakeCursor([])
            self.rows[row_id] = params
            return _FakeCursor([(row_id,)])
        raise AssertionError(f"unexpected SQL shape reached the outbox: {text!r}")


def _stub_completion(payload: dict[str, Any]):
    def complete(*, system: str, user: str, trace_id=None, max_tokens=None) -> str:
        return json.dumps(payload)

    return complete


@pytest.fixture(autouse=True)
def _acquisition_runtime(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/app_test")
    reset_store_backends()
    object_store_module._MEMORY_STORE.clear()
    clear_registry()
    summary_extractor.register(complete=_stub_completion({"summary": "A test summary.", "confidence": 0.75}))
    synthesis_extractor.register(
        complete=_stub_completion(
            {
                "synthesis_sentences": [
                    {
                        "text": "The transcript describes local-first tools.",
                        "anchors": [{"segment_index": 1, "start": 2.0, "end": 6.0}],
                    }
                ],
                "model_confidence": 0.8,
            }
        )
    )
    claims_extractor.register(
        complete=_stub_completion(
            {
                "claims": [
                    {
                        "source_wording": "Hello world",
                        "system_paraphrase": "The source opens with a greeting.",
                        "anchors": [{"segment_index": 0, "start": 0.0, "end": 2.0}],
                    }
                ]
            }
        )
    )
    yield
    clear_registry()
    summary_extractor.register()
    synthesis_extractor.register()
    claims_extractor.register()
    reset_store_backends()
    object_store_module._MEMORY_STORE.clear()


def _context(root: Path, scope: str | None = _SCOPE) -> VaultContext:
    root.mkdir(parents=True, exist_ok=True)
    return VaultContext(
        status="selected",
        active_vault_id="overlay-wiring",
        active_vault_name="Overlay Wiring",
        active_vault_path=str(root),
        active_scope_id=scope,
    )


def _guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _stub_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    info = {
        "id": VIDEO_ID,
        "title": "Overlay Wiring Video",
        "channel": "Test Channel",
        "channel_id": "UC123",
        "upload_date": "20260101",
        "duration": 600,
        "description": "desc",
        "chapters": [],
        "tags": [],
        "language": "en",
        "thumbnail": "https://example.com/thumb.jpg",
        "subtitles": {"en": [{"ext": "vtt", "url": "https://example.com/manual.vtt"}]},
        "automatic_captions": {},
    }
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: info)
    monkeypatch.setattr(plugin, "yt_dlp_extract_metadata", lambda url: info)
    monkeypatch.setattr(plugin, "fetch_caption_body", lambda url: _CAPTION_BODY)


def _candidate_note(root: Path) -> str:
    notes = [path for path in (root / "Sources").rglob("*.md") if path.name != "transcript.md"]
    assert len(notes) == 1, notes
    return notes[0].read_text(encoding="utf-8")


def _frontmatter(note: str) -> dict[str, Any]:
    return yaml.safe_load(note.split("---\n", 2)[1])


def _overlay_band(note: str) -> str:
    proposals = note.split(PROPOSALS_HEADING, 1)[1].split(EVIDENCE_HEADING, 1)[0]
    assert "### Interest overlay" in proposals
    return proposals.split("### Interest overlay", 1)[1].split("\n### ", 1)[0]


def _spy_render(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    real = overlay_module.render_interest_overlay

    def spy(**kwargs: Any):
        calls.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(overlay_module, "render_interest_overlay", spy)
    return calls


def test_acquisition_renders_overlay_connections_from_admitted_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _note_path = _approved_vault(tmp_path / "vault")
    projection = rebuild_profile_projection(root, active_scope_id=_SCOPE)
    assert projection.available
    _stub_fetch(monkeypatch)
    calls = _spy_render(monkeypatch)

    receipt = acquire_youtube(VIDEO_URL, vault_context=_context(root), write_guard=_guard(), conn=_FakeOutboxConn())

    assert receipt.ok is True
    # The production acquisition path invoked the governed renderer with the vault-context scope.
    assert len(calls) == 1
    assert calls[0]["active_scope_id"] == _SCOPE
    assert Path(calls[0]["vault_root"]).resolve() == root.resolve()
    note = _candidate_note(root)
    band = _overlay_band(note)
    # One four-part connection: anchored source evidence, inference, owner link, suggested use.
    assert f"- **Source says** (00:02): “{_MATCHING_CUE}”" in band.replace("> ", "")
    assert "**System inference:** This passage shares" in band
    assert "**Owner link:** “Prefer local-first knowledge tools" in band
    assert f"approved profile version {projection.version_id}" in band
    assert "**Suggested use:** Review this passage" in band
    assert "Follow research on retrieval evaluation" not in band  # unsupported entry is not linked
    overlay_meta = _frontmatter(note)["interest_overlay"]
    assert overlay_meta == {
        "status": "connections",
        "reason": "approved_same_scope_profile",
        "profile_scope_id": _SCOPE,
        "profile_version_id": projection.version_id,
        "profile_receipt_id": projection.receipt_id,
        "dropped_connections": [],
    }
    # Spine evidence remains alongside the overlay.
    assert "### Evidence-anchored synthesis" in note
    assert "### Evidence-anchored claims" in note
    assert "**Materialization status:** complete" in note

    # The replay orchestrator uses the same assembly seam: replaying the raw record into another
    # approved vault renders that vault's overlay without any source egress.
    replay_root, _ = _approved_vault(tmp_path / "replay-vault")
    replay_projection = rebuild_profile_projection(replay_root, active_scope_id=_SCOPE)
    monkeypatch.setattr(plugin, "fetch_caption_body", lambda url: pytest.fail("replay egress"))
    replay = run_replay(
        receipt.raw_record_id, vault_context=_context(replay_root), conn=_FakeOutboxConn(), assert_no_source_egress=True
    )
    assert replay.source_egress == 0
    replay_note = _candidate_note(replay_root)
    assert f"approved profile version {replay_projection.version_id}" in _overlay_band(replay_note)
    assert _frontmatter(replay_note)["interest_overlay"]["profile_receipt_id"] == replay_projection.receipt_id
    assert calls[-1]["active_scope_id"] == _SCOPE


def test_connection_producer_is_deterministic_local_and_no_egress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _note_path = _approved_vault(tmp_path / "vault")
    normalized = normalize(dict(_RAW_RECORD))

    def forbidden(*_args: Any, **_kwargs: Any):
        raise AssertionError("overlay production must not reach the network, a model, or LLM routing")

    for target, name in (
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
        (socket, "create_connection"),
        (socket, "getaddrinfo"),
        (router_module.LLMRouter, "__init__"),
        (constrained_module, "constrained_completion"),
        (extraction_registry, "run_extractor"),
        (candidate_writeback, "run_extractor"),
        (plugin, "fetch"),
        (plugin, "fetch_caption_body"),
    ):
        monkeypatch.setattr(target, name, forbidden)

    # Profile state may be read only through the named governed projection reader.
    reader_depth = {"inside": 0, "calls": 0}
    real_reader = overlay_module.read_governed_profile_for_overlay
    real_admit = overlay_module.admit_profile_for_interest_overlay

    def reader(vault_root, *, active_scope_id):
        reader_depth["inside"] += 1
        reader_depth["calls"] += 1
        try:
            return real_reader(vault_root, active_scope_id=active_scope_id)
        finally:
            reader_depth["inside"] -= 1

    def guarded_admit(vault_root, *, active_scope_id):
        assert reader_depth["inside"] == 1, "profile admission bypassed read_governed_profile_for_overlay"
        return real_admit(vault_root, active_scope_id=active_scope_id)

    monkeypatch.setattr(overlay_module, "read_governed_profile_for_overlay", reader)
    monkeypatch.setattr(overlay_module, "admit_profile_for_interest_overlay", guarded_admit)

    first = propose_local_connections(vault_root=root, active_scope_id=_SCOPE, normalized=normalized.as_dict())
    second = propose_local_connections(vault_root=root, active_scope_id=_SCOPE, normalized=normalized.as_dict())
    assert first == second
    assert [c["owner_link"] for c in first] == [_PROFILE_LINE]
    assert first[0]["source_says"] == _MATCHING_CUE
    assert first[0]["anchors"] == [{"segment_index": 1, "start": 2.0, "end": 6.0}]
    assert set(first[0]) == {"source_says", "anchors", "system_inference", "owner_link", "suggested_use"}

    # The production assembly seam is equally local: same inputs, same overlay, same section.
    candidates = [
        assemble_candidate(
            dict(_RAW_RECORD),
            normalized=normalized,
            extraction_results=(),
            vault_context=_context(root),
        )
        for _ in range(2)
    ]
    overlays = [candidate.interest_overlay for candidate in candidates]
    assert overlays[0] is not None and overlays[0] == overlays[1]
    assert overlays[0].status == "connections"
    assert overlays[0].section() == overlays[1].section()
    assert reader_depth["calls"] >= 6  # producer + renderer each read once per production
    assert reader_depth["inside"] == 0


def test_acquisition_overlay_no_profile_metadata_only_and_failure_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    normalized = normalize(dict(_RAW_RECORD))
    scoped_root, _ = _approved_vault(tmp_path / "scoped")
    pending_root, _pending_note, pending_uuid = _new_profile_note(tmp_path / "pending")
    _propose(pending_root, pending_uuid, f"<!--mimer:profile-scope scope_id={_SCOPE}-->\n\n- {_PROFILE_LINE}")
    missing_root = tmp_path / "missing"
    unselected = VaultContext(status="none", active_scope_id=_SCOPE)
    cases = {
        "missing": (_context(missing_root), "authority_unavailable"),
        "pending": (_context(pending_root), "profile_not_receipt_bound"),
        "out_of_scope": (_context(scoped_root, _OTHER_SCOPE), "profile_scope_mismatch"),
        "unresolvable_scope": (_context(scoped_root, None), "missing_or_invalid_active_scope"),
        "invalid_scope": (_context(scoped_root, "not a scope!"), "missing_or_invalid_active_scope"),
        "unselected_vault": (unselected, "missing_or_invalid_active_scope"),
    }
    for name, (context, reason) in cases.items():
        candidate = assemble_candidate(
            dict(_RAW_RECORD), normalized=normalized, extraction_results=(), vault_context=context
        )
        assert candidate.interest_overlay is not None, name
        assert candidate.interest_overlay.status == "no-profile", name
        assert candidate.interest_overlay.reason == reason, name
        note = render_candidate_note(candidate)
        band = _overlay_band(note)
        lines = [line for line in band.splitlines() if line.strip() and line.strip() != ">"]
        assert lines == [f"> {NO_PROFILE_LINES['en']}"], name
        assert note.count(NO_PROFILE_LINES["en"]) == 1, name
        assert _PROFILE_LINE not in note, name
        assert _frontmatter(note)["interest_overlay"]["status"] == "no-profile", name
        assert EVIDENCE_HEADING in note and "**Transcript:** available" in note, name
    # The written note carries the same single line through the governed write seam.
    written = write_candidate_note(
        assemble_candidate(
            dict(_RAW_RECORD), normalized=normalized, extraction_results=(), vault_context=_context(missing_root)
        ),
        vault_context=_context(missing_root),
        write_guard=_guard(),
    )
    assert written.status == "written"
    assert (missing_root / str(written.artifact_path)).read_text(encoding="utf-8").count(NO_PROFILE_LINES["en"]) == 1

    # Metadata-only acquisition renders no overlay section even with an admitted profile.
    _stub_fetch(monkeypatch)
    calls = _spy_render(monkeypatch)
    meta_root, _ = _approved_vault(tmp_path / "metadata")
    receipt = acquire_metadata_only(VIDEO_URL, vault_context=_context(meta_root), conn=_FakeOutboxConn())
    assert receipt.ok is True
    meta_note = _candidate_note(meta_root)
    assert "Interest overlay" not in meta_note
    assert "interest_overlay" not in _frontmatter(meta_note)
    assert NO_PROFILE_LINES["en"] not in meta_note
    assert calls == []

    # Overlay failure degrades the overlay only; the candidate and its evidence sections survive.
    def exploding(**_kwargs: Any):
        raise RuntimeError("overlay producer exploded")

    raising_root, _ = _approved_vault(tmp_path / "raising")
    with monkeypatch.context() as scoped_patch:
        scoped_patch.setattr(candidate_writeback, "produce_interest_overlay", exploding)
        object_store_module._MEMORY_STORE.clear()
        receipt = acquire_youtube(
            VIDEO_URL, vault_context=_context(raising_root), write_guard=_guard(), conn=_FakeOutboxConn()
        )
    assert receipt.ok is True
    note = _candidate_note(raising_root)
    assert "### Interest overlay" not in note
    assert "### Evidence-anchored synthesis" in note
    assert "### Evidence-anchored claims" in note
    meta = _frontmatter(note)
    assert meta["degraded"] is True
    assert meta["unavailable_note_modules"] == ["interest_overlay"]
    assert "interest overlay failed" in note

    # An admitted connection the shared wrapper would refuse (banned owner-authority phrasing in
    # an approved entry) is dropped and reported on its own; healthy connections still render.
    banned_line = "Local-first knowledge tools matter because you decided they keep the machine yours."
    banned_root, _ = _approved_vault(
        tmp_path / "banned",
        f"<!--mimer:profile-scope scope_id={_SCOPE}-->\n\n## Interests\n\n- {banned_line}\n- {_PROFILE_LINE}",
    )
    object_store_module._MEMORY_STORE.clear()
    receipt = acquire_youtube(
        VIDEO_URL, vault_context=_context(banned_root), write_guard=_guard(), conn=_FakeOutboxConn()
    )
    assert receipt.ok is True
    note = _candidate_note(banned_root)
    band = _overlay_band(note)
    assert "you decided" not in band
    assert "**Owner link:** “Prefer local-first knowledge tools" in band
    meta = _frontmatter(note)
    assert meta["interest_overlay"]["status"] == "connections"
    assert meta["interest_overlay"]["dropped_connections"] == ["connection_unsafe_for_proposal_band"]
    assert "degraded" not in meta
    assert "### Evidence-anchored synthesis" in note


# --- #5749: production active-scope binding ---------------------------------------------------
#
# The production entry points are the ``acquire-youtube``/``acquire-replay`` CLI commands
# (explicit operator ``--scope``) and the acquisition-request drain (``drain_one``), which takes
# the scope from the request's policy snapshot.  The CLI runs get only an injected runtime outbox
# connection and write guard (callers' own values win, so the drain passes its own); each entry
# point's VaultContext construction and the real pipeline run unchanged.


def _cli_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.knowledge_acquisition import acquire as acquire_module
    from app.knowledge_acquisition import replay as replay_module

    real_acquire = acquire_module.acquire_youtube
    real_replay = replay_module.run_replay
    monkeypatch.setattr(
        acquire_module,
        "acquire_youtube",
        lambda url, **kwargs: real_acquire(url, **{"conn": _FakeOutboxConn(), "write_guard": _guard(), **kwargs}),
    )
    monkeypatch.setattr(
        replay_module,
        "run_replay",
        lambda raw_id, **kwargs: real_replay(raw_id, **{"conn": _FakeOutboxConn(), "write_guard": _guard(), **kwargs}),
    )


def _invoke(args: list[str]) -> Any:
    from app.cli import cli
    from tests._click_compat import cli_runner

    result = cli_runner(mix_stderr=False).invoke(cli, args)
    assert result.exit_code == 0, (result.output, result.exception)
    return result


def _drain(root: Path, policy_snapshot: dict[str, Any], *, context: VaultContext | None = None) -> Any:
    from app.knowledge_acquisition.acquisition_requests import (
        AcquisitionRequests,
        DiscoveryTrigger,
        drain_one,
        reset_memory_acquisition_requests,
    )

    reset_memory_acquisition_requests()
    object_store_module._MEMORY_STORE.clear()
    conn = _FakeOutboxConn()
    queue = AcquisitionRequests.for_runtime()
    queue.enqueue(
        source_kind="youtube_url",
        item_ref=VIDEO_ID,
        source_ref=VIDEO_URL,
        trigger=DiscoveryTrigger(
            binding_id="00000000-0000-0000-0000-000000005749",
            collection_kind="inbox_playlist",
            collection_ref="PL5749",
            trigger="poll",
            playlist_item_id="item-5749",
        ),
        policy_snapshot=policy_snapshot,
        conn=conn,
    )
    claimed = queue.claim_batch(1, conn=conn)
    result = drain_one(
        claimed[0],
        vault_context=context or _context(root, None),
        queue=queue,
        write_guard=_guard(),
        conn=conn,
    )
    assert result.status == "completed", result
    return result


def _assert_single_no_profile(root: Path) -> None:
    note = _candidate_note(root)
    lines = [line for line in _overlay_band(note).splitlines() if line.strip() and line.strip() != ">"]
    assert lines == [f"> {NO_PROFILE_LINES['en']}"]
    assert note.count(NO_PROFILE_LINES["en"]) == 1
    assert _PROFILE_LINE not in note
    assert _frontmatter(note)["interest_overlay"]["reason"] == "missing_or_invalid_active_scope"


def test_production_entry_point_binds_active_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_fetch(monkeypatch)
    _cli_runtime(monkeypatch)
    calls = _spy_render(monkeypatch)

    # acquire-youtube --scope: the operator-stated scope reaches the governed renderer.
    root, _ = _approved_vault(tmp_path / "cli")
    projection = rebuild_profile_projection(root, active_scope_id=_SCOPE)
    result = _invoke(["acquire-youtube", VIDEO_URL, "--vault-root", str(root), "--scope", _SCOPE, "--json"])
    assert [call["active_scope_id"] for call in calls] == [_SCOPE]
    note = _candidate_note(root)
    assert f"approved profile version {projection.version_id}" in _overlay_band(note)
    assert _frontmatter(note)["interest_overlay"]["status"] == "connections"
    raw_record_id = json.loads(result.output.strip().splitlines()[-1])["raw_record_id"]

    # acquire-replay --scope binds the same way, with zero source egress.
    replay_root, _ = _approved_vault(tmp_path / "cli-replay")
    with monkeypatch.context() as no_egress:
        no_egress.setattr(plugin, "fetch_caption_body", lambda url: pytest.fail("replay egress"))
        _invoke(["acquire-replay", raw_record_id, "--vault-root", str(replay_root), "--scope", _SCOPE])
    assert calls[-1]["active_scope_id"] == _SCOPE
    assert _frontmatter(_candidate_note(replay_root))["interest_overlay"]["status"] == "connections"

    # Drained acquisition requests take the scope from the request's policy snapshot, even when
    # the drain caller's context carries none.
    drain_root, _ = _approved_vault(tmp_path / "drain")
    _drain(drain_root, {"policy_version": 1, "mode": "acquire_transcript", "active_scope_id": _SCOPE})
    assert calls[-1]["active_scope_id"] == _SCOPE
    assert Path(calls[-1]["vault_root"]).resolve() == drain_root.resolve()
    assert _frontmatter(_candidate_note(drain_root))["interest_overlay"]["status"] == "connections"


def test_production_entry_point_without_scope_renders_no_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_fetch(monkeypatch)
    _cli_runtime(monkeypatch)
    calls = _spy_render(monkeypatch)

    # No --scope: an approved profile exists, but no scope is inferred from the vault.
    root, _ = _approved_vault(tmp_path / "unscoped")
    _invoke(["acquire-youtube", VIDEO_URL, "--vault-root", str(root)])
    assert calls[-1]["active_scope_id"] is None
    _assert_single_no_profile(root)

    # An invalid --scope degrades to the same single no-profile line.
    object_store_module._MEMORY_STORE.clear()
    invalid_root, _ = _approved_vault(tmp_path / "invalid")
    _invoke(["acquire-youtube", VIDEO_URL, "--vault-root", str(invalid_root), "--scope", "not a scope!"])
    assert calls[-1]["active_scope_id"] is None
    _assert_single_no_profile(invalid_root)

    # A drained request without a snapshot scope renders no-profile; the snapshot is the drain's
    # only source, so a scope already present on the caller's context is not carried over.
    drain_root, _ = _approved_vault(tmp_path / "drain")
    _drain(drain_root, {"policy_version": 1, "mode": "acquire_transcript"}, context=_context(drain_root, _SCOPE))
    assert calls[-1]["active_scope_id"] is None
    _assert_single_no_profile(drain_root)

    # An invalid snapshot scope is never coerced into a binding.
    drain_invalid_root, _ = _approved_vault(tmp_path / "drain-invalid")
    _drain(drain_invalid_root, {"policy_version": 1, "mode": "acquire_transcript", "active_scope_id": 42})
    assert calls[-1]["active_scope_id"] is None
    _assert_single_no_profile(drain_invalid_root)
