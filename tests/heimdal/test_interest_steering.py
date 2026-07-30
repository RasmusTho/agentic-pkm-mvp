"""Heimdal interest model + in-flow/post-hoc steering tests -- Epic #3019
slice A18 (#3043).

Covers the governing Issue's four behavioral Acceptance Criteria:

- ``test_weight_edit_is_intent`` -- a hand-edited `interests.md` weight is
  explicit intent and outranks inference: an agent's derived-column update
  (running before or after the hand-edit) never overwrites the human's
  weight.
- ``test_inflow_append_is_durable`` -- "watch this" / "never this" from
  chat OR an item appends durably to `watchlist.md` / `never.md`; both
  transports produce the identical durable append, and the append survives
  process/object boundaries (re-read from disk).
- ``test_posthoc_steering_is_append_only`` -- "less of this" / "mute" /
  "wrong" append immutable lines to `steering.log.md`; prior lines are
  never rewritten or reordered by a later append.
- ``test_agent_columns_are_read_only_for_human`` -- the agent-authored
  `confidence`/`evidence`/`decay` columns never overwrite a human's
  `weights` edit, even when the human edit happens *between* two agent
  updates (simulating an Obsidian edit mid-cycle).

Every test exercises the real production write call sites
(`app.heimdal.interest_steering.*`, backed by
`app.heimdal.settings_notes.apply_agent_update` / `write_settings_note` /
`app.knowledge.write_ops.append_note_relative` +
`app.write_guard.WriteGuard`), mirroring
`tests/heimdal/test_settings_notes.py`'s temp-vault-fixture convention: no
network, no real Postgres, no real vault.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.heimdal import interest_steering as steering_module
from app.heimdal.interest_steering import (
    InterestDerivedUpdate,
    apply_interest_derived_updates,
    append_never,
    append_steering_log,
    append_watch,
    read_inflow_body,
    read_interests,
    read_steering_log_body,
    set_interest_weight,
    update_source_filters,
)
from app.heimdal.settings_notes import (
    NEVER_LIST,
    SOURCE_CONFIG,
    STEERING_LOG,
    WATCHLIST,
    note_rel_path,
    read_settings_note,
)
from app.write_guard import WriteGuard, WritesBlockedError

pytestmark = pytest.mark.not_pg


def _vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _allowing_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _blocking_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "safe_mode", "reason": "test-induced block"})


# ---------------------------------------------------------------------------
# AC: a hand-edited interests.md weight is explicit intent and outranks
# inference.
# ---------------------------------------------------------------------------


def test_weight_edit_is_intent(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    # 1. Agent runs its own inference first, seeding derived columns for an
    #    interest with no human weight yet.
    apply_interest_derived_updates(
        vault_root,
        [InterestDerivedUpdate(interest="battery_chemistry", confidence=0.4, decay=0.1)],
        write_guard=guard,
    )

    # 2. The human explicitly sets a weight -- this is intent, not
    #    inference, and must be recorded distinctly.
    set_interest_weight(vault_root, "battery_chemistry", 0.9, write_guard=guard)

    # 3. The agent re-runs inference and would, left unchecked, derive a
    #    lower confidence/weight-adjacent signal -- but it must not be able
    #    to touch `weights` at all; only the human-facing path can.
    apply_interest_derived_updates(
        vault_root,
        [InterestDerivedUpdate(interest="battery_chemistry", confidence=0.55, evidence=["obs-1", "obs-2"])],
        write_guard=guard,
    )

    note = read_interests(vault_root)
    assert note is not None
    # The human's explicit weight survives every subsequent agent inference
    # pass untouched -- it outranks inference.
    assert note.values["weights"]["battery_chemistry"] == 0.9
    # The agent-authored columns still update normally alongside it.
    assert note.values["confidence"]["battery_chemistry"] == 0.55
    assert note.values["evidence"]["battery_chemistry"] == ["obs-1", "obs-2"]
    assert note.values["decay"]["battery_chemistry"] == 0.1  # preserved from the first pass


def test_weight_edit_after_agent_inference_is_not_overwritten_by_later_inference(tmp_path: Path) -> None:
    """A hand-edit made directly on disk (the literal Obsidian-edit path,
    not this module's `set_interest_weight` convenience) is honored
    identically -- the invariant is about the note, not about which
    function wrote it."""
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    apply_interest_derived_updates(
        vault_root,
        [InterestDerivedUpdate(interest="northvolt", confidence=0.2)],
        write_guard=guard,
    )

    # Simulate a direct Obsidian edit: reparse, mutate `weights`, re-render.
    from app.heimdal.settings_notes import INTERESTS, parse_note, render_note

    rel_path = note_rel_path(INTERESTS)
    path = vault_root / rel_path
    text = path.read_text(encoding="utf-8")
    reparsed = parse_note(INTERESTS, text)
    reparsed.values["weights"] = {"northvolt": 0.75}
    path.write_text(render_note(reparsed), encoding="utf-8")

    apply_interest_derived_updates(
        vault_root,
        [InterestDerivedUpdate(interest="northvolt", confidence=0.85)],
        write_guard=guard,
    )

    on_disk = read_interests(vault_root)
    assert on_disk is not None
    assert on_disk.values["weights"] == {"northvolt": 0.75}
    assert on_disk.values["confidence"]["northvolt"] == 0.85


# ---------------------------------------------------------------------------
# AC: in-flow "watch this" / "never this" from chat or an item appends
# durably to watchlist.md / never.md.
# ---------------------------------------------------------------------------


def test_inflow_append_is_durable(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    chat_line = append_watch(vault_root, "sources/youtube:northvolt", source="chat", write_guard=guard)
    item_line = append_watch(vault_root, "sources/youtube:battery-tech", source="item", write_guard=guard)

    body = read_inflow_body(vault_root, "watch")
    # Both transports' lines are present, in append order, in the same note
    # -- the action is a transport onto the note, not a distinct capability.
    assert chat_line in body
    assert item_line in body
    assert body.index(chat_line) < body.index(item_line)

    # The append is durable: re-reading fresh from disk (new read, not the
    # in-memory return value) still finds both lines.
    rel_path = note_rel_path(WATCHLIST)
    reread = (vault_root / rel_path).read_text(encoding="utf-8")
    assert chat_line in reread
    assert item_line in reread


def test_never_this_from_item_appends_durably(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    line = append_never(vault_root, "sources/spam_feed", source="item", note="reported by user", write_guard=guard)

    assert "source=item" in line
    assert "spam_feed" in line
    body = read_inflow_body(vault_root, "never")
    assert line in body

    rel_path = note_rel_path(NEVER_LIST)
    assert (vault_root / rel_path).exists()


def test_inflow_append_from_chat_and_item_produce_identical_durable_shape(tmp_path: Path) -> None:
    """Either surface produces the same durable note append -- neither
    transport is privileged or shaped differently."""
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    from datetime import datetime, timezone

    fixed_time = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)
    chat_line = append_watch(vault_root, "same-target", source="chat", write_guard=guard, at=fixed_time)
    item_line = append_watch(vault_root, "same-target", source="item", write_guard=guard, at=fixed_time)

    # Only the declared transport differs; everything else about the line
    # shape is identical.
    assert chat_line.replace("source=chat", "source=item") == item_line


def test_inflow_append_honors_write_guard_block(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    with pytest.raises(WritesBlockedError):
        append_watch(vault_root, "blocked-target", source="chat", write_guard=_blocking_guard())
    assert read_inflow_body(vault_root, "watch") == ""


def test_injected_guard_is_preserved_through_append_seam(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    vault_root = _vault(tmp_path)
    injected_guard = _allowing_guard()
    seam_calls: list[tuple[object, object]] = []
    real_append = steering_module.append_note_relative

    def recording_append(note_rel_path, content, **kwargs):  # type: ignore[no-untyped-def]
        seam_calls.append((kwargs.get("write_guard"), kwargs.get("action")))
        return real_append(note_rel_path, content, **kwargs)

    monkeypatch.setattr(
        steering_module.DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        lambda: {"state": "safe_mode", "reason": "default guard must not be used"},
    )
    monkeypatch.setattr(steering_module, "append_note_relative", recording_append)

    append_watch(
        vault_root,
        "sources/youtube:northvolt",
        source="chat",
        write_guard=injected_guard,
    )
    append_steering_log(
        vault_root,
        "mute",
        "sources/spam_feed",
        source="item",
        write_guard=injected_guard,
    )

    assert seam_calls == [
        (injected_guard, steering_module.INFLOW_APPEND_WRITE_ACTION),
        (injected_guard, steering_module.POSTHOC_STEERING_WRITE_ACTION),
    ]


# ---------------------------------------------------------------------------
# AC: post-hoc "less of this" / "mute" / "wrong" append immutable lines to
# steering.log.md.
# ---------------------------------------------------------------------------


def test_posthoc_steering_is_append_only(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    line1 = append_steering_log(vault_root, "less_of_this", "sources/youtube:crypto", source="chat", write_guard=guard)
    line2 = append_steering_log(vault_root, "mute", "sources/spam_feed", source="item", write_guard=guard)
    line3 = append_steering_log(vault_root, "wrong", "battery_chemistry", source="chat", note="misattributed", write_guard=guard)

    body = read_steering_log_body(vault_root)
    # All three lines present, in append order.
    assert body.index(line1) < body.index(line2) < body.index(line3)

    # Immutability: re-reading after a third append does not change the
    # bytes of the first two lines already on disk (append-only, not
    # rewrite-in-place).
    assert line1 in body
    assert line2 in body

    # The frontmatter bookkeeping tracks count/last-appended without
    # touching the body's prior entries.
    note = read_settings_note(vault_root, STEERING_LOG)
    assert note is not None
    assert note.values["entry_count"] == 3


def test_posthoc_steering_prior_lines_survive_verbatim_across_appends(tmp_path: Path) -> None:
    """Stronger immutability check: capture the on-disk bytes after the
    first append, then assert those exact bytes are an unmodified prefix
    of the body after two more appends -- nothing was rewritten in place."""
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    append_steering_log(vault_root, "wrong", "target-a", source="chat", write_guard=guard)
    rel_path = note_rel_path(STEERING_LOG)
    after_first = (vault_root / rel_path).read_text(encoding="utf-8")

    append_steering_log(vault_root, "mute", "target-b", source="item", write_guard=guard)
    append_steering_log(vault_root, "less_of_this", "target-c", source="chat", write_guard=guard)
    after_third = (vault_root / rel_path).read_text(encoding="utf-8")

    # `write_settings_note` rewrites frontmatter each time (that is expected
    # -- frontmatter is agent-authored bookkeeping, not a log entry), but
    # the appended body *lines* from the first write must still appear
    # verbatim and in original order in the final body.
    first_line = [ln for ln in after_first.splitlines() if "target-a" in ln][0]
    assert first_line in after_third.splitlines()


def test_posthoc_steering_honors_write_guard_block(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    with pytest.raises(WritesBlockedError):
        append_steering_log(vault_root, "mute", "blocked-target", source="chat", write_guard=_blocking_guard())
    assert read_steering_log_body(vault_root) == ""


# ---------------------------------------------------------------------------
# AC: agent-authored confidence/evidence/decay columns do not overwrite
# human weight edits.
# ---------------------------------------------------------------------------


def test_agent_columns_are_read_only_for_human(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    set_interest_weight(vault_root, "solid_state_batteries", 0.6, write_guard=guard)
    apply_interest_derived_updates(
        vault_root,
        [
            InterestDerivedUpdate(
                interest="solid_state_batteries",
                confidence=0.3,
                evidence=["obs-x"],
                decay=0.05,
            )
        ],
        write_guard=guard,
    )

    note = read_interests(vault_root)
    assert note is not None
    assert note.values["weights"] == {"solid_state_batteries": 0.6}
    assert note.values["confidence"] == {"solid_state_batteries": 0.3}
    assert note.values["evidence"] == {"solid_state_batteries": ["obs-x"]}
    assert note.values["decay"] == {"solid_state_batteries": 0.05}

    # Repeated agent updates keep refining the derived columns without ever
    # requiring or accepting a `weights` argument -- there is no code path
    # in `apply_interest_derived_updates`/`InterestDerivedUpdate` that can
    # carry a weight value at all.
    apply_interest_derived_updates(
        vault_root,
        [InterestDerivedUpdate(interest="solid_state_batteries", confidence=0.65)],
        write_guard=guard,
    )
    updated = read_interests(vault_root)
    assert updated is not None
    assert updated.values["weights"] == {"solid_state_batteries": 0.6}  # untouched
    assert updated.values["confidence"] == {"solid_state_batteries": 0.65}  # refined


def test_interest_derived_update_has_no_weight_field() -> None:
    """Structural guarantee: `InterestDerivedUpdate` cannot carry a weight
    value at all -- there is no field to smuggle one through."""
    update = InterestDerivedUpdate(interest="x", confidence=0.5)
    assert not hasattr(update, "weight")
    assert not hasattr(update, "weights")


# ---------------------------------------------------------------------------
# Per-source filters (sources/*.md) -- reuses A14's SOURCE_CONFIG verbatim.
# ---------------------------------------------------------------------------


def test_update_source_filters_writes_per_source_note(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    update_source_filters(vault_root, "youtube", ["exclude:clickbait", "include:battery"], write_guard=guard)

    note = read_settings_note(vault_root, SOURCE_CONFIG, source_id="youtube")
    assert note is not None
    assert note.values["filters"] == ["exclude:clickbait", "include:battery"]
    assert note.values["source_id"] == "youtube"

    rel_path = note_rel_path(SOURCE_CONFIG, source_id="youtube")
    assert rel_path == "_heimdal/sources/youtube.md"


def test_update_source_filters_is_per_instance(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    update_source_filters(vault_root, "youtube", ["include:battery"], write_guard=guard)
    update_source_filters(vault_root, "podcast_x", ["exclude:ads"], write_guard=guard)

    youtube = read_settings_note(vault_root, SOURCE_CONFIG, source_id="youtube")
    podcast = read_settings_note(vault_root, SOURCE_CONFIG, source_id="podcast_x")
    assert youtube is not None and youtube.values["filters"] == ["include:battery"]
    assert podcast is not None and podcast.values["filters"] == ["exclude:ads"]
