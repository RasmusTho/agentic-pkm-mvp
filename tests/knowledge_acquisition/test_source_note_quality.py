"""YSNV2-12 (#4119): source-note quality evaluation and the v2 end-to-end invariant matrix.

Every note evaluated here is produced by the REAL acquisition-time pipeline
(``acquire_youtube`` -> normalize -> extractors -> moments/frames -> overlay -> candidate write,
and ``run_replay``).  The only substitutions are the external seams: source egress is stubbed
at the YouTube plugin, LLM extractors return fixed JSON, media capture is an injected
``SourceMediaCapture`` fake, and the governed profile comes from the real ProfileAgent
propose -> checked confirmation -> governed write -> receipt path.

GOLD-SET PROVENANCE: every gold set in this file is a clearly labeled SYNTHETIC fixture
(``provenance.kind: synthetic_fixture``).  None of them is, or stands in for, the owner's
must-capture annotations; those are a versioned data input the owner supplies later under
operator receipt ``ysnv2_gold_set_annotation_scope.v1`` (#4107).
"""

from __future__ import annotations

import json
import socket
import urllib.request
from pathlib import Path
from dataclasses import replace
from typing import Any

import pytest
import yaml

from app import objects as object_store_module
from app.components.llm import constrained as constrained_module
from app.components.llm import router as router_module
from app.knowledge.profile_consumer_projection import rebuild_profile_projection
from app.knowledge_acquisition import candidate_writeback, extraction_registry
from app.knowledge_acquisition import source_frames as frames_module
from app.knowledge_acquisition import youtube_plugin as plugin
from app.knowledge_acquisition.acquire import acquire_youtube
from app.knowledge_acquisition.extraction_registry import clear_registry
from app.knowledge_acquisition.extractors import claims_extractor, summary_extractor, synthesis_extractor
from app.knowledge_acquisition.interest_overlay import NO_PROFILE_LINES
from app.knowledge_acquisition.raw_record import get_raw_record
from app.knowledge_acquisition.replay import run_replay
from app.knowledge_acquisition.source_frames import CapturedFrame, MediaUnavailableError
from app.knowledge_acquisition.source_note_quality import (
    ANNOTATION_SCOPE_RECEIPT,
    CRITERION_ANCHOR_VALIDITY,
    CRITERION_CLAIM_ENTAILMENT,
    CRITERION_EVIDENCE_LINEAGE,
    CRITERION_MUST_CAPTURE_RECALL,
    GOLD_SET_SCHEMA,
    OPERATOR_SCORED_DIMENSIONS,
    OWNER_GOLD_SET_PATH,
    SYNTHETIC_FIXTURE,
    GoldSetError,
    evaluate_source_note,
    evaluate_subject,
    load_owner_gold_set,
    load_rendered_subject,
    parse_gold_set,
)
from app.objects import ObjectStore
from app.stores import reset_store_backends
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard
from tests.knowledge_acquisition.test_interest_overlay import _SCOPE, _approved_vault

pytestmark = pytest.mark.not_pg

REPO_ROOT = Path(__file__).resolve().parents[2]
VIDEO_A = "abcdefghijk"
VIDEO_B = "bcdefghijkl"
_MATCHING_CUE = "Local-first knowledge tools keep every file on your machine."
_UNSUPPORTED_WORDING = "The speaker recommends moving every file to cloud storage."
_RASTER = bytes((x * 7 + y * 3) % 256 for y in range(32) for x in range(32))


def _captions(third_cue: str) -> str:
    return (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:02.000\nHello world\n\n"
        f"00:00:02.000 --> 00:00:06.000\n{_MATCHING_CUE}\n\n"
        f"00:00:06.000 --> 00:00:10.000\n{third_cue}\n"
    )


_SYNTHESIS = {
    "synthesis_sentences": [
        {"text": "The transcript describes local-first tools.", "anchors": [{"segment_index": 1, "start": 2.0, "end": 6.0}]}
    ],
    "model_confidence": 0.8,
}
_CLAIMS = {
    "claims": [
        {
            "source_wording": "Hello world",
            "system_paraphrase": "The source opens with a greeting.",
            "anchors": [{"segment_index": 0, "start": 0.0, "end": 2.0}],
        },
        {
            "source_wording": _MATCHING_CUE,
            "system_paraphrase": "The source says local-first tools keep files local.",
            "anchors": [{"segment_index": 1, "start": 2.0, "end": 6.0}],
        },
    ]
}


class FakeMediaCapture:
    """Injected media seam; records each bounded download and never touches the network."""

    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.fail_with = fail_with
        self.downloads: list[str] = []

    def download_temporary_media(self, *, item_ref: str, dest_dir: Path, max_bytes: int, max_duration_seconds: int) -> Path:
        self.downloads.append(item_ref)
        if self.fail_with is not None:
            raise self.fail_with
        media = dest_dir / "source-media.mp4"
        media.write_bytes(b"FAKE-MP4" * 64)
        return media

    def extract_frame(self, *, media_path: Path, timestamp_seconds: int, work_dir: Path) -> CapturedFrame:
        return CapturedFrame(image_bytes=b"\xff\xd8\xff\xe0" + f"still-{timestamp_seconds}".encode() + b"\xff\xd9", grayscale_32=_RASTER)


class _Cursor:
    def __init__(self, rows: list[tuple[Any, ...]]):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _Outbox:
    def __init__(self) -> None:
        self.rows: dict[str, Any] = {}

    def execute(self, sql: str, params: tuple = ()) -> _Cursor:
        text = " ".join(sql.lower().split())
        if text.startswith("insert into outbox (id,"):
            if params[0] in self.rows:
                return _Cursor([])
            self.rows[params[0]] = params
            return _Cursor([(params[0],)])
        raise AssertionError(f"unexpected SQL reached the outbox: {text!r}")


def _register_extractors(*, claims: dict[str, Any] = _CLAIMS) -> None:
    def stub(payload: dict[str, Any]):
        return lambda *, system, user, trace_id=None, max_tokens=None: json.dumps(payload)

    clear_registry()
    summary_extractor.register(complete=stub({"summary": "A test summary.", "confidence": 0.75}))
    synthesis_extractor.register(complete=stub(_SYNTHESIS))
    claims_extractor.register(complete=stub(claims))


@pytest.fixture(autouse=True)
def _runtime(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/app_test")
    reset_store_backends()
    object_store_module._MEMORY_STORE.clear()
    _register_extractors()

    def forbidden(*_args: Any, **_kwargs: Any):
        raise AssertionError("quality tests must not reach a real network or media boundary")

    # Real sockets and the production media boundaries are forbidden for the whole module.
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(frames_module, "_youtube_dl", forbidden)
    monkeypatch.setattr(frames_module, "_run_ffmpeg", forbidden)
    yield
    clear_registry()
    summary_extractor.register()
    synthesis_extractor.register()
    claims_extractor.register()
    reset_store_backends()
    object_store_module._MEMORY_STORE.clear()


def _stub_source(monkeypatch: pytest.MonkeyPatch, video_id: str, captions: str) -> None:
    info = {
        "id": video_id,
        "title": f"Quality Fixture {video_id}",
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
    monkeypatch.setattr(plugin, "fetch_caption_body", lambda url: captions)


def _context(root: Path, scope: str | None = None) -> VaultContext:
    root.mkdir(parents=True, exist_ok=True)
    return VaultContext(
        status="selected",
        active_vault_id=f"quality-{root.name}",
        active_vault_name="Quality",
        active_vault_path=str(root),
        active_scope_id=scope,
    )


def _guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _acquire(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    video_id: str = VIDEO_A,
    third_cue: str = "A third cue about calibration.",
    scope: str | None = None,
    capture: FakeMediaCapture | None = None,
) -> tuple[Any, VaultContext, Path, FakeMediaCapture]:
    _stub_source(monkeypatch, video_id, _captions(third_cue))
    capture = capture or FakeMediaCapture()
    context = _context(root, scope)
    receipt = acquire_youtube(
        f"https://www.youtube.com/watch?v={video_id}",
        vault_context=context,
        write_guard=_guard(),
        conn=_Outbox(),
        media_capture=capture,
    )
    assert receipt.ok is True, receipt
    stage = next(stage for stage in receipt.stages if stage.stage == "candidate")
    return receipt, context, root / str(stage.artifact_path), capture


def _synthetic_gold_set(
    *, item_ref: str, content_identity: str, threshold: float = 0.6, version: int = 1
) -> dict[str, Any]:
    """A SYNTHETIC gold set for harness tests only; never owner must-capture annotations."""

    return {
        "schema": GOLD_SET_SCHEMA,
        "gold_set_id": "ysnv2-harness-synthetic",
        "version": version,
        "provenance": {"kind": SYNTHETIC_FIXTURE, "note": "synthetic harness fixture; not owner annotations"},
        "must_capture_recall_threshold": threshold,
        "videos": [
            {
                "item_ref": item_ref,
                "content_identity": content_identity,
                "must_capture": [
                    {"point_id": "synthetic-greeting", "description": "synthetic: opening", "start_seconds": 0, "end_seconds": 2},
                    {"point_id": "synthetic-local-first", "description": "synthetic: local-first", "start_seconds": 3, "end_seconds": 5},
                    {"point_id": "synthetic-late", "description": "synthetic: uncovered tail", "start_seconds": 30, "end_seconds": 40},
                ],
            }
        ],
    }


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _store_snapshot() -> dict[str, Any]:
    return {key: json.dumps(obj.payload, sort_keys=True, default=str) for key, obj in object_store_module._MEMORY_STORE.items()}


def _frontmatter(note: str) -> dict[str, Any]:
    return yaml.safe_load(note.split("---\n", 2)[1])


def _forbid_egress(monkeypatch: pytest.MonkeyPatch, *, evaluation: bool) -> None:
    """Forbid source egress; for evaluation also forbid model calls and every state write.

    Replay legitimately re-runs the (stubbed) extractors and writes derived artifacts plus a
    proposal companion, so only its source/media egress is forbidden.
    """

    def forbidden(*_args: Any, **_kwargs: Any):
        raise AssertionError("evaluation/replay must not egress, call a model, or mutate state")

    targets: list[tuple[Any, str]] = [
        (socket, "getaddrinfo"),
        (socket.socket, "connect_ex"),
        (plugin, "fetch"),
        (plugin, "fetch_caption_body"),
        (plugin, "yt_dlp_extract_info"),
        (plugin, "yt_dlp_extract_metadata"),
    ]
    if evaluation:
        targets += [
            (router_module.LLMRouter, "__init__"),
            (constrained_module, "constrained_completion"),
            (ObjectStore, "save_object"),
            (ObjectStore, "create_object_once"),
            (extraction_registry, "run_extractor"),
            (candidate_writeback, "run_extractor"),
            (candidate_writeback, "write_candidate_note"),
            (Path, "write_text"),
            (Path, "write_bytes"),
            (Path, "mkdir"),
            (Path, "unlink"),
        ]
    for target, name in targets:
        monkeypatch.setattr(target, name, forbidden)


# --- AC1 ----------------------------------------------------------------------------------------


def test_quality_gate_rejects_unanchored_or_non_entailing_claims(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Positive control: a note whose rendered evidence is anchored and entailed passes.
    _receipt, _ctx, note_path, _capture = _acquire(tmp_path / "clean", monkeypatch)
    clean_note = note_path.read_text(encoding="utf-8")
    clean = evaluate_source_note(clean_note)
    assert clean.passed is True, clean.failures
    assert clean.failed_criteria == ()
    assert clean.metrics["anchor_validity"] == 1.0 and clean.metrics["claim_entailment"] == 1.0
    assert clean.metrics["rendered_items_by_kind"] == {"synthesis_sentence": 1, "claim": 2, "moment": 1}

    # Non-entailing: the anchor resolves, so the renderer's own filter keeps the claim, but its
    # source wording is not what the cited segment says.  The harness names claim_entailment.
    object_store_module._MEMORY_STORE.clear()
    _register_extractors(
        claims={
            "claims": [
                _CLAIMS["claims"][0],
                {
                    "source_wording": _UNSUPPORTED_WORDING,
                    "system_paraphrase": "The source endorses cloud storage.",
                    "anchors": [{"segment_index": 1, "start": 2.0, "end": 6.0}],
                },
            ]
        }
    )
    _r, _c, bad_path, _cap = _acquire(tmp_path / "non-entailing", monkeypatch)
    bad_note = bad_path.read_text(encoding="utf-8")
    assert _UNSUPPORTED_WORDING in bad_note  # rendered: the pipeline gate alone does not catch it
    report = evaluate_source_note(bad_note)
    assert report.passed is False
    assert report.failed_criteria == (CRITERION_CLAIM_ENTAILMENT,)
    (failure,) = report.failures[CRITERION_CLAIM_ENTAILMENT]
    assert failure.startswith("claim[") and _UNSUPPORTED_WORDING[:40] in failure
    assert report.metrics["claim_entailment"] == 0.5
    assert report.as_dict()["failed_criteria"] == [CRITERION_CLAIM_ENTAILMENT]

    # Unanchored: a rendered claim without anchors and a synthesis sentence absent from the
    # durable synthesis artifact (a renderer regression) both fail anchor_validity by name.
    tampered = bad_note.replace(
        "> **Source-bound claims (non-authoritative):**",
        "> **Source-bound claims (non-authoritative):**\n"
        "> - **Source wording:** Hello world\n"
        ">   **System paraphrase:** An uncited restatement.",
        1,
    ).replace(
        "> - The transcript describes local-first tools.",
        "> - The transcript describes local-first tools.\n> - An uncited synthesis sentence.",
        1,
    )
    report = evaluate_source_note(tampered)
    assert report.passed is False
    assert set(report.failed_criteria) == {CRITERION_ANCHOR_VALIDITY, CRITERION_CLAIM_ENTAILMENT}
    unanchored = report.failures[CRITERION_ANCHOR_VALIDITY]
    assert any(item.startswith("synthesis_sentence[") and "uncited synthesis" in item for item in unanchored)
    assert any(item.startswith("claim[") and "Hello world" in item for item in unanchored)

    # A heading-like string inside rendered source text cannot end the evaluated band early, and
    # an unrecognized evidence bullet fails rather than silently dropping out of the evaluation.
    heading_text = clean_note.replace(
        "> - **Source wording:** Hello world\n",
        "> - **Source wording:** Hello world ## Evidence and lineage\n",
        1,
    ).replace(
        "> **Timestamped moments (non-authoritative; selected from transcript evidence):**",
        "> **Timestamped moments (non-authoritative; selected from transcript evidence):**\n> - a stray bullet",
        1,
    )
    report = evaluate_source_note(heading_text)
    assert report.metrics["rendered_items_by_kind"]["moment"] == 1  # moments still parsed
    assert any("unparsed rendered item" in item for item in report.failures[CRITERION_ANCHOR_VALIDITY])
    # A non-entailing claim never credits must-capture recall, even when its anchor overlaps.
    subject = load_rendered_subject(bad_note)
    only_bad_claim = replace(
        subject, items=tuple(item for item in subject.items if item.verbatim == _UNSUPPORTED_WORDING)
    )
    span_gold = _synthetic_gold_set(item_ref=VIDEO_A, content_identity=str(subject.content_identity))
    span_gold["videos"][0]["must_capture"] = [
        {"point_id": "synthetic-bad-span", "description": "synthetic", "start_seconds": 3, "end_seconds": 5}
    ]
    swapped_report = evaluate_subject(only_bad_claim, gold_set=parse_gold_set(span_gold))
    assert CRITERION_CLAIM_ENTAILMENT in swapped_report.failed_criteria
    assert swapped_report.metrics["must_capture_missed"] == ["synthetic-bad-span"]
    assert evaluate_source_note(clean_note).as_dict()["metrics"]["must_capture_recall"] == "not_evaluated"

    # A multi-line source wording is checked whole: a fabricated continuation line after a real
    # transcript quote fails claim_entailment instead of riding on the entailed first line.
    object_store_module._MEMORY_STORE.clear()
    fabricated = f"{_MATCHING_CUE}\nThey also upload everything to the vendor cloud."
    _register_extractors(
        claims={
            "claims": [
                _CLAIMS["claims"][0],
                {
                    "source_wording": fabricated,
                    "system_paraphrase": "The source describes local and cloud storage.",
                    "anchors": [{"segment_index": 1, "start": 2.0, "end": 6.0}],
                },
            ]
        }
    )
    _r, _c, multi_path, _cap = _acquire(tmp_path / "multi-line", monkeypatch)
    multi_note = multi_path.read_text(encoding="utf-8")
    assert "They also upload everything to the vendor cloud." in multi_note
    multi = evaluate_source_note(multi_note)
    assert multi.failed_criteria == (CRITERION_CLAIM_ENTAILMENT,)
    (multi_failure,) = multi.failures[CRITERION_CLAIM_ENTAILMENT]
    assert "Local-first knowledge tools" in multi_failure

    # Unresolvable lineage is its own failed criterion, never a silent pass.
    meta = _frontmatter(clean_note)
    orphan = clean_note.replace(str(meta["normalized_artifact_id"]), "00000000-0000-0000-0000-000000000000")
    report = evaluate_source_note(orphan)
    assert CRITERION_EVIDENCE_LINEAGE in report.failed_criteria
    assert "normalized_transcript_unresolvable" in report.failures[CRITERION_EVIDENCE_LINEAGE]


# --- AC2 ----------------------------------------------------------------------------------------


def test_quality_metrics_record_anchor_validity_and_must_capture_recall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt, _ctx, note_path, _capture = _acquire(tmp_path / "vault", monkeypatch)
    note = note_path.read_text(encoding="utf-8")
    gold = parse_gold_set(_synthetic_gold_set(item_ref=VIDEO_A, content_identity=receipt.content_identity))
    assert gold.is_owner_evidence is False

    report = evaluate_source_note(note, gold_set=gold)
    assert report.passed is True, report.failures
    assert report.metrics["anchor_validity"] == 1.0
    assert report.metrics["must_capture_recall"] == pytest.approx(2 / 3)
    assert report.metrics["must_capture_captured"] == ["synthetic-greeting", "synthetic-local-first"]
    assert report.metrics["must_capture_missed"] == ["synthetic-late"]
    # Versioned fixture lineage: gold-set identity/version/digest/provenance and the subject's
    # durable artifact lineage are recorded together.
    lineage = report.gold_set_lineage
    assert lineage is not None
    assert lineage["schema"] == GOLD_SET_SCHEMA and lineage["version"] == 1
    assert lineage["digest"].startswith("sha256:") and lineage["provenance_kind"] == SYNTHETIC_FIXTURE
    assert lineage["owner_evidence"] is False and lineage["annotation_scope_receipt"] is None
    assert lineage["entry"] == {"item_ref": VIDEO_A, "content_identity": receipt.content_identity}
    meta = _frontmatter(note)
    assert report.subject_lineage["raw_record_id"] == receipt.raw_record_id
    assert report.subject_lineage["normalized_artifact_id"] == meta["normalized_artifact_id"]
    assert report.subject_lineage["extraction_artifact_ids"] == meta["extraction_artifact_ids"]
    assert report.subject_lineage["key_moments_artifact_id"] == meta["key_moments_artifact_id"]
    assert report.subject_lineage["note_digest"].startswith("sha256:")
    # Subjective dimensions are listed for the operator, never auto-scored or auto-accepted.
    dumped = json.loads(json.dumps(report.as_dict()))
    assert dumped["operator_scored_dimensions"] == {name: "pending_operator" for name in OPERATOR_SCORED_DIMENSIONS}
    # KD-6BD17B74F8B3 / KD-0A5C9F1AB7EE observability: moment budget basis and routing outcome.
    assert report.diagnostics["source_duration_seconds"] == 600
    assert report.diagnostics["moment_budget_duration_seconds"] == 10.0
    assert report.diagnostics["content_route"] == meta["content_route"]

    # A stricter versioned threshold fails the recall criterion by name.
    strict = parse_gold_set(
        _synthetic_gold_set(item_ref=VIDEO_A, content_identity=receipt.content_identity, threshold=0.9, version=2)
    )
    failed = evaluate_source_note(note, gold_set=strict)
    assert failed.failed_criteria == (CRITERION_MUST_CAPTURE_RECALL,)
    assert failed.gold_set_lineage is not None and failed.gold_set_lineage["version"] == 2
    assert failed.gold_set_lineage["digest"] != lineage["digest"]
    # Annotations bound to another content version never silently apply to this one.
    stale = parse_gold_set(_synthetic_gold_set(item_ref=VIDEO_A, content_identity="sha256:" + "0" * 64))
    mismatch = evaluate_source_note(note, gold_set=stale)
    assert mismatch.failed_criteria == (CRITERION_MUST_CAPTURE_RECALL,)
    assert mismatch.metrics["must_capture_recall"] is None

    # Provenance cannot be misrepresented: synthetic fixtures cannot claim the owner receipt,
    # owner annotations must bind it, and the receipt's 3-video scope bounds an owner set.
    claims_owner = _synthetic_gold_set(item_ref=VIDEO_A, content_identity=receipt.content_identity)
    claims_owner["provenance"] = {"kind": SYNTHETIC_FIXTURE, "annotation_scope_receipt": ANNOTATION_SCOPE_RECEIPT}
    with pytest.raises(GoldSetError, match="synthetic fixture must not claim"):
        parse_gold_set(claims_owner)
    unbound_owner = dict(claims_owner, provenance={"kind": "owner_annotation", "annotated_by": "owner", "annotated_at": "x"})
    with pytest.raises(GoldSetError, match=ANNOTATION_SCOPE_RECEIPT):
        parse_gold_set(unbound_owner)
    oversized = dict(
        claims_owner,
        provenance={
            "kind": "owner_annotation",
            "annotation_scope_receipt": ANNOTATION_SCOPE_RECEIPT,
            "annotated_by": "owner",
            "annotated_at": "x",
        },
        videos=[dict(claims_owner["videos"][0], item_ref=f"video{n}") for n in range(4)],
    )
    with pytest.raises(GoldSetError, match="exceeds the receipt scope"):
        parse_gold_set(oversized)
    # The owner data slot is pending until the owner supplies annotations; when present it must
    # be owner evidence bound to the receipt (never a synthetic fixture in its place).
    assert load_owner_gold_set(tmp_path / "empty-repo") is None
    misplaced = tmp_path / "misplaced-repo" / OWNER_GOLD_SET_PATH
    misplaced.parent.mkdir(parents=True)
    misplaced.write_text(json.dumps(_synthetic_gold_set(item_ref=VIDEO_A, content_identity=receipt.content_identity)))
    with pytest.raises(GoldSetError, match="must hold owner annotations"):
        load_owner_gold_set(tmp_path / "misplaced-repo")
    repo_owner_set = load_owner_gold_set(REPO_ROOT)
    assert repo_owner_set is None or repo_owner_set.is_owner_evidence


# --- AC4 ----------------------------------------------------------------------------------------


def test_quality_evaluation_is_no_egress_and_non_mutating(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    receipt, context, note_path, capture = _acquire(tmp_path / "vault", monkeypatch)
    vault_root = tmp_path / "vault"
    # The owner writes into their band of the candidate; that content is human-authored.
    owner_text = "- Owner takeaway: local-first matters for my archive."
    note_path.write_text(
        note_path.read_text(encoding="utf-8").replace("<!-- Add owner-authored takeaways here. -->", owner_text),
        encoding="utf-8",
    )
    owned_bytes = note_path.read_bytes()
    gold = parse_gold_set(_synthetic_gold_set(item_ref=VIDEO_A, content_identity=receipt.content_identity))
    vault_before, store_before = _snapshot(vault_root), _store_snapshot()

    with monkeypatch.context() as sealed:
        _forbid_egress(sealed, evaluation=True)
        note_text = note_path.read_text(encoding="utf-8")
        first = evaluate_source_note(note_text, gold_set=gold)
        second = evaluate_source_note(note_text, gold_set=gold)
    assert first.passed is True, first.failures
    assert first.as_dict() == second.as_dict()  # deterministic and rebuildable from fixtures
    assert _snapshot(vault_root) == vault_before
    assert _store_snapshot() == store_before
    assert note_path.read_bytes() == owned_bytes

    # Replay is equally no-egress and never rewrites the owner's note: it emits a companion.
    with monkeypatch.context() as sealed:
        _forbid_egress(sealed, evaluation=False)
        replayed = run_replay(
            receipt.raw_record_id, vault_context=context, write_guard=_guard(), conn=_Outbox(), assert_no_source_egress=True
        )
    assert replayed.source_egress == 0
    assert capture.downloads == [VIDEO_A]  # no media recapture during replay
    candidate = next(stage for stage in replayed.stages if stage.stage == "candidate")
    assert candidate.status == "proposal_written"
    companion_path = vault_root / str(candidate.artifact_path)
    assert companion_path != note_path
    assert note_path.read_bytes() == owned_bytes
    # Every pre-existing vault file (owner note, bundle, frames) is byte-identical after replay.
    for path, data in vault_before.items():
        assert (vault_root / path).read_bytes() == data, path
    # The replayed companion is itself evaluable without egress and keeps the same evidence.
    companion = evaluate_source_note(companion_path.read_text(encoding="utf-8"), gold_set=gold)
    assert companion.passed is True, companion.failures
    assert companion.metrics["must_capture_recall"] == first.metrics["must_capture_recall"]


# --- AC5 ----------------------------------------------------------------------------------------


def test_v2_end_to_end_invariant_matrix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Representative v2 fixture: the capability-wide invariants, proven together.

    Parent-closure handoff evidence for #4107: (1) immutable versioned bundle evidence,
    (2) anchored, entailed claims, (3) non-destructive candidate materialization (D5),
    (4) governed overlay admission and the no-profile path, (5) bounded frame capture and
    timestamps-only degradation, (6) no-egress replay - all through the real acquisition-time
    pipeline, with only external seams substituted.
    """

    # --- Source A: governed profile admitted, media capture succeeds.
    root_a, _profile_note = _approved_vault(tmp_path / "vault-a")
    projection = rebuild_profile_projection(root_a, active_scope_id=_SCOPE)
    assert projection.available
    receipt_a, context_a, note_a_path, capture_a = _acquire(root_a, monkeypatch, scope=_SCOPE)
    note_a = note_a_path.read_text(encoding="utf-8")
    raw_a = get_raw_record(receipt_a.raw_record_id)
    assert raw_a is not None
    raw_a_before = json.dumps(raw_a, sort_keys=True, default=str)

    # --- Source B: no profile scope, media unavailable.
    capture_b = FakeMediaCapture(fail_with=MediaUnavailableError("video unavailable"))
    receipt_b, _context_b, note_b_path, _ = _acquire(
        tmp_path / "vault-b", monkeypatch, video_id=VIDEO_B, third_cue="A different closing cue.", capture=capture_b
    )
    note_b = note_b_path.read_text(encoding="utf-8")

    # (1) Immutable versioned bundle evidence keyed by content identity.
    (bundle_a,) = [p.parent for p in root_a.rglob("source.json")]
    digest_a = receipt_a.content_identity.removeprefix("sha256:")
    assert bundle_a.name == f"content-{digest_a}-v1"
    source_json = json.loads((bundle_a / "source.json").read_text(encoding="utf-8"))
    assert source_json["extensions"]["content_identity"] == receipt_a.content_identity
    assert source_json["extensions"]["replay_input"] == "machine_side_raw_only"
    assert receipt_a.raw_record_id in source_json["derived_from"]
    bundle_a_before = _snapshot(bundle_a)
    # New source content acquires into a new version member; the older member, its raw record
    # and its candidate note stay byte-identical.
    receipt_a2, _c, note_a2_path, _cap = _acquire(
        root_a, monkeypatch, scope=_SCOPE, third_cue="A revised closing cue.", capture=FakeMediaCapture()
    )
    assert receipt_a2.content_identity != receipt_a.content_identity
    assert receipt_a2.raw_record_id != receipt_a.raw_record_id
    assert sorted(p.parent.name for p in root_a.rglob("source.json")) == sorted(
        [bundle_a.name, f"content-{receipt_a2.content_identity.removeprefix('sha256:')}-v1"]
    )
    assert _snapshot(bundle_a) == bundle_a_before
    assert json.dumps(get_raw_record(receipt_a.raw_record_id), sort_keys=True, default=str) == raw_a_before
    assert note_a_path.read_text(encoding="utf-8") == note_a and note_a2_path != note_a_path

    # (2) Anchored claims: every rendered synthesis sentence, claim, moment and overlay quote
    # resolves to a transcript anchor and verbatim wording is entailed (synthetic gold sets).
    reports = {}
    for name, note, receipt, item_ref in (
        ("a", note_a, receipt_a, VIDEO_A),
        ("b", note_b, receipt_b, VIDEO_B),
    ):
        gold = parse_gold_set(_synthetic_gold_set(item_ref=item_ref, content_identity=receipt.content_identity))
        reports[name] = evaluate_source_note(note, gold_set=gold)
        assert reports[name].passed is True, (name, reports[name].failures)
        assert reports[name].metrics["anchor_validity"] == 1.0
        assert reports[name].metrics["claim_entailment"] == 1.0
    assert reports["a"].metrics["rendered_items_by_kind"]["overlay_source_says"] == 1
    assert "overlay_source_says" not in reports["b"].metrics["rendered_items_by_kind"]

    # (4) Governed overlay admission: the connection is bound to the receipt-backed profile
    # version for the explicit scope; without a scope the single no-profile line renders.
    meta_a, meta_b = _frontmatter(note_a), _frontmatter(note_b)
    assert meta_a["interest_overlay"]["status"] == "connections"
    assert meta_a["interest_overlay"]["profile_scope_id"] == _SCOPE
    assert meta_a["interest_overlay"]["profile_version_id"] == projection.version_id
    assert meta_a["interest_overlay"]["profile_receipt_id"] == projection.receipt_id
    assert f"approved profile version {projection.version_id}" in note_a
    assert meta_b["interest_overlay"]["status"] == "no-profile"
    assert meta_b["interest_overlay"]["reason"] == "missing_or_invalid_active_scope"
    assert note_b.count(NO_PROFILE_LINES["en"]) == 1
    for meta in (meta_a, meta_b):
        assert meta["authority"] == {"source_authoritative": False, "ai_generated": True, "requires_review": True}

    # (5) Bounded frame capture: one bounded download, one retained context frame, temporary
    # media deleted with a receipt; unavailable media degrades B to timestamps-only.
    assert capture_a.downloads == [VIDEO_A]
    manifest_path = bundle_a / "frames.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    (frame,) = manifest["frames"]
    assert frame["frame_role"] == "context_frame" and frame["media_role"] == "media_derivative"
    assert manifest["deletion_receipt"]["status"] == "deleted"
    assert manifest["deletion_receipt"]["remaining_entries"] == 0
    assert f"]({frame['path']})" in note_a
    assert not [p for p in root_a.rglob("*") if p.suffix in {".mp4", ".webm", ".mkv"}]
    assert capture_b.downloads == [VIDEO_B]
    assert not list((tmp_path / "vault-b").rglob("*.jpg"))
    assert "### Timestamped moments" in note_b and "![" not in note_b
    assert "timestamps-only (capture_failed: video unavailable)" in note_b
    assert "**Materialization status:** complete" in note_b

    # (3) + (6) Non-destructive materialization and no-egress replay: the owner edits A, replay
    # runs with every source/model boundary forbidden, writes a D5 companion, never recaptures
    # media, and leaves the owner's note, raw evidence and retained frames byte-identical.
    owner_text = "- Owner takeaway: keep this for the archive decision."
    note_a_path.write_text(note_a.replace("<!-- Add owner-authored takeaways here. -->", owner_text), encoding="utf-8")
    owned = note_a_path.read_bytes()
    frames_before = {p: p.read_bytes() for p in root_a.rglob("*.jpg")}
    with monkeypatch.context() as sealed:
        _forbid_egress(sealed, evaluation=False)
        replayed = run_replay(
            receipt_a.raw_record_id, vault_context=context_a, write_guard=_guard(), conn=_Outbox(), assert_no_source_egress=True
        )
    assert replayed.source_egress == 0
    candidate = next(stage for stage in replayed.stages if stage.stage == "candidate")
    assert candidate.status == "proposal_written"
    companion_path = root_a / str(candidate.artifact_path)
    assert companion_path not in (note_a_path, note_a2_path)
    assert note_a_path.read_bytes() == owned
    assert {p: p.read_bytes() for p in root_a.rglob("*.jpg")} == frames_before
    assert capture_a.downloads == [VIDEO_A]
    assert _snapshot(bundle_a) == bundle_a_before
    assert json.dumps(get_raw_record(receipt_a.raw_record_id), sort_keys=True, default=str) == raw_a_before
    companion = companion_path.read_text(encoding="utf-8")
    assert f"]({frame['path']})" in companion  # retained frame re-referenced, never recaptured
    replay_report = evaluate_source_note(
        companion,
        gold_set=parse_gold_set(_synthetic_gold_set(item_ref=VIDEO_A, content_identity=receipt_a.content_identity)),
    )
    assert replay_report.passed is True, replay_report.failures
    assert replay_report.metrics["must_capture_recall"] == reports["a"].metrics["must_capture_recall"]
