"""KA-05 tests for candidate assembly + governed `youtube_source_note` writeback.

Covers `docs/KNOWLEDGE_ACQUISITION/CANDIDATE_WRITEBACK.md`'s four acceptance criteria. No network,
no real LLM call: the `summary` extractor's completion is stubbed through the same `complete=`
injection seam `test_summary_extractor.py` uses. Every test uses a temp-vault fixture — never a
real vault path.
"""

from __future__ import annotations

from dataclasses import replace
import errno
import json
import os
from pathlib import Path
import threading

import pytest
import yaml

import app.knowledge_acquisition.candidate_writeback as candidate_writeback
from app.knowledge_acquisition.candidate_writeback import (
    ARTIFACT_CLASS,
    CANDIDATE_WRITE_ACTION,
    REVIEW_STATE_DRAFT,
    TRIAGE_STATE_CAPTURED,
    Candidate,
    CandidateWriteResult,
    CandidateWritebackError,
    assemble_candidate,
    candidate_note_path,
    render_candidate_note,
    write_candidate_note,
)
from app.knowledge_acquisition.extraction_registry import ExtractionResult, clear_registry
from app.knowledge_acquisition.extractors import summary_extractor
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard, WritesBlockedError
from tests.knowledge.candidate_create_oracles import (
    FdOracle,
    assert_exact_fd_ownership,
)

RAW_RECORD_FIXTURE = {
    "source_kind": "youtube_url",
    "item_ref": "dQw4w9WgXcQ",
    "url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
    "content_identity": "sha256:candidate-fixture-identity",
    "acquisition_method": "captions_manual",
    "caption_language": "en",
    "caption_body": (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "Hello world\n\n"
        "00:00:02.000 --> 00:00:04.000\n"
        "This is a transcript about testing.\n"
    ),
    "metadata": {
        "title": "A Test Video",
        "channel": "Test Channel",
        "publish_date": "20260101",
        "chapters": [],
    },
    "provenance": {
        "source_kind": "youtube_url",
        "url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
        "creator": "Test Channel",
        "published": "20260101",
        "acquisition_method": "captions_manual",
    },
}


def _stub_completion(raw: str):
    def complete(*, system: str, user: str, trace_id=None, max_tokens=None) -> str:
        return raw

    return complete


@pytest.fixture(autouse=True)
def _reset_registry():
    """Re-register the production `summary` extractor after each test's registry reset (same
    pattern as `test_summary_extractor.py`), so this module never leaks a stubbed spec into other
    test modules relying on the real registration."""
    yield
    clear_registry()
    summary_extractor.register()


def _vault(root: Path) -> VaultContext:
    root.mkdir(parents=True, exist_ok=True)
    return VaultContext(
        status="selected",
        active_vault_id="vault-test",
        active_vault_name="Vault Test",
        active_vault_path=str(root),
    )


def _allowing_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _blocking_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "safe_mode", "reason": "test-induced block"})


def _assembled_candidate(raw: dict | None = None) -> Candidate:
    summary_extractor.register(
        complete=_stub_completion(
            json.dumps({"summary": "A deterministic test summary.", "confidence": 0.75})
        )
    )
    return assemble_candidate(raw if raw is not None else RAW_RECORD_FIXTURE)


# ---------------------------------------------------------------------------
# AC1: note written through the governed vault-write path, asserted at the
# production call site.
# ---------------------------------------------------------------------------


def test_write_goes_through_writeguard_callsite(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault = _vault(vault_root)
    candidate = _assembled_candidate()

    calls: list[str] = []
    guard = WriteGuard(lambda: {"state": "healthy"})
    original_assert = guard.assert_writes_allowed

    def _tracking_assert(action: str) -> None:
        calls.append(action)
        original_assert(action)

    guard.assert_writes_allowed = _tracking_assert  # type: ignore[method-assign]

    result = write_candidate_note(candidate, vault_context=vault, write_guard=guard)

    assert result.status == "written"
    assert calls == [CANDIDATE_WRITE_ACTION]
    # The production call site: the note only exists on disk because the guard was consulted
    # immediately before the write, not as an incidental side effect.
    assert (vault_root / result.artifact_path).exists()


def test_writeguard_denial_creates_no_candidate_parent(tmp_path: Path) -> None:
    """No direct filesystem write bypassing the guard: a denial leaves no artifact at all."""
    vault_root = tmp_path / "vault"
    vault = _vault(vault_root)
    candidate = _assembled_candidate()

    result = write_candidate_note(candidate, vault_context=vault, write_guard=_blocking_guard())

    assert result.status == "blocked"
    expected_path = candidate_note_path(candidate)
    assert not (vault_root / expected_path).exists()
    assert not (vault_root / "Sources").exists()
    # Confirm nothing at all landed under the vault root.
    assert list(vault_root.rglob("*.md")) == []


# ---------------------------------------------------------------------------
# AC2: note carries posture markers + provenance + template shape.
# ---------------------------------------------------------------------------


def test_note_shape_and_posture_markers(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault = _vault(vault_root)
    candidate = _assembled_candidate()

    result = write_candidate_note(candidate, vault_context=vault, write_guard=_allowing_guard())
    assert result.status == "written"

    note_text = (vault_root / result.artifact_path).read_text(encoding="utf-8")
    assert note_text.startswith("---\n")
    fm_text, body = note_text.split("---\n", 2)[1:]
    frontmatter = yaml.safe_load(fm_text)

    # Mandated posture markers (#2793 token mapping).
    assert frontmatter["authority"]["requires_review"] is True
    assert frontmatter["review_state"] == REVIEW_STATE_DRAFT

    # Artifact class + provenance.
    assert frontmatter["artifact_class"] == ARTIFACT_CLASS
    assert frontmatter["transcript_available"] is True
    provenance = frontmatter["provenance"]
    assert provenance["source_kind"] == "youtube_url"
    assert provenance["url"] == RAW_RECORD_FIXTURE["url"]
    assert provenance["content_identity"] == RAW_RECORD_FIXTURE["content_identity"]
    assert provenance["acquisition_method"] == "captions_manual"

    # Authority-banded template shape: owner notes / one proposal wrapper /
    # deterministic evidence and lineage.
    assert "## Owner notes" in body
    assert "### Takeaways" in body
    assert "### Open threads" in body
    assert body.count("## Proposals (non-authoritative)") == 1
    assert "### Summary" in body
    assert "## Evidence and lineage" in body
    assert "non-authoritative" in body
    assert "A deterministic test summary." in body

    # The source video remains the authoritative source; the note itself is not authoritative.
    assert frontmatter["authority"]["source_authoritative"] is False


def test_candidate_transcript_availability_reflects_usable_evidence() -> None:
    """An empty ASR result is a valid no-transcript candidate, not evidence for a summary."""
    raw_without_transcript = {
        **RAW_RECORD_FIXTURE,
        "acquisition_method": "asr",
        "caption_body": "",
        "asr_segments": [],
    }

    def _unexpected_completion(**_kwargs) -> str:
        raise AssertionError("summary extraction must not run without usable transcript evidence")

    summary_extractor.register(complete=_unexpected_completion)
    candidate = assemble_candidate(raw_without_transcript)
    rendered = render_candidate_note(candidate)
    fm_text, body = rendered.split("---\n", 2)[1:]

    assert candidate.transcript_available is False
    assert candidate.summary_text() is None
    assert yaml.safe_load(fm_text)["transcript_available"] is False
    assert "Model confidence" not in body
    assert "**Coverage:** 0 normalized segments; no transcript evidence" in body
    proposals = body.split("## Proposals (non-authoritative)", 1)[1].split(
        "## Evidence and lineage",
        1,
    )[0]
    assert "Coverage:" not in proposals


def test_rendered_summary_preserves_model_confidence() -> None:
    candidate = _assembled_candidate()

    rendered = render_candidate_note(candidate)

    assert "Model confidence (non-authoritative):** 0.75" in rendered
    assert "Coverage:** 2/2 normalized segments (100%; complete transcript)" in rendered
    assert "A deterministic test summary." in rendered


def test_rendered_summary_rejects_non_finite_confidence_defensively() -> None:
    candidate = Candidate(
        content_identity="sha256:non-finite-confidence",
        source_kind="youtube_url",
        item_ref="dQw4w9WgXcQ",
        url="https://youtube.com/watch?v=dQw4w9WgXcQ",
        title="A Test Video",
        creator="Test Channel",
        published="20260101",
        acquisition_method="captions_manual",
        transcript_available=True,
        extractions=(
            ExtractionResult(
                extractor_id="summary",
                extractor_version=2,
                source_content_identity="sha256:non-finite-confidence",
                output={"summary": "Must not render.", "confidence": float("nan")},
                model_identity={"provider": "mock", "model": "mock"},
            ),
        ),
        transcript_segment_count=1,
    )

    rendered = render_candidate_note(candidate)

    assert "Must not render." not in rendered
    assert "Model confidence" not in rendered


def test_template_file_carries_mandated_posture_markers() -> None:
    """Doc-diff companion: the shipped template itself (not just the written note) carries the
    extension delivered in this task."""
    template_path = Path("docs/examples/vault-templates/youtube-source-note.md")
    text = template_path.read_text(encoding="utf-8")
    fm_text = text.split("---\n", 2)[1]
    frontmatter = yaml.safe_load(fm_text)
    assert "review_state" in frontmatter
    assert frontmatter["review_state"] == REVIEW_STATE_DRAFT
    assert "requires_review" in frontmatter["authority"]


# ---------------------------------------------------------------------------
# AC3: written note enters triage at `captured`; no advancement; no mutation
# of any existing artifact.
# ---------------------------------------------------------------------------


def test_triage_entry_is_captured_no_advancement(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault = _vault(vault_root)
    candidate = _assembled_candidate()

    result = write_candidate_note(candidate, vault_context=vault, write_guard=_allowing_guard())
    assert result.status == "written"

    note_text = (vault_root / result.artifact_path).read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(note_text.split("---\n", 2)[1])

    assert frontmatter["triage_state"] == TRIAGE_STATE_CAPTURED
    # No field anywhere claims a later triage state.
    assert frontmatter["triage_state"] != "triaged"
    assert frontmatter["triage_state"] != "promoted"


def test_no_existing_artifact_mutation(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault = _vault(vault_root)

    # A pre-existing, unrelated vault note plus its content hash/mtime.
    existing_note = vault_root / "Evergreen" / "unrelated-note.md"
    existing_note.parent.mkdir(parents=True, exist_ok=True)
    existing_content = "---\nartifact_class: evergreen_note\nreview_state: reviewed\n---\n\nBody.\n"
    existing_note.write_text(existing_content, encoding="utf-8")
    existing_mtime_before = existing_note.stat().st_mtime_ns

    candidate = _assembled_candidate()
    result = write_candidate_note(candidate, vault_context=vault, write_guard=_allowing_guard())
    assert result.status == "written"

    # The pre-existing artifact is byte-identical and untouched.
    assert existing_note.read_text(encoding="utf-8") == existing_content
    assert existing_note.stat().st_mtime_ns == existing_mtime_before


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "root_open",
        "sources_open",
        "intermediate_open",
        "final_parent_open",
        "parent_fsync",
        "root_close",
        "sources_close",
        "intermediate_close",
        "final_parent_close",
        "target_stat",
        "nonregular_target",
    ],
)
def test_rerun_existing_candidate_returns_before_render_and_creates_no_recovery_artifact(
    fault: str | None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The durable existing-target probe is fail-closed and stays before render/guard."""

    vault_root = tmp_path / "vault"
    vault = _vault(vault_root)
    candidate = _assembled_candidate()
    sources_dir = "Sources/one/two"
    relative = candidate_note_path(candidate, sources_dir=sources_dir)
    target = vault_root / relative

    if fault == "nonregular_target":
        target.mkdir(parents=True)
        expected_bytes: bytes | None = None
    else:
        first = write_candidate_note(
            candidate,
            vault_context=vault,
            write_guard=_allowing_guard(),
            sources_dir=sources_dir,
        )
        assert first.status == "written"
        expected_bytes = target.read_bytes()

    def forbidden_render(_candidate: Candidate) -> str:
        raise AssertionError("existing-target probe must return before rendering")

    monkeypatch.setattr(candidate_writeback, "render_candidate_note", forbidden_render)
    guard = _allowing_guard()

    def forbidden_guard(_action: str) -> None:
        raise AssertionError("existing-target probe must return before WriteGuard")

    guard.assert_writes_allowed = forbidden_guard  # type: ignore[method-assign]
    oracle = FdOracle()
    oracle.install(monkeypatch)
    real_open = os.open
    real_close = os.close
    real_fsync = os.fsync
    real_stat = os.stat
    fd_labels: dict[int, str] = {}
    fired = 0

    def hit(message: str) -> None:
        nonlocal fired
        fired += 1
        raise OSError(errno.EIO, message)

    def faulting_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        decoded = os.fsdecode(path)
        label = (
            "root"
            if dir_fd is None
            else {
                "Sources": "sources",
                "one": "intermediate",
                "two": "final_parent",
            }.get(decoded, decoded)
        )
        if fault == f"{label}_open":
            hit(f"{label} open fault")
        fd = real_open(path, flags, mode, dir_fd=dir_fd)
        fd_labels[fd] = label
        return fd

    def faulting_close(fd: int) -> None:
        label = fd_labels.pop(fd, "unknown")
        if fault == f"{label}_close":
            real_close(fd)
            hit(f"{label} close fault")
        real_close(fd)

    def faulting_fsync(fd: int) -> None:
        if fault == "parent_fsync" and fd_labels.get(fd) == "final_parent":
            hit("parent fsync fault")
        real_fsync(fd)

    def faulting_stat(
        path: str | bytes | int | os.PathLike[str] | os.PathLike[bytes],
        *,
        dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> os.stat_result:
        if fault == "target_stat" and path == target.name:
            hit("target stat fault")
        return real_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(os, "open", faulting_open)
    monkeypatch.setattr(os, "close", faulting_close)
    monkeypatch.setattr(os, "fsync", faulting_fsync)
    monkeypatch.setattr(os, "stat", faulting_stat)

    with oracle.observe():
        if fault is None:
            second = write_candidate_note(
                candidate,
                vault_context=vault,
                write_guard=guard,
                sources_dir=sources_dir,
            )
            assert second.status == "already_exists"
            assert second.artifact_path == relative
        else:
            with pytest.raises(CandidateWritebackError):
                write_candidate_note(
                    candidate,
                    vault_context=vault,
                    write_guard=guard,
                    sources_dir=sources_dir,
                )
            if fault != "nonregular_target":
                assert fired == 1

    if expected_bytes is not None:
        assert target.read_bytes() == expected_bytes
    assert list(target.parent.glob(".candidate-stage-*")) == []
    assert fd_labels == {}
    assert_exact_fd_ownership(
        oracle.opened,
        oracle.close_attempts,
        oracle.duplicates,
    )
    assert oracle.active == {}


def test_composer_preserves_human_authored_band_on_rerun(tmp_path: Path) -> None:
    """A replay never regenerates or rewrites the owner-authored authority band."""
    vault_root = tmp_path / "vault"
    vault = _vault(vault_root)
    candidate = _assembled_candidate()

    first = write_candidate_note(candidate, vault_context=vault, write_guard=_allowing_guard())
    assert first.status == "written"
    note_path = vault_root / first.artifact_path
    initial = note_path.read_text(encoding="utf-8")
    assert "## Owner notes" in initial
    assert "### Takeaways" in initial
    assert "### Open threads" in initial

    human_takeaway = "The owner keeps this exact takeaway."
    human_thread = "The owner keeps this exact open thread."
    edited = initial.replace(
        "<!-- Add owner-authored takeaways here. -->",
        human_takeaway,
    ).replace(
        "<!-- Add owner-authored open threads here. -->",
        human_thread,
    )
    note_path.write_text(edited, encoding="utf-8")
    edited_bytes = note_path.read_bytes()

    drifted = replace(
        candidate,
        extractions=(
            ExtractionResult(
                extractor_id="summary",
                extractor_version=2,
                source_content_identity=candidate.content_identity,
                output={"summary": "A later generated summary.", "confidence": 0.9},
                model_identity={"provider": "mock", "model": "mock"},
            ),
        ),
    )
    second = write_candidate_note(drifted, vault_context=vault, write_guard=_allowing_guard())

    assert second.status == "already_exists"
    assert note_path.read_bytes() == edited_bytes
    assert human_takeaway in note_path.read_text(encoding="utf-8")
    assert human_thread in note_path.read_text(encoding="utf-8")
    assert "A later generated summary." not in note_path.read_text(encoding="utf-8")


def test_composer_wraps_proposals_and_omits_absent_modules() -> None:
    candidate = _assembled_candidate()

    rendered = render_candidate_note(candidate)

    assert rendered.count("## Proposals (non-authoritative)") == 1
    assert rendered.count("### Summary") == 1
    assert "## AI summary" not in rendered
    assert rendered.index("## Owner notes") < rendered.index("## Proposals (non-authoritative)")
    assert rendered.index("### Summary") < rendered.index("## Evidence and lineage")
    assert rendered.index("A deterministic test summary.") < rendered.index(
        "## Evidence and lineage"
    )
    proposals_start = rendered.index("## Proposals (non-authoritative)")
    evidence_start = rendered.index("## Evidence and lineage")
    coverage_start = rendered.index("**Coverage:**")
    assert proposals_start < evidence_start < coverage_start
    assert "**Coverage:**" not in rendered[proposals_start:evidence_start]

    no_transcript = replace(
        candidate,
        transcript_available=False,
        extractions=(),
        transcript_segment_count=0,
    )
    degraded = render_candidate_note(no_transcript)

    assert degraded.count("## Proposals (non-authoritative)") == 1
    assert "### Summary" not in degraded
    assert "## AI summary" not in degraded
    assert "AI summary goes here" not in degraded
    assert "_No proposal modules were produced._" in degraded
    assert "**Coverage:** 0 normalized segments; no transcript evidence" in degraded


# ---------------------------------------------------------------------------
# AC4: blocked write (WriteGuard denial fixture) is loud, item-scoped,
# retryable; candidate is not terminal.
# ---------------------------------------------------------------------------


def test_blocked_write_is_loud_and_retryable(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault = _vault(vault_root)
    candidate = _assembled_candidate()

    blocked_result = write_candidate_note(
        candidate, vault_context=vault, write_guard=_blocking_guard()
    )

    # Loud: the block reason is preserved, not swallowed.
    assert blocked_result.status == "blocked"
    assert blocked_result.artifact_path is None
    assert blocked_result.reason
    assert "safe_mode" in blocked_result.reason

    # Item-scoped: nothing durable was written for this candidate.
    expected_path = candidate_note_path(candidate)
    assert not (vault_root / expected_path).exists()

    # Not terminal: the same candidate can be retried once writes are allowed again, and it
    # then succeeds normally (no leftover partial state blocked the retry).
    retried_result = write_candidate_note(
        candidate, vault_context=vault, write_guard=_allowing_guard()
    )
    assert retried_result.status == "written"
    assert retried_result.artifact_path == expected_path


def test_candidate_is_terminal_only_after_note_materialization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    vault = _vault(vault_root)
    candidate = _assembled_candidate()

    def _fail_materialization(*_args, **_kwargs) -> None:
        raise OSError("test materialization failure")

    monkeypatch.setattr(candidate_writeback, "create_candidate_note_once", _fail_materialization)

    with pytest.raises(
        candidate_writeback.CandidateWritebackError, match="materialization failure"
    ):
        write_candidate_note(candidate, vault_context=vault, write_guard=_allowing_guard())

    assert not (vault_root / candidate_note_path(candidate)).exists()


def test_blocked_write_raises_writesblockederror_is_catchable() -> None:
    """The underlying WriteGuard exception type is the standard, well-known one — callers already
    handling `WritesBlockedError` elsewhere in the codebase get consistent behavior here too."""
    guard = _blocking_guard()
    with pytest.raises(WritesBlockedError):
        guard.assert_writes_allowed(CANDIDATE_WRITE_ACTION)


# ---------------------------------------------------------------------------
# First-write-wins under extraction drift (opus review round 1 probe, pinned).
# ---------------------------------------------------------------------------


def test_rerun_with_drifted_summary_preserves_first_write(tmp_path: Path) -> None:
    """Re-running the same content_identity with a DIFFERENT extraction output must not clobber
    the already-written note: status is `already_exists`, the on-disk note stays byte-identical
    to the first write (VERSION A preserved, VERSION B absent), and exactly one note exists.

    `clear_registry()` between the two runs is the fresh-process-equivalent setup: without it,
    KA-04's in-process idempotency cache would return the first extraction unchanged and mask
    the drift this test exists to probe."""
    vault_root = tmp_path / "vault"
    vault = _vault(vault_root)

    candidate_a = _assembled_candidate()
    first = write_candidate_note(candidate_a, vault_context=vault, write_guard=_allowing_guard())
    assert first.status == "written"
    note_bytes_a = (vault_root / first.artifact_path).read_bytes()
    assert b"A deterministic test summary." in note_bytes_a

    # Fresh-process equivalent: wipe the extraction cache so the drifted summary genuinely
    # re-runs rather than replaying the cached VERSION A extraction.
    clear_registry()
    summary_extractor.register(
        complete=_stub_completion(
            json.dumps({"summary": "A DRIFTED second summary.", "confidence": 0.9})
        )
    )
    candidate_b = assemble_candidate(RAW_RECORD_FIXTURE)
    assert candidate_b.summary_text() == "A DRIFTED second summary."
    assert candidate_b.content_identity == candidate_a.content_identity

    second = write_candidate_note(candidate_b, vault_context=vault, write_guard=_allowing_guard())
    assert second.status == "already_exists"
    assert second.artifact_path == first.artifact_path

    # First write wins: byte-identical note, drifted text absent, exactly one note on disk.
    note_bytes_after = (vault_root / first.artifact_path).read_bytes()
    assert note_bytes_after == note_bytes_a
    assert b"A DRIFTED second summary." not in note_bytes_after
    assert len(list(vault_root.rglob("*.md"))) == 1


def test_note_path_uses_full_identity_entropy() -> None:
    """Regression (opus review round 1): the identity's scheme prefix must not consume the
    16-char path window. Two `sha256:<hex>` identities sharing their first 16 raw characters
    (including the constant `sha256:` prefix) but diverging afterwards must map to DIFFERENT
    note paths — under the pre-fix slugging, both collapsed to `...-sha256-aaaaaaaaa.md`."""

    def _candidate_with_identity(content_identity: str) -> Candidate:
        return Candidate(
            content_identity=content_identity,
            source_kind="youtube_url",
            item_ref="dQw4w9WgXcQ",
            url="https://youtube.com/watch?v=dQw4w9WgXcQ",
            title="A Test Video",
            creator="Test Channel",
            published="20260101",
            acquisition_method="captions_manual",
            transcript_available=True,
            extractions=(),
        )

    shared_prefix = "sha256:aaaaaaaaa"  # 16 chars of the full string, 9 of hash payload
    path_a = candidate_note_path(_candidate_with_identity(shared_prefix + "1" * 40))
    path_b = candidate_note_path(_candidate_with_identity(shared_prefix + "2" * 40))

    assert path_a != path_b
    # And the scheme prefix itself never appears in the path segment.
    assert "sha256" not in path_a.rsplit("/", 1)[-1]


# ---------------------------------------------------------------------------
# Assembly-level checks (re-derivation from raw, in-process; no durable
# extraction handoff).
# ---------------------------------------------------------------------------


def test_assemble_candidate_rederives_from_raw() -> None:
    candidate = _assembled_candidate()
    assert candidate.content_identity == RAW_RECORD_FIXTURE["content_identity"]
    assert candidate.title == "A Test Video"
    assert candidate.acquisition_method == "captions_manual"
    assert candidate.transcript_available is True
    assert candidate.summary_text() == "A deterministic test summary."


def test_candidate_write_result_is_frozen_dataclass() -> None:
    result = CandidateWriteResult(
        status="written", artifact_path="Sources/x.md", content_identity="sha256:x"
    )
    with pytest.raises(Exception):
        result.status = "blocked"  # type: ignore[misc]


def test_replay_proposal_race_reconciles_loser_after_candidate_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    vault = _vault(vault_root)
    candidate = _assembled_candidate()
    candidate = replace(
        candidate,
        raw_record_id="raw-race",
        normalized_artifact_id="normalized-race",
        extraction_artifact_ids=("extract-race",),
    )
    barrier = threading.Barrier(2)
    original_probe = candidate_writeback.candidate_note_exists_durable
    calls = {"count": 0}
    calls_lock = threading.Lock()

    def synchronized_probe(*args, **kwargs):
        with calls_lock:
            calls["count"] += 1
            call_number = calls["count"]
        result = original_probe(*args, **kwargs)
        if call_number <= 2:
            barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(
        candidate_writeback, "candidate_note_exists_durable", synchronized_probe
    )

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _index: write_candidate_note(
                    candidate,
                    vault_context=vault,
                    write_guard=_allowing_guard(),
                    proposal_on_existing=True,
                ),
                range(2),
            )
        )

    assert {result.status for result in results} == {"written", "proposal_written"}
    assert len(list(vault_root.rglob("*.md"))) == 2
    assert len(list(vault_root.rglob("*.meta.md"))) == 1
