"""Attention view tests -- Epic #3019 slice A16 (J6, #3036).

Covers the governing Issue's three behavioral Acceptance Criteria:

- ``test_grouped_counts_reasons_overrides_persist`` -- a batch of per-item
  attention events, folded and persisted via ``record_attention_events``,
  lands durably in ``attention/YYYY-MM-DD.md`` as grouped counts + reasons,
  and a subsequently recorded override is retained alongside them.
- ``test_firehose_is_ui_only_no_durable_rows`` -- ``iter_skip_firehose``
  yields per-item rows but writes nothing to the vault; only the grouped
  note exists on disk, never a per-item file/row.
- ``test_override_persists_to_daily_note`` -- ``record_override`` durably
  captures a human override in the daily note without disturbing the
  agent-authored counts/reasons already there.

All three exercise the real production write call site
(``record_attention_events`` / ``record_override`` ->
``app.heimdal.settings_notes.write_settings_note`` ->
``app.knowledge.write_ops.write_note_relative`` ->
``app.write_guard.WriteGuard``), mirroring
``tests/heimdal/test_settings_notes.py``'s and
``tests/heimdal/test_entity_confirm.py``'s temp-vault-fixture convention: no
network, no real Postgres, no real vault.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.heimdal.attention_log import (
    DECISION_ATTENDED,
    DECISION_SKIPPED,
    AttentionEvent,
    AttentionLogError,
    AttentionOverride,
    FirehoseRow,
    fold_day_summary,
    iter_skip_firehose,
    read_day_summary,
    record_attention_events,
    record_override,
)
from app.heimdal.settings_notes import DEFAULT_SETTINGS_DIR, note_rel_path, ATTENTION_DAY
from app.write_guard import WriteGuard, WritesBlockedError

pytestmark = pytest.mark.not_pg


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _allowing_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _blocking_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "safe_mode", "reason": "test-induced block"})


DAY = "2026-07-06"


def _events() -> list[AttentionEvent]:
    return [
        AttentionEvent(item_id="item-1", decision=DECISION_SKIPPED, reason="low_relevance"),
        AttentionEvent(item_id="item-2", decision=DECISION_SKIPPED, reason="low_relevance"),
        AttentionEvent(item_id="item-3", decision=DECISION_SKIPPED, reason="duplicate"),
        AttentionEvent(item_id="item-4", decision=DECISION_ATTENDED, reason="high_interest"),
    ]


# ---------------------------------------------------------------------------
# AC1: grouped counts/reasons/overrides all persist to the daily note.
# ---------------------------------------------------------------------------


def test_grouped_counts_reasons_overrides_persist(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    summary = record_attention_events(vault_root, DAY, _events(), write_guard=guard)

    # Grouped counts are keyed decision:reason and correctly tallied.
    assert summary.counts == {
        "skipped:low_relevance": 2,
        "skipped:duplicate": 1,
        "attended:high_interest": 1,
    }
    assert tuple(summary.reasons) == ("duplicate", "high_interest", "low_relevance")
    assert tuple(summary.overrides) == ()

    # Now record a human override; it must layer onto the same note without
    # disturbing the already-persisted grouped counts/reasons.
    override = AttentionOverride(
        item_id="item-1",
        original_decision=DECISION_SKIPPED,
        overridden_decision=DECISION_ATTENDED,
        note="actually relevant, keep it",
    )
    after_override = record_override(vault_root, DAY, override, write_guard=guard)

    assert after_override.counts == summary.counts
    assert after_override.reasons == summary.reasons
    assert len(after_override.overrides) == 1
    assert after_override.overrides[0]["item_id"] == "item-1"
    assert after_override.overrides[0]["overridden_decision"] == DECISION_ATTENDED

    # Durable: a fresh read off disk reflects everything (real production
    # read path, not just the in-memory return values).
    reread = read_day_summary(vault_root, DAY)
    assert reread is not None
    assert reread.counts == summary.counts
    assert tuple(reread.reasons) == tuple(summary.reasons)
    assert len(reread.overrides) == 1
    assert reread.overrides[0]["item_id"] == "item-1"

    # The note actually exists at the deterministic ADR/A14-declared path.
    rel_path = note_rel_path(ATTENTION_DAY, settings_dir=DEFAULT_SETTINGS_DIR, date=DAY)
    assert (vault_root / rel_path).exists()
    assert rel_path == "_heimdal/attention/2026-07-06.md"


def test_record_attention_events_honors_write_guard_block(tmp_path: Path) -> None:
    """The governed write seam is real, not decorative (mirrors
    `test_settings_notes.test_write_settings_note_honors_write_guard_block`):
    a blocked WriteGuard prevents the grouped write entirely, fail-loud."""
    vault_root = _vault(tmp_path)
    with pytest.raises(WritesBlockedError):
        record_attention_events(vault_root, DAY, _events(), write_guard=_blocking_guard())
    assert read_day_summary(vault_root, DAY) is None


def test_fold_day_summary_is_pure_and_matches_persisted_result(tmp_path: Path) -> None:
    """`fold_day_summary` (the in-memory fold) and `record_attention_events`
    (fold + persist) agree exactly -- persistence never silently transforms
    the grouped shape."""
    folded = fold_day_summary(DAY, _events())
    persisted = record_attention_events(_vault(tmp_path), DAY, _events(), write_guard=_allowing_guard())
    assert dict(folded.counts) == dict(persisted.counts)
    assert tuple(folded.reasons) == tuple(persisted.reasons)


# ---------------------------------------------------------------------------
# AC2: the item-level firehose is UI-only -- no durable per-item rows.
# ---------------------------------------------------------------------------


def test_firehose_is_ui_only_no_durable_rows(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    events = _events()

    # The firehose yields one row per item -- full per-item detail is
    # available to a UI lens.
    rows = list(iter_skip_firehose(events))
    assert len(rows) == len(events)
    assert all(isinstance(row, FirehoseRow) for row in rows)
    assert {row.item_id for row in rows} == {"item-1", "item-2", "item-3", "item-4"}

    # But nothing was written to the vault by consuming the firehose -- no
    # vault directory was even created, let alone a per-item file/row.
    assert not vault_root.exists() or list(vault_root.iterdir()) == []

    # Only after the grouped call persists do we get exactly ONE note for the
    # day -- never one artifact per item. The whole `_heimdal/attention/`
    # directory contains a single file for this day, not `len(events)` files.
    record_attention_events(vault_root, DAY, events, write_guard=_allowing_guard())
    attention_dir = vault_root / "_heimdal" / "attention"
    written_files = list(attention_dir.iterdir())
    assert len(written_files) == 1
    assert written_files[0].name == f"{DAY}.md"

    # The durable note's rendered content carries grouped counts, not raw
    # per-item rows -- item ids never leak into the persisted note.
    content = written_files[0].read_text(encoding="utf-8")
    for event in events:
        assert event.item_id not in content


def test_iter_skip_firehose_is_pure_generator_no_vault_args() -> None:
    """Structural guarantee: the firehose function signature takes no
    vault_root/VaultContext/WriteGuard at all -- it cannot write even if a
    caller wanted it to. This pins the declared-bend boundary at the type
    level, not just by behavioral absence of files."""
    import inspect

    sig = inspect.signature(iter_skip_firehose)
    param_names = set(sig.parameters)
    assert param_names == {"events"}


# ---------------------------------------------------------------------------
# AC3: a human override persists durably to the daily note.
# ---------------------------------------------------------------------------


def test_override_persists_to_daily_note(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    # Seed the day with an agent-authored grouped fold first (the common
    # real-world order: agent skips things, human reviews/overrides after).
    record_attention_events(vault_root, DAY, _events(), write_guard=guard)

    override = AttentionOverride(
        item_id="item-3",
        original_decision=DECISION_SKIPPED,
        overridden_decision=DECISION_ATTENDED,
        note="this was actually relevant",
    )
    record_override(vault_root, DAY, override, write_guard=guard)

    reread = read_day_summary(vault_root, DAY)
    assert reread is not None
    assert len(reread.overrides) == 1
    persisted = reread.overrides[0]
    assert persisted["item_id"] == "item-3"
    assert persisted["original_decision"] == DECISION_SKIPPED
    assert persisted["overridden_decision"] == DECISION_ATTENDED
    assert persisted["note"] == "this was actually relevant"

    # Agent-authored counts/reasons from the earlier fold are untouched.
    assert reread.counts["skipped:duplicate"] == 1


def test_override_on_a_day_with_no_prior_agent_fold(tmp_path: Path) -> None:
    """An override can be the FIRST write of the day (human catches
    something before any agent fold ran) -- record_override must not require
    a pre-existing note."""
    vault_root = _vault(tmp_path)
    override = AttentionOverride(
        item_id="item-9",
        original_decision=DECISION_SKIPPED,
        overridden_decision=DECISION_ATTENDED,
    )
    summary = record_override(vault_root, DAY, override, write_guard=_allowing_guard())
    assert summary.counts == {}
    assert len(summary.overrides) == 1


def test_override_is_idempotent_on_exact_duplicate(tmp_path: Path) -> None:
    """Replaying the exact same override does not duplicate the entry --
    mirrors the idempotent-write discipline used across the Heimdal write
    call sites (e.g. `candidate_projection.write_candidate_note`)."""
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    override = AttentionOverride(
        item_id="item-1",
        original_decision=DECISION_SKIPPED,
        overridden_decision=DECISION_ATTENDED,
        note="dup check",
        overridden_at="2026-07-06T12:00:00Z",
    )
    record_override(vault_root, DAY, override, write_guard=guard)
    summary = record_override(vault_root, DAY, override, write_guard=guard)
    assert len(summary.overrides) == 1


def test_record_override_honors_write_guard_block(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    override = AttentionOverride(
        item_id="item-1",
        original_decision=DECISION_SKIPPED,
        overridden_decision=DECISION_ATTENDED,
    )
    with pytest.raises(WritesBlockedError):
        record_override(vault_root, DAY, override, write_guard=_blocking_guard())
    assert read_day_summary(vault_root, DAY) is None


# ---------------------------------------------------------------------------
# Validation / completeness
# ---------------------------------------------------------------------------


def test_attention_event_rejects_invalid_decision() -> None:
    with pytest.raises(AttentionLogError):
        AttentionEvent(item_id="x", decision="ignored", reason="whatever")


def test_attention_event_rejects_empty_reason() -> None:
    with pytest.raises(AttentionLogError):
        AttentionEvent(item_id="x", decision=DECISION_SKIPPED, reason="   ")


def test_attention_override_rejects_invalid_decisions() -> None:
    with pytest.raises(AttentionLogError):
        AttentionOverride(item_id="x", original_decision="bogus", overridden_decision=DECISION_ATTENDED)
    with pytest.raises(AttentionLogError):
        AttentionOverride(item_id="x", original_decision=DECISION_SKIPPED, overridden_decision="bogus")


def test_read_day_summary_returns_none_when_absent(tmp_path: Path) -> None:
    assert read_day_summary(_vault(tmp_path), DAY) is None


def test_no_events_folds_to_empty_summary(tmp_path: Path) -> None:
    summary = record_attention_events(_vault(tmp_path), DAY, [], write_guard=_allowing_guard())
    assert summary.counts == {}
    assert tuple(summary.reasons) == ()
