"""KA-05 tests for candidate assembly + governed `youtube_source_note` writeback.

Covers `docs/KNOWLEDGE_ACQUISITION/CANDIDATE_WRITEBACK.md`'s four acceptance criteria. No network,
no real LLM call: the `summary` extractor's completion is stubbed through the same `complete=`
injection seam `test_summary_extractor.py` uses. Every test uses a temp-vault fixture — never a
real vault path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from app.knowledge_acquisition.candidate_writeback import (
    ARTIFACT_CLASS,
    CANDIDATE_WRITE_ACTION,
    REVIEW_STATE_DRAFT,
    TRIAGE_STATE_CAPTURED,
    Candidate,
    CandidateWriteResult,
    assemble_candidate,
    candidate_note_path,
    write_candidate_note,
)
from app.knowledge_acquisition.extraction_registry import clear_registry
from app.knowledge_acquisition.extractors import summary_extractor
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard, WritesBlockedError

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


def test_write_does_not_touch_filesystem_when_guard_denies(tmp_path: Path) -> None:
    """No direct filesystem write bypassing the guard: a denial leaves no artifact at all."""
    vault_root = tmp_path / "vault"
    vault = _vault(vault_root)
    candidate = _assembled_candidate()

    result = write_candidate_note(candidate, vault_context=vault, write_guard=_blocking_guard())

    assert result.status == "blocked"
    expected_path = candidate_note_path(candidate)
    assert not (vault_root / expected_path).exists()
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

    # Template shape: About / AI summary (non-authoritative) / Human takeaways.
    assert "## About" in body
    assert "## AI summary" in body
    assert "non-authoritative" in body
    assert "## Human takeaways" in body
    assert "A deterministic test summary." in body

    # The source video remains the authoritative source; the note itself is not authoritative.
    assert frontmatter["authority"]["source_authoritative"] is False


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


def test_rerun_same_candidate_is_idempotent_not_duplicated(tmp_path: Path) -> None:
    """Re-running the same candidate targets the same note path and does not duplicate it
    (spec: 'the write retries idempotently — same note path, same content identity')."""
    vault_root = tmp_path / "vault"
    vault = _vault(vault_root)
    candidate = _assembled_candidate()

    first = write_candidate_note(candidate, vault_context=vault, write_guard=_allowing_guard())
    assert first.status == "written"

    second = write_candidate_note(candidate, vault_context=vault, write_guard=_allowing_guard())
    assert second.status == "already_exists"
    assert second.artifact_path == first.artifact_path

    all_notes = list(vault_root.rglob("*.md"))
    assert len(all_notes) == 1


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
    retried_result = write_candidate_note(candidate, vault_context=vault, write_guard=_allowing_guard())
    assert retried_result.status == "written"
    assert retried_result.artifact_path == expected_path


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
