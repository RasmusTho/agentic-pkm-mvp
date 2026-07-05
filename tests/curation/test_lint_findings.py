"""#2986 (G2-1) -- vault-health lint pipeline.

Spec: ``docs/MIMER_CAPABILITY_HARDENING/GRADUATED_CURATION.md`` §5, §6.

Covers:
- idempotent rerun over an unchanged fixture vault (identical finding ids,
  no duplicate report entries),
- each of the eight initial lint checks against a fixture note that
  triggers it,
- missing ``uuid`` is advisory only and never blocks report generation.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.curation.findings import FindingClass, FindingTrack
from app.curation.lint import (
    LINT_REPORT_WRITE_ACTION,
    render_lint_report,
    run_vault_lint,
    write_lint_report,
)
from app.write_guard import WriteGuard, WritesBlockedError


def _write_note(vault_root: Path, rel_path: str, content: str) -> Path:
    path = vault_root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _allow_all_guard() -> WriteGuard:
    return WriteGuard(snapshot_fn=lambda: {"state": "healthy", "reason": None})


def _blocking_guard() -> WriteGuard:
    return WriteGuard(snapshot_fn=lambda: {"state": "safe_mode", "reason": "test-blocked"})


# ---------------------------------------------------------------------------
# Fixture vault covering every one of the eight initial checks
# ---------------------------------------------------------------------------


@pytest.fixture
def fixture_vault(tmp_path: Path) -> Path:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    # 1. Orphan note: no inbound wikilinks from anywhere else in the vault.
    _write_note(
        vault_root,
        "orphan-note.md",
        "---\nuuid: uuid-orphan\nkind: note\n---\n\nThis note has no inbound links to it at all here.\n",
    )

    # A "hub" note that links to a known-good target, so the target is NOT orphaned.
    _write_note(
        vault_root,
        "target-note.md",
        "---\nuuid: uuid-target\nkind: note\n---\n\nA target note that is linked from the hub below with plenty of body text.\n",
    )
    _write_note(
        vault_root,
        "hub-note.md",
        "---\nuuid: uuid-hub\nkind: note\n---\n\nSee [[target-note]] for more. This hub also has enough words to not be a stub.\n",
    )

    # 2. Dead wikilink: points at a title that resolves to no note.
    _write_note(
        vault_root,
        "dead-wikilink-note.md",
        "---\nuuid: uuid-dead-wikilink\nkind: note\n---\n\nSee [[Nonexistent Target]] which does not resolve to anything real.\n",
    )

    # 3. Dead external link: uses the reserved dead-link marker host.
    _write_note(
        vault_root,
        "dead-external-note.md",
        "---\nuuid: uuid-dead-external\nkind: note\n---\n\nSee [broken](https://dead.invalid/page) for details on this topic.\n",
    )

    # 4. Frontmatter schema violation: unterminated frontmatter block.
    _write_note(
        vault_root,
        "bad-frontmatter-note.md",
        "---\nuuid: uuid-bad-frontmatter\nkind: note\nThis frontmatter block never closes and has enough words.\n",
    )

    # 5. Empty/stub note: body under the word-count floor.
    _write_note(
        vault_root,
        "stub-note.md",
        "---\nuuid: uuid-stub\nkind: note\n---\n\nToo short.\n",
    )

    # 6. Staleness by note-kind policy: a `task` note with an old `updated` stamp.
    _write_note(
        vault_root,
        "stale-task-note.md",
        (
            "---\nuuid: uuid-stale-task\nkind: task\nupdated: 2020-01-01T00:00:00Z\n---\n\n"
            "An old task note that should be flagged as stale by kind policy here.\n"
        ),
    )

    # 7. Panel block with a stale option marker (proposed without option_id).
    _write_note(
        vault_root,
        "stale-panel-note.md",
        (
            "---\nuuid: uuid-stale-panel\nkind: note\n---\n\n"
            "%% ai %%\n## AI-åtgärder\n"
            "- [ ] Do the thing <!--ai:proposed=123-->\n"
            "%% ai %%\n\n"
            "Some body text so this note is not itself flagged as a stub note.\n"
        ),
    )

    # 8. Missing uuid -- advisory only.
    _write_note(
        vault_root,
        "no-uuid-note.md",
        "---\nkind: note\n---\n\nThis note has no uuid at all but plenty of body text here.\n",
    )

    return vault_root


def test_each_initial_check_produces_the_expected_finding(fixture_vault: Path) -> None:
    """Each of the eight initial lint checks fires on its dedicated trigger fixture."""
    report = run_vault_lint(fixture_vault)
    by_class: dict[FindingClass, list] = {}
    for finding in report.findings:
        by_class.setdefault(finding.finding_class, []).append(finding)

    # 1. orphan
    orphan_paths = {f.evidence[0] for f in by_class.get(FindingClass.STRUCTURE_ORPHAN, [])}
    assert "orphan-note.md" in orphan_paths
    assert "target-note.md" not in orphan_paths  # linked from hub-note

    # 2. dead wikilink
    dead_wikilink_paths = {f.evidence[0] for f in by_class.get(FindingClass.LINK_BROKEN_WIKILINK, [])}
    assert "dead-wikilink-note.md" in dead_wikilink_paths

    # 3. dead external link
    dead_external_paths = {f.evidence[0] for f in by_class.get(FindingClass.LINK_DEAD_EXTERNAL, [])}
    assert "dead-external-note.md" in dead_external_paths

    # 4. frontmatter schema violation
    bad_fm_paths = {f.evidence[0] for f in by_class.get(FindingClass.FRONTMATTER_SCHEMA_VIOLATION, [])}
    assert "bad-frontmatter-note.md" in bad_fm_paths

    # 5. empty/stub note + 6. staleness + 7. stale panel marker + 8. missing uuid
    # all currently classify as STRUCTURE_GAP -- assert by evidence path instead
    # of by class, since STRUCTURE_GAP is a shared bucket for several checks.
    gap_paths = {f.evidence[0] for f in by_class.get(FindingClass.STRUCTURE_GAP, [])}
    assert "stub-note.md" in gap_paths
    assert "stale-panel-note.md" in gap_paths
    assert "no-uuid-note.md" in gap_paths

    stale_paths = {f.evidence[0] for f in by_class.get(FindingClass.STRUCTURE_STALE_CLAIM, [])}
    assert "stale-task-note.md" in stale_paths

    # Track is derived purely from the closed class->track wall (never invented
    # here); no auto_fix writer exists in this slice regardless of a finding's
    # derived track (propose-only enforced at the write seam, not by faking
    # every lint finding's class into "propose").
    from app.curation.findings import MECHANICAL_ALLOWLIST, track_for_class

    for finding in report.findings:
        assert finding.track is track_for_class(finding.finding_class)
        if finding.finding_class in MECHANICAL_ALLOWLIST:
            assert finding.track is FindingTrack.AUTO_FIX
        else:
            assert finding.track is FindingTrack.PROPOSE


def test_missing_uuid_is_advisory_only(fixture_vault: Path) -> None:
    """A note missing ``uuid`` still gets a full report and is never a processing gate."""
    report = run_vault_lint(fixture_vault)

    # The report generation itself succeeded (no exception) and covered every
    # note, including the uuid-less one.
    assert report.notes_scanned == 10
    scanned_evidence = {e for f in report.findings for e in f.evidence}
    assert "no-uuid-note.md" in scanned_evidence

    # The missing-uuid finding is present as its own (advisory) finding...
    missing_uuid_findings = [
        f for f in report.findings if f.evidence == ("no-uuid-note.md",) and "uuid absent" in f.observed
    ]
    assert len(missing_uuid_findings) == 1
    assert missing_uuid_findings[0].track is FindingTrack.PROPOSE

    # ...and it does not block the write of the report note.
    guard = _allow_all_guard()
    report_path = write_lint_report(report, vault_root=fixture_vault, write_guard=guard)
    assert report_path.exists()
    assert "no-uuid-note.md" in report_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Idempotent rerun
# ---------------------------------------------------------------------------


def test_idempotent_rerun_same_finding_ids_and_no_duplicate_report_entries(
    fixture_vault: Path,
) -> None:
    """Running the lint pass twice over an unchanged vault is a provable no-op."""
    report_1 = run_vault_lint(fixture_vault)
    report_2 = run_vault_lint(fixture_vault)

    ids_1 = [f.finding_id for f in report_1.findings]
    ids_2 = [f.finding_id for f in report_2.findings]
    assert ids_1 == ids_2
    assert len(ids_1) == len(set(ids_1)), "no duplicate finding ids within a single pass"

    guard = _allow_all_guard()
    path_1 = write_lint_report(report_1, vault_root=fixture_vault, write_guard=guard)
    content_1 = path_1.read_text(encoding="utf-8")
    path_2 = write_lint_report(report_2, vault_root=fixture_vault, write_guard=guard)
    content_2 = path_2.read_text(encoding="utf-8")

    assert path_1 == path_2

    def _strip_generated_at(text: str) -> str:
        return "\n".join(line for line in text.splitlines() if not line.startswith("- Generated at:"))

    # Content is identical modulo the "Generated at" wall-clock stamp: the
    # rerun overwrites the same fixed-path report (never appends), and every
    # finding heading (keyed by finding_id) appears exactly once.
    assert _strip_generated_at(content_1) == _strip_generated_at(content_2), (
        "rerun over an unchanged vault must not duplicate report entries"
    )
    for finding_id in ids_1:
        heading = f"### {finding_id[:12]}"
        assert content_2.count(heading) == 1, f"finding {finding_id} must appear exactly once, not duplicated"


def test_render_lint_report_is_deterministic(fixture_vault: Path) -> None:
    report = run_vault_lint(fixture_vault)
    assert render_lint_report(report) == render_lint_report(report)


# ---------------------------------------------------------------------------
# WriteGuard enforcement at the production call site (negative path)
# ---------------------------------------------------------------------------


def test_write_lint_report_blocked_by_write_guard(fixture_vault: Path) -> None:
    """A blocked WriteGuard raises loudly before any report file is written."""
    report = run_vault_lint(fixture_vault)
    guard = _blocking_guard()

    with pytest.raises(WritesBlockedError):
        write_lint_report(report, vault_root=fixture_vault, write_guard=guard)

    from app.vault.paths import resolve_vault_system_dir_rel_or_default

    system_dir_rel = resolve_vault_system_dir_rel_or_default(fixture_vault)
    report_dir = fixture_vault / system_dir_rel / "curation"
    assert not report_dir.exists(), "a blocked guard must prevent any partial write"


def test_write_lint_report_asserts_the_named_action(fixture_vault: Path) -> None:
    """The write seam asserts the named, auditable lint-report action."""
    report = run_vault_lint(fixture_vault)
    seen: list[str] = []

    def _recording_snapshot() -> dict:
        return {"state": "healthy", "reason": None}

    guard = WriteGuard(snapshot_fn=_recording_snapshot)
    original_assert = guard.assert_writes_allowed

    def _recording_assert(action: str) -> None:
        seen.append(action)
        original_assert(action)

    guard.assert_writes_allowed = _recording_assert  # type: ignore[method-assign]
    write_lint_report(report, vault_root=fixture_vault, write_guard=guard)
    assert seen == [LINT_REPORT_WRITE_ACTION]


def test_no_note_body_writes_beyond_the_report_note(fixture_vault: Path) -> None:
    """Running the lint pass never mutates any source note body (propose-only)."""
    before = {
        p.relative_to(fixture_vault).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(fixture_vault.rglob("*.md"))
    }
    report = run_vault_lint(fixture_vault)
    write_lint_report(report, vault_root=fixture_vault, write_guard=_allow_all_guard())

    for rel_path, original_content in before.items():
        current = (fixture_vault / rel_path).read_text(encoding="utf-8")
        assert current == original_content, f"{rel_path} body must be unchanged by the lint pass"
