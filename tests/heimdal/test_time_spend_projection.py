"""SCREEN-05 (#3345): the rebuildable time-spend projection over screen spans.

Acceptance criteria under test (issue #3345 / PROJECT_TIME_SPEND_ANALYSIS.md):

- AC1 ``test_rollup_by_all_axes``: spans roll up by app / project / scope /
  day / week with correct duration sums; idle gaps (time between spans) are
  never counted.
- AC2 ``test_time_spend_rebuilds_from_observations``: the projection is a
  deterministic pure fold of the observation stream -- same observations in,
  byte-identical markdown out; an "incremental" rebuild after more
  observations arrive equals a from-scratch rebuild over the same stream
  (there is no hidden state to diverge).
- AC3 ``test_projection_written_governed_derived_class``: the markdown note
  is written through the governed WriteGuard path with the derived /
  ``requires_review`` posture and never overwrites a human-authored note.

Every publishing step goes through the production observation publish path
(`assemble_observation_payload` + `publish_full_observation`, the exact call
site `app.heimdal.screen_derivation._publish_span` uses), and every
enforcement assertion drives the production rebuild entrypoint
(`rebuild_time_spend`), not an isolated helper.

Per-span identity (KD-FBDBDAD4C052): spans here deliberately share one
``episode_id`` in several tests -- the rollup must keep them distinct, which
is the recorded workaround for the candidate projector's episode fold defect.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.heimdal.cursor_store import reset_memory_cursor_store
from app.heimdal.observation_log import (
    read_observations_from,
    reset_memory_observation_log,
)
from app.heimdal.publish import (
    assemble_observation_payload,
    publish_full_observation,
)
from app.heimdal.time_spend import (
    ARTIFACT_CLASS,
    NO_PROJECT_BUCKET,
    build_time_spend_rollup,
    fold_time_spend,
    format_duration,
    rebuild_time_spend,
    render_time_spend_note,
    rollup_axes,
    time_spend_note_path,
)
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard

pytestmark = pytest.mark.not_pg

TOPIC = "heimdal.observation.published"


@pytest.fixture(autouse=True)
def _reset_heimdal_stores():
    reset_memory_observation_log()
    reset_memory_cursor_store()
    yield
    reset_memory_observation_log()
    reset_memory_cursor_store()


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


def _span_payload(
    *,
    observation_id: str,
    start: str,
    end: str,
    app: str = "Obsidian",
    scope: str = "work",
    projects: tuple[str, ...] = (),
    episode_id: str = "screen-tick-shared",
    supersedes: str | None = None,
    content_identity: str = "sha256:" + "c" * 64,
) -> dict:
    """One screen span payload shaped exactly like `screen_derivation._publish_span`'s."""
    mentions = [
        {
            "mention_id": f"screen:project:{project.lower().replace(' ', '-')}",
            "surface_form": project,
            "kind_hint": "project",
            "resolution": "unresolved",
        }
        for project in projects
    ]
    return assemble_observation_payload(
        observation_id=observation_id,
        episode_id=episode_id,
        observed_at_start=start,
        observed_at_end=end,
        clock_basis="device_metadata",
        sequence=None,
        supersedes=supersedes,
        attributions=[
            {
                "mention_id": "operator",
                "role": "recorder",
                "resolution": "resolved",
                "basis": "capture_context",
            }
        ],
        entity_mentions=mentions,
        modality="screen",
        content=f"Working in {app}",
        content_structure={
            "span": {
                "frame_count": 2,
                "dimensions": {"app": app, "window": "doc", "scope": scope, "goal": "edit"},
                "raw_refs": ["heimraw:frame-1"],
            }
        },
        raw_ref="heimraw:frame-1",
        confidence={
            "attribution": {"score": 1.0, "calibration": "by_construction"},
            "activity_summary": {"score": 0.8, "calibration": "heuristic"},
        },
        provenance={
            "sensor": {"adapter": "macos_observer", "version": "v1", "machine": "mac-1"},
            "capture_chain": ["macos_observer", "screen_capture_endpoint"],
            "content_identity": content_identity,
            "stage_versions": {"screen_derivation": "test-model@v1"},
            "model_ref": "local/test-vision",
            "raw_refs": ["heimraw:frame-1"],
        },
        sensitivity="private",
        scope_hint=scope,
        consent={
            "basis": "self_record",
            "granted_by": "operator",
            "granted_at": "2026-01-01T00:00:00+00:00",
            "third_party": "none",
            "grant_ref": "grant-self-record-v1",
        },
    )


def _publish(payload: dict, *, stage_versions: dict | None = None) -> None:
    publish_full_observation(
        topic=TOPIC,
        payload=payload,
        source="heimdal.screen_derivation",
        stage_versions=stage_versions or payload["provenance"]["stage_versions"],
    )


def _publish_week_fixture() -> None:
    """Four spans in 2026-W28 across two days, apps, scopes, projects.

    All four share ONE episode_id (the KD-FBDBDAD4C052 shape) and carry a
    2h idle gap between the first two spans that must never be counted.
    """
    _publish(
        _span_payload(
            observation_id="screen-obs-a",
            start="2026-07-06T09:00:00+00:00",
            end="2026-07-06T09:30:00+00:00",  # 30m
            app="Obsidian",
            scope="work",
            projects=("ERE spec",),
            content_identity="sha256:" + "a" * 64,
        )
    )
    # 2h idle/locked gap here: never sampled, so no span covers it.
    _publish(
        _span_payload(
            observation_id="screen-obs-b",
            start="2026-07-06T11:30:00+00:00",
            end="2026-07-06T11:45:00+00:00",  # 15m
            app="Safari",
            scope="private",
            projects=(),
            content_identity="sha256:" + "b" * 64,
        )
    )
    _publish(
        _span_payload(
            observation_id="screen-obs-c",
            start="2026-07-07T10:00:00+00:00",
            end="2026-07-07T11:00:00+00:00",  # 1h, next day
            app="Obsidian",
            scope="work",
            projects=("ERE spec", "Heimdal"),
            content_identity="sha256:" + "d" * 64,
        )
    )
    _publish(
        _span_payload(
            observation_id="screen-obs-d",
            start="2026-07-07T12:00:00+00:00",
            end="2026-07-07T12:05:30+00:00",  # 5m30s
            app="Terminal",
            scope="work",
            projects=("Heimdal",),
            content_identity="sha256:" + "e" * 64,
        )
    )


# --- AC1: rollup by every axis, correct sums, idle gaps excluded --------------


def test_rollup_by_all_axes():
    _publish_week_fixture()

    rollup = build_time_spend_rollup()
    assert len(rollup.spans) == 4  # one per observation_id, despite the shared episode_id
    axes = rollup_axes(rollup.spans)

    assert axes["by_app"] == {
        "Obsidian": 90 * 60.0,
        "Safari": 15 * 60.0,
        "Terminal": 330.0,
    }
    assert axes["by_scope"] == {
        "work": 30 * 60.0 + 60 * 60.0 + 330.0,
        "private": 15 * 60.0,
    }
    # A span mentioning two projects counts fully toward each.
    assert axes["by_project"] == {
        "ERE spec": 30 * 60.0 + 60 * 60.0,
        "Heimdal": 60 * 60.0 + 330.0,
        NO_PROJECT_BUCKET: 15 * 60.0,
    }
    assert axes["by_day"] == {
        "2026-07-06": 45 * 60.0,
        "2026-07-07": 60 * 60.0 + 330.0,
    }
    assert axes["by_week"] == {"2026-W28": 45 * 60.0 + 60 * 60.0 + 330.0}

    # Idle gaps excluded: total is the sum of span windows, NOT the wall-clock
    # extent of the observed period (which includes the 2h gap).
    total = sum(span.duration_seconds for span in rollup.spans)
    assert total == 45 * 60.0 + 60 * 60.0 + 330.0
    wall_clock_extent = (11.75 - 9.0) * 3600  # first day alone spans 2h45m
    assert total < wall_clock_extent + 24 * 3600  # sanity: nothing interpolated

    assert format_duration(axes["by_week"]["2026-W28"]) == "1h50m"


def test_revisions_and_corrections_do_not_double_count():
    _publish(
        _span_payload(
            observation_id="screen-obs-rev",
            start="2026-07-06T09:00:00+00:00",
            end="2026-07-06T09:30:00+00:00",
            app="Obsidian",
            content_identity="sha256:" + "a" * 64,
        )
    )
    # A revision of the SAME evidence: same observation_id, new stage_versions
    # -> a new log row that must fold onto the same span, not add 30m.
    _publish(
        _span_payload(
            observation_id="screen-obs-rev",
            start="2026-07-06T09:00:00+00:00",
            end="2026-07-06T09:30:00+00:00",
            app="Obsidian",
            content_identity="sha256:" + "a" * 64,
        ),
        stage_versions={"screen_derivation": "test-model@v2"},
    )
    # A correction that supersedes a distinct earlier observation id.
    _publish(
        _span_payload(
            observation_id="screen-obs-old",
            start="2026-07-06T10:00:00+00:00",
            end="2026-07-06T10:10:00+00:00",
            app="Safari",
            content_identity="sha256:" + "b" * 64,
        )
    )
    _publish(
        _span_payload(
            observation_id="screen-obs-corrected",
            start="2026-07-06T10:00:00+00:00",
            end="2026-07-06T10:12:00+00:00",
            app="Safari",
            supersedes="screen-obs-old",
            content_identity="sha256:" + "d" * 64,
        )
    )

    rollup = build_time_spend_rollup()
    axes = rollup_axes(rollup.spans)
    assert axes["by_app"] == {"Obsidian": 30 * 60.0, "Safari": 12 * 60.0}


# --- AC2: deterministic rebuild from the observation stream alone -------------


def test_time_spend_rebuilds_from_observations(tmp_path):
    vault_a = _vault(tmp_path / "vault-a")
    guard = _allowing_guard()
    note_rel = time_spend_note_path("2026-W28")

    # Incremental shape: two spans arrive, rebuild; two more arrive, rebuild.
    _publish(
        _span_payload(
            observation_id="screen-obs-a",
            start="2026-07-06T09:00:00+00:00",
            end="2026-07-06T09:30:00+00:00",
            projects=("ERE spec",),
            content_identity="sha256:" + "a" * 64,
        )
    )
    _publish(
        _span_payload(
            observation_id="screen-obs-b",
            start="2026-07-06T11:30:00+00:00",
            end="2026-07-06T11:45:00+00:00",
            app="Safari",
            scope="private",
            content_identity="sha256:" + "b" * 64,
        )
    )
    first = rebuild_time_spend(vault_context=vault_a, write_guard=guard)
    assert first["weeks"]["2026-W28"]["status"] == "written"

    _publish(
        _span_payload(
            observation_id="screen-obs-c",
            start="2026-07-07T10:00:00+00:00",
            end="2026-07-07T11:00:00+00:00",
            projects=("ERE spec", "Heimdal"),
            content_identity="sha256:" + "d" * 64,
        )
    )
    _publish(
        _span_payload(
            observation_id="screen-obs-d",
            start="2026-07-07T12:00:00+00:00",
            end="2026-07-07T12:05:30+00:00",
            app="Terminal",
            projects=("Heimdal",),
            content_identity="sha256:" + "e" * 64,
        )
    )
    second = rebuild_time_spend(vault_context=vault_a, write_guard=guard)
    assert second["weeks"]["2026-W28"]["status"] == "rebuilt"
    incremental_bytes = (Path(vault_a.active_vault_path or "") / note_rel).read_text(
        encoding="utf-8"
    )

    # From-scratch shape: a FRESH log receives the same four observations in
    # one go; a fresh vault gets one rebuild. Same observations -> the
    # projection must be byte-identical. No cursor, no run counter, no
    # wall-clock stamp may leak in.
    reset_memory_observation_log()
    reset_memory_cursor_store()
    _publish_week_fixture()
    vault_b = _vault(tmp_path / "vault-b")
    scratch = rebuild_time_spend(vault_context=vault_b, write_guard=guard)
    assert scratch["weeks"]["2026-W28"]["status"] == "written"
    scratch_bytes = (Path(vault_b.active_vault_path or "") / note_rel).read_text(
        encoding="utf-8"
    )

    assert scratch_bytes == incremental_bytes

    # And the fold itself is a pure function: same rows, same rollup/markdown.
    rows = read_observations_from(0)
    assert render_time_spend_note("2026-W28", fold_time_spend(rows)) == render_time_spend_note(
        "2026-W28", fold_time_spend(rows)
    )

    # Re-running with no new observations is a no-op, not a new artifact.
    third = rebuild_time_spend(vault_context=vault_b, write_guard=guard)
    assert third["weeks"]["2026-W28"]["status"] == "unchanged"


# --- AC3: governed write, derived class, never over a human note --------------


def test_projection_written_governed_derived_class(tmp_path):
    _publish_week_fixture()
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path or "")
    note_rel = time_spend_note_path("2026-W28")
    note_path = vault_root / note_rel

    # A blocked WriteGuard stops the PRODUCTION rebuild path before any write.
    blocked = rebuild_time_spend(vault_context=vault, write_guard=_blocking_guard())
    assert blocked["weeks"]["2026-W28"]["status"] == "blocked"
    assert not note_path.exists()

    # An allowed write lands with the derived / requires_review posture.
    written = rebuild_time_spend(vault_context=vault, write_guard=_allowing_guard())
    assert written["weeks"]["2026-W28"]["status"] == "written"
    content = note_path.read_text(encoding="utf-8")
    assert f"artifact_class: {ARTIFACT_CLASS}" in content
    assert "requires_review: true" in content
    assert "source_authoritative: false" in content
    assert "ai_generated: true" in content
    assert "rebuildable: true" in content

    # Rebuilding OVER its own projection is allowed (the note is disposable)...
    _publish(
        _span_payload(
            observation_id="screen-obs-extra",
            start="2026-07-08T09:00:00+00:00",
            end="2026-07-08T09:10:00+00:00",
            content_identity="sha256:" + "f" * 64,
        )
    )
    rebuilt = rebuild_time_spend(vault_context=vault, write_guard=_allowing_guard())
    assert rebuilt["weeks"]["2026-W28"]["status"] == "rebuilt"

    # ...but a human-authored note at the target path is NEVER overwritten,
    # even through the production rebuild entrypoint.
    human_text = "# My own week notes\n\nHand-written; hands off.\n"
    note_path.write_text(human_text, encoding="utf-8")
    guarded = rebuild_time_spend(vault_context=vault, write_guard=_allowing_guard())
    assert guarded["weeks"]["2026-W28"]["status"] == "blocked"
    assert "refusing to overwrite" in (guarded["weeks"]["2026-W28"]["reason"] or "")
    assert note_path.read_text(encoding="utf-8") == human_text

    # A frontmatter-bearing note that claims authority is not ours either.
    pretender = (
        "---\nartifact_class: time_spend_projection\nauthority:\n"
        "  ai_generated: false\n  source_authoritative: true\n  requires_review: false\n---\n\nbody\n"
    )
    note_path.write_text(pretender, encoding="utf-8")
    guarded_again = rebuild_time_spend(vault_context=vault, write_guard=_allowing_guard())
    assert guarded_again["weeks"]["2026-W28"]["status"] == "blocked"
    assert note_path.read_text(encoding="utf-8") == pretender


def test_rebuild_requires_selected_vault():
    _publish_week_fixture()
    from app.heimdal.time_spend import TimeSpendProjectionError

    with pytest.raises(TimeSpendProjectionError):
        rebuild_time_spend(
            vault_context=VaultContext(status="uninitialized"),
            write_guard=_allowing_guard(),
        )


def test_week_filter_and_missing_week(tmp_path):
    _publish_week_fixture()
    vault = _vault(tmp_path / "vault")
    receipt = rebuild_time_spend(
        vault_context=vault, write_guard=_allowing_guard(), week="2026-W29"
    )
    assert receipt["weeks"] == {
        "2026-W29": {"status": "no_observations", "artifact_path": None, "reason": None}
    }
    assert not (Path(vault.active_vault_path or "") / time_spend_note_path("2026-W29")).exists()
