"""Calendar Stream Adapter tests (ERE-09, #3184).

Spec: ``docs/EPISODE_RESOLUTION_ENGINE/CALENDAR_STREAM_ADAPTER.md``. Covers
the governing Issue's Acceptance Criteria (the coordinator-resolved
architecture fork on AC3 is documented inline at that test):

- ``test_calendar_entries_normalize_to_signal_contract`` (AC1): a parsed ICS
  VEVENT normalizes to a schema-valid ``SignalContract`` (bitemporal,
  per-dimension confidence, provenance UID+etag) AND to the segmentation-
  internal ``SegmentationSignal`` the tick actually folds.
- ``test_attendees_resolved_provisionally_heim6`` (AC2): three-state
  attendee resolution against a read-only register snapshot, with NO
  register mutation anywhere in the path.
- ``test_calendar_joins_fusion_via_registry_only`` (AC3, enforcement): the
  shift-detection core (`detect_shift`/`_disjoint_set_shift`/
  `fold_signals_into_segments`/the named shift constants) is unchanged, and
  calendar signals fold jointly with heimdal + vault.activity signals in the
  SAME `fold_signals_into_segments` call via the registry-driven
  `run_segmentation_tick` entrypoint (per the coordinator's #3184
  architecture-fork resolution: an additive `run_segmentation_tick`
  ingestion block is in scope; the pure core is not).
- ``test_credentials_from_private_bindings_fail_loud`` (AC4): private-
  bindings env-var credential resolution, fail-loud when unconfigured,
  reached at the real `run_segmentation_tick` call site.
- ``test_unreachable_calendar_degrades_softly`` (AC5): an unreachable
  calendar surfaces in the tick summary's `degraded` key without failing the
  tick or blocking a sibling calendar/stream.
- ``test_calendar_scope_mapping_respected`` (AC6): per-calendar scope
  mapping keeps a work-calendar signal out of a private-scope partition.

No network, no live CalDAV (Constraints: "NO live iCloud fetch in this
environment or the test suite" -- every transport here is a fake/fixture);
the live-CalDAV receipt is a mac-mini test-channel deliverable, deferred.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Sequence

import pytest

from app.episodes import segmenter
from app.episodes.calendar_stream import (
    CALENDAR_STREAM_ID,
    AttendeeAmbiguous,
    AttendeeResolved,
    AttendeeUnresolved,
    CalendarBinding,
    CalendarCredentialsError,
    CalendarRawItem,
    CalendarUnreachableError,
    RegisterEntrySnapshot,
    calendar_event_to_signal_contract,
    calendar_signal_id,
    parse_vevent,
    read_calendar_raw_items_for_tick,
    resolve_attendee_readonly,
    resolve_calendar_bindings,
)
from app.episodes.calendar_stream import _calendar_query_body, _occurrence_content_token, _parse_multistatus
from app.episodes.segmenter import _signal_from_calendar_row, fold_signals_into_segments, run_segmentation_tick
from app.episodes.stream_registry import ConfidenceScore
from app.write_guard import WriteGuard

pytestmark = pytest.mark.not_pg


def _allow_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy", "reason": None})


def _stub_assignment_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the ERE-05 assignment DB I/O that ``run_segmentation_tick`` runs after segmentation
    (ERE-05, #3180): a tick with any real signal now also assigns episode_ref bindings, which reads
    ``episodes``/``episode_artifact_binding`` and commits the diff. These calendar tests exercise
    the tick without Postgres, so the assignment reads/write are stubbed to no-ops -- mirrors
    ``tests/episodes/test_segmentation_core.py``'s tick tests. No prior persisted episodes or ledger
    rows in these fixtures."""
    monkeypatch.setattr(segmenter, "read_candidate_episodes_for_scopes", lambda scopes: [])
    monkeypatch.setattr(segmenter, "read_existing_bindings", lambda refs: {})
    monkeypatch.setattr(segmenter, "read_existing_bindings_for_episodes", lambda episode_ids: {})
    monkeypatch.setattr(
        segmenter,
        "commit_assignment_diff",
        lambda to_insert, to_correct, write_guard=None, vault_root=None: {
            "pending": len(to_insert),
            "corrected": len(to_correct),
        },
    )


def _dt(hour: int, minute: int, day: int = 11) -> datetime:
    return datetime(2026, 7, day, hour, minute, tzinfo=timezone.utc)


def _ics(
    uid: str,
    *,
    dtstart: str,
    dtend: str | None = None,
    summary: str | None = "Weekly Sync",
    location: str | None = "Conference Room A",
    attendees: Sequence[str] = (),
) -> str:
    lines = ["BEGIN:VCALENDAR", "BEGIN:VEVENT", f"UID:{uid}", f"DTSTART:{dtstart}"]
    if dtend:
        lines.append(f"DTEND:{dtend}")
    if summary is not None:
        lines.append(f"SUMMARY:{summary}")
    if location is not None:
        lines.append(f"LOCATION:{location}")
    for attendee in attendees:
        lines.append(attendee)
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"


def _binding(*, calendar_id: str = "work-cal", scope: str = "work") -> CalendarBinding:
    return CalendarBinding(
        calendar_id=calendar_id,
        base_url="https://caldav.icloud.com",
        username="operator@example.com",
        app_password="super-secret-app-password",
        calendar_path=f"/calendars/{calendar_id}/",
        scope=scope,
    )


# ---------------------------------------------------------------------------
# AC1: entries normalize to schema-valid signals
# ---------------------------------------------------------------------------


def test_calendar_entries_normalize_to_signal_contract() -> None:
    ics_text = _ics(
        "event-1",
        dtstart="20260711T090000Z",
        dtend="20260711T093000Z",
        summary="Roadmap Sync",
        location="Conference Room A",
        attendees=["ATTENDEE;CN=Alice Andersson:mailto:alice@example.com"],
    )
    event = parse_vevent(ics_text)
    assert event is not None
    assert event.uid == "event-1"
    assert event.dtstart == _dt(9, 0)
    assert event.dtend == _dt(9, 30)
    assert event.summary == "Roadmap Sync"
    assert event.location == "Conference Room A"
    assert len(event.attendees) == 1
    assert event.attendees[0].surface_form == "Alice Andersson"

    contract = calendar_event_to_signal_contract(uid="event-1", etag="etag-1", event=event, scope="work")
    assert contract.stream_id == CALENDAR_STREAM_ID
    assert contract.signal_id == "event-1:etag-1"
    assert contract.provenance_ref == "calendar:event-1:etag-1"
    # Bitemporal: observed_at_start/end are reality time, emitted_at is separate.
    assert contract.observed_at_start == "2026-07-11T09:00:00+00:00"
    assert contract.observed_at_end == "2026-07-11T09:30:00+00:00"
    assert contract.emitted_at
    # Per-dimension confidence, never a bare scalar.
    assert isinstance(contract.dimensions_fed["time"], ConfidenceScore)
    assert contract.dimensions_fed["time"].calibration == "by_construction"
    assert "protagonist" in contract.dimensions_fed  # attendees present
    assert "space" in contract.dimensions_fed  # location present
    assert "goal" in contract.dimensions_fed  # summary present
    assert contract.scope_binding is not None and contract.scope_binding.scope == "work"

    # A missing DTSTART can never normalize to a signal contract (bounds are
    # never guessed) -- DTSTART omitted from the ICS body entirely.
    no_start_event = parse_vevent(
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:event-2\r\nSUMMARY:Untimed\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    assert no_start_event is not None
    assert no_start_event.dtstart is None
    with pytest.raises(ValueError):
        calendar_event_to_signal_contract(uid="event-2", etag="etag-2", event=no_start_event, scope="work")

    # The segmentation-internal SegmentationSignal built from the same raw
    # item carries the same bitemporal bounds + provenance.
    binding = _binding()
    item = CalendarRawItem(uid="event-1", etag="etag-1", ics_text=ics_text)
    signal = _signal_from_calendar_row(binding, item, register_snapshot=())
    assert signal is not None
    assert signal.stream_id == CALENDAR_STREAM_ID
    assert signal.signal_id == "event-1:etag-1"
    assert signal.provenance_ref == "calendar:event-1:etag-1"
    assert signal.observed_at == _dt(9, 0)
    assert signal.observed_at_end == _dt(9, 30)
    assert signal.scope == "work"


# ---------------------------------------------------------------------------
# AC2: HEIM-6-honest three-state attendee resolution, no register mutation
# ---------------------------------------------------------------------------


def test_attendees_resolved_provisionally_heim6() -> None:
    known = (
        RegisterEntrySnapshot(
            entity_id="ent:alice-canonical", label="Alice Andersson", aliases=("Alice",), lifecycle="canonical"
        ),
        RegisterEntrySnapshot(
            entity_id="ent:prov:bob-a", label="Bob", aliases=(), lifecycle="provisional"
        ),
        RegisterEntrySnapshot(
            entity_id="ent:prov:bob-b", label="Bob B", aliases=("Bob",), lifecycle="provisional"
        ),
        RegisterEntrySnapshot(
            entity_id="ent:merged-away", label="Old Alice", aliases=("Alice",), lifecycle="merged"
        ),
    )

    # resolved: exactly one non-merged match.
    resolved = resolve_attendee_readonly("Alice Andersson", known_entries=known)
    assert isinstance(resolved, AttendeeResolved)
    assert resolved.entity_id == "ent:alice-canonical"
    assert resolved.confidence == 1.0

    # ambiguous: two non-merged entries share the alias "Bob" -- no winner
    # asserted (HEIM-6), and the merged "Alice" entry never resurfaces as a
    # match (merged entries are excluded, mirroring EntityRegister.resolve()).
    ambiguous = resolve_attendee_readonly("Bob", known_entries=known)
    assert isinstance(ambiguous, AttendeeAmbiguous)
    assert {c.entity_id for c in ambiguous.candidates} == {"ent:prov:bob-a", "ent:prov:bob-b"}

    # unresolved: no match at all -- a LOCAL, non-durable placeholder id,
    # never an `ent:prov:` id (this module mints nothing).
    unresolved_1 = resolve_attendee_readonly("Random Person", known_entries=known)
    unresolved_2 = resolve_attendee_readonly("Random Person", known_entries=known)
    assert isinstance(unresolved_1, AttendeeUnresolved)
    assert unresolved_1.surface_form == "Random Person"
    assert not unresolved_1.entity_id.startswith("ent:")
    assert unresolved_1.entity_id.startswith("cal:unresolved:")
    # Deterministic, so the same surface form re-resolves to the same local
    # placeholder id (never a fresh random id each call).
    assert unresolved_1.entity_id == unresolved_2.entity_id


def test_unresolved_attendee_never_writes_register(tmp_path: Path) -> None:
    """A calendar event with an attendee the register has never seen must
    fold into a signal WITHOUT ever creating a register note on disk -- the
    read path (`read_register_snapshot`) only reads, and
    `resolve_attendee_readonly` never mints (Scope: "no register mutation")."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    register_dir = vault_root / "_heimdal" / "register"
    assert not register_dir.exists()

    ics_text = _ics(
        "event-unknown",
        dtstart="20260711T090000Z",
        attendees=["ATTENDEE;CN=Totally Unknown Person:mailto:unknown@example.com"],
    )
    binding = _binding()
    item = CalendarRawItem(uid="event-unknown", etag="etag-1", ics_text=ics_text)
    signal = _signal_from_calendar_row(binding, item, register_snapshot=())
    assert signal is not None
    assert len(signal.protagonists) == 1
    assert signal.protagonists[0].startswith("cal:unresolved:")

    # Still no register directory anywhere under the vault -- nothing was minted.
    assert not register_dir.exists()
    assert list(vault_root.rglob("*.md")) == []


# ---------------------------------------------------------------------------
# AC3 (enforcement): joins fusion via the registry only, shift-detection
# core unchanged
# ---------------------------------------------------------------------------


def test_calendar_joins_fusion_via_registry_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Coordinator contract clarification (#3184): AC3 proves (a) the
    five-dimension shift-detection core (`detect_shift`, `_disjoint_set_shift`,
    `fold_signals_into_segments`, the named shift constants) is UNCHANGED,
    and (b) calendar is enumerated + consumed purely via the registry
    (`enumerate_consumable_streams`), folding jointly with heimdal/vault
    signals in the SAME `fold_signals_into_segments` call -- via an additive
    `run_segmentation_tick` ingestion block, not a segmenter-core change."""
    # (a) the shift-detection core's documented invariants still hold,
    # exercised directly and unrelated to any calendar wiring: the named
    # constants are exactly the ERE-04-delivered values, and detect_shift's
    # dimension behavior is untouched.
    assert segmenter.TIME_GAP_MINUTES == 45
    assert segmenter.GOAL_SHIFT_DETECTION_ENABLED is True
    assert segmenter.PROTAGONIST_SHIFT_DETECTION_ENABLED is True
    assert segmenter.CAUSAL_BREAK_DETECTION_ENABLED is True
    assert segmenter.PLACE_SHIFT_DETECTION_ENABLED is False  # calendar does NOT flip this (out of scope)

    heimdal_signal = segmenter.SegmentationSignal(
        stream_id=segmenter.HEIMDAL_STREAM_ID,
        signal_id="obs-1",
        observed_at=_dt(9, 0),
        scope="work",
        provenance_ref="heimdal.observations:obs-1",
        protagonists=("alice",),
        heimdal_session_id="sess-a",
    )
    vault_signal = segmenter.SegmentationSignal(
        stream_id="vault.activity",
        signal_id="vault-1",
        observed_at=_dt(9, 5),
        scope="work",
        provenance_ref="vault.activity:vault-1",
        goal=("proj-x",),
    )
    calendar_signal = segmenter.SegmentationSignal(
        stream_id=CALENDAR_STREAM_ID,
        signal_id="event-1:etag-1",
        observed_at=_dt(9, 2),
        scope="work",
        provenance_ref="calendar:event-1:etag-1",
        protagonists=("alice",),
    )
    # The SAME fold_signals_into_segments call, unmodified, folds all three
    # streams' signals into one segment (joint fusion, not a parallel path).
    updated_open, closed = fold_signals_into_segments(
        [heimdal_signal, vault_signal, calendar_signal], open_segments=None, frontiers={}
    )
    assert closed == []
    assert set(updated_open) == {"work"}
    joint = updated_open["work"]
    assert set(joint.derived_from) == {
        "heimdal.observations:obs-1",
        "vault.activity:vault-1",
        "calendar:event-1:etag-1",
    }

    # (b) the PRODUCTION run_segmentation_tick entrypoint: calendar is
    # enumerated only via enumerate_consumable_streams (the registry), and
    # its raw-item fetch is registry-gated exactly like the existing
    # heimdal/vault blocks -- proven by stubbing the I/O boundaries only,
    # never bypassing the registry-driven `live_streams` gate itself.
    ics_text = _ics(
        "tick-event-1", dtstart="20260711T090500Z", attendees=["ATTENDEE;CN=Alice:mailto:alice@example.com"]
    )
    raw_item = CalendarRawItem(uid="tick-event-1", etag="etag-1", ics_text=ics_text)
    binding = _binding()

    monkeypatch.setattr(
        segmenter,
        "enumerate_consumable_streams",
        lambda *a, **k: (
            SimpleNamespace(stream_id=segmenter.HEIMDAL_STREAM_ID),
            SimpleNamespace(stream_id=CALENDAR_STREAM_ID),
        ),
    )
    monkeypatch.setattr(segmenter, "read_observations_for_consumer", lambda *a, **k: [])
    monkeypatch.setattr(segmenter, "advance_cursor_for_consumer", lambda *a, **k: None)
    monkeypatch.setattr(
        segmenter, "read_calendar_raw_items_for_tick", lambda *a, **k: ([(binding, raw_item)], [])
    )
    monkeypatch.setattr(segmenter, "read_register_snapshot", lambda *a, **k: ())
    monkeypatch.setattr(segmenter.engine_state, "all_state_with_prefix", lambda prefix: {})
    monkeypatch.setattr(segmenter.engine_state, "set_state", lambda key, value: None)
    monkeypatch.setattr(segmenter.engine_state, "delete_state", lambda key: None)
    _stub_assignment_io(monkeypatch)

    result = run_segmentation_tick(vault_root=tmp_path / "vault", write_guard=_allow_guard())
    assert result["consumed"] == {segmenter.HEIMDAL_STREAM_ID: 0, CALENDAR_STREAM_ID: 1}
    assert result["degraded"] == []

    # calendar was NOT enumerated when the registry does not report it live.
    monkeypatch.setattr(
        segmenter, "enumerate_consumable_streams", lambda *a, **k: (SimpleNamespace(stream_id=segmenter.HEIMDAL_STREAM_ID),)
    )
    calls: list[str] = []
    monkeypatch.setattr(
        segmenter,
        "read_calendar_raw_items_for_tick",
        lambda *a, **k: (calls.append("called") or ([], [])),
    )
    result_2 = run_segmentation_tick(vault_root=tmp_path / "vault2", write_guard=_allow_guard())
    assert CALENDAR_STREAM_ID not in result_2["consumed"]
    assert calls == []  # never fetched when the registry does not list it live


# ---------------------------------------------------------------------------
# AC4: credentials resolve from private-bindings only, fail-loud if
# registry-live but unconfigured
# ---------------------------------------------------------------------------


def test_credentials_from_private_bindings_fail_loud(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # No env at all -> fail loud, never a silently-disabled adapter.
    with pytest.raises(CalendarCredentialsError):
        resolve_calendar_bindings(env={})

    # Single-calendar shorthand, fully configured -> resolves.
    single_env = {
        "CALDAV_URL": "https://caldav.icloud.com",
        "CALDAV_USERNAME": "operator@example.com",
        "CALDAV_APP_PASSWORD": "super-secret-value",
        "CALDAV_CALENDAR_PATH": "/calendars/home/",
        "CALDAV_SCOPE": "personal",
    }
    bindings = resolve_calendar_bindings(env=single_env)
    assert len(bindings) == 1
    assert bindings[0].scope == "personal"
    assert bindings[0].app_password == "super-secret-value"

    # The secret value never appears in any exception message anywhere in
    # this module's credential-resolution path.
    partial_env = dict(single_env)
    del partial_env["CALDAV_APP_PASSWORD"]
    with pytest.raises(CalendarCredentialsError) as exc_info:
        resolve_calendar_bindings(env=partial_env)
    assert "super-secret-value" not in str(exc_info.value)

    # Multi-calendar JSON shape (AC6 groundwork): per-calendar scope mapping.
    import json

    json_env = {
        "CALDAV_CALENDARS_JSON": json.dumps(
            [
                {
                    "calendar_id": "work",
                    "base_url": "https://caldav.icloud.com",
                    "username": "operator@example.com",
                    "app_password": "secret-1",
                    "calendar_path": "/calendars/work/",
                    "scope": "work",
                },
                {
                    "calendar_id": "personal",
                    "base_url": "https://caldav.icloud.com",
                    "username": "operator@example.com",
                    "app_password": "secret-2",
                    "calendar_path": "/calendars/home/",
                    "scope": "personal",
                },
            ]
        )
    }
    multi = resolve_calendar_bindings(env=json_env)
    assert {b.scope for b in multi} == {"work", "personal"}

    # Malformed JSON -> fail loud, not a silent fallback to zero calendars.
    with pytest.raises(CalendarCredentialsError):
        resolve_calendar_bindings(env={"CALDAV_CALENDARS_JSON": "not json"})
    with pytest.raises(CalendarCredentialsError):
        resolve_calendar_bindings(env={"CALDAV_CALENDARS_JSON": "[]"})

    # Reached at the REAL run_segmentation_tick call site (registry says
    # calendar is live; no config at all): the tick itself fails loud rather
    # than silently treating calendar as absent.
    monkeypatch.setattr(
        segmenter,
        "enumerate_consumable_streams",
        lambda *a, **k: (SimpleNamespace(stream_id=CALENDAR_STREAM_ID),),
    )
    monkeypatch.delenv("CALDAV_URL", raising=False)
    monkeypatch.delenv("CALDAV_USERNAME", raising=False)
    monkeypatch.delenv("CALDAV_APP_PASSWORD", raising=False)
    monkeypatch.delenv("CALDAV_CALENDAR_PATH", raising=False)
    monkeypatch.delenv("CALDAV_SCOPE", raising=False)
    monkeypatch.delenv("CALDAV_CALENDARS_JSON", raising=False)
    monkeypatch.setattr(segmenter.engine_state, "all_state_with_prefix", lambda prefix: {})
    with pytest.raises(CalendarCredentialsError):
        run_segmentation_tick(vault_root=tmp_path / "vault", write_guard=_allow_guard())


# ---------------------------------------------------------------------------
# AC5: unreachable calendar degrades softly
# ---------------------------------------------------------------------------


def test_unreachable_calendar_degrades_softly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reachable_binding = _binding(calendar_id="reachable-cal", scope="work")
    unreachable_binding = _binding(calendar_id="unreachable-cal", scope="personal")

    ics_text = _ics("ok-event", dtstart="20260711T090000Z")

    def fake_transport(binding: CalendarBinding) -> list[CalendarRawItem]:
        if binding.calendar_id == "unreachable-cal":
            raise CalendarUnreachableError("simulated network failure")
        return [CalendarRawItem(uid="ok-event", etag="etag-1", ics_text=ics_text)]

    items, degraded = read_calendar_raw_items_for_tick(
        bindings=(reachable_binding, unreachable_binding), transport=fake_transport
    )
    assert degraded == ["unreachable-cal"]
    assert len(items) == 1
    assert items[0][0].calendar_id == "reachable-cal"

    # Through the real run_segmentation_tick entrypoint: the tick completes,
    # never raises, and the degraded calendar is reported in the summary --
    # a missing stream never stalls segmentation (other live streams, and
    # the reachable calendar, still process normally).
    monkeypatch.setattr(
        segmenter,
        "enumerate_consumable_streams",
        lambda *a, **k: (SimpleNamespace(stream_id=CALENDAR_STREAM_ID),),
    )
    monkeypatch.setattr(
        segmenter,
        "read_calendar_raw_items_for_tick",
        lambda *a, **k: read_calendar_raw_items_for_tick(
            bindings=(reachable_binding, unreachable_binding), transport=fake_transport
        ),
    )
    monkeypatch.setattr(segmenter, "read_register_snapshot", lambda *a, **k: ())
    monkeypatch.setattr(segmenter.engine_state, "all_state_with_prefix", lambda prefix: {})
    monkeypatch.setattr(segmenter.engine_state, "set_state", lambda key, value: None)
    monkeypatch.setattr(segmenter.engine_state, "delete_state", lambda key: None)
    _stub_assignment_io(monkeypatch)

    result = run_segmentation_tick(vault_root=tmp_path / "vault", write_guard=_allow_guard())
    assert result["degraded"] == ["unreachable-cal"]
    assert result["consumed"][CALENDAR_STREAM_ID] == 1  # the reachable calendar's one item
    assert result["open_segments"] == 1  # the reachable calendar's signal still folded


# ---------------------------------------------------------------------------
# AC6: per-calendar scope mapping respected (ERE-08 discipline)
# ---------------------------------------------------------------------------


def test_calendar_scope_mapping_respected() -> None:
    work_binding = _binding(calendar_id="work-cal", scope="work")
    personal_binding = _binding(calendar_id="personal-cal", scope="private")

    work_item = CalendarRawItem(
        uid="work-event", etag="e1", ics_text=_ics("work-event", dtstart="20260711T090000Z", summary="Standup")
    )
    personal_item = CalendarRawItem(
        uid="personal-event",
        etag="e1",
        ics_text=_ics("personal-event", dtstart="20260711T090500Z", summary="Therapy"),
    )

    work_signal = _signal_from_calendar_row(work_binding, work_item, register_snapshot=())
    personal_signal = _signal_from_calendar_row(personal_binding, personal_item, register_snapshot=())
    assert work_signal is not None and personal_signal is not None
    assert work_signal.scope == "work"
    assert personal_signal.scope == "private"

    # The already-shipped per-scope partitioning keeps them in separate
    # segments -- a work-calendar signal never enters the private partition,
    # even though both signals arrive in the SAME fold call.
    updated_open, closed = fold_signals_into_segments(
        [work_signal, personal_signal], open_segments=None, frontiers={}
    )
    assert closed == []
    assert set(updated_open) == {"work", "private"}
    assert updated_open["work"].derived_from == ("calendar:work-event:e1",)
    assert updated_open["private"].derived_from == ("calendar:personal-event:e1",)
    # No cross-contamination: the private segment's provenance never
    # includes the work calendar's ref, and vice versa.
    assert "calendar:personal-event:e1" not in updated_open["work"].derived_from
    assert "calendar:work-event:e1" not in updated_open["private"].derived_from


# ---------------------------------------------------------------------------
# Review gate round 1 (PR #3519, calendar-parsing robustness gaps the
# ICS-fixture tests above did not exercise -- would have surfaced only on
# the deferred mac-mini live-CalDAV channel, against real iCloud data).
# ---------------------------------------------------------------------------


def test_tzid_qualified_dtstart_resolves_to_correct_utc_instant() -> None:
    """Finding 1 (confirmed): iCloud writes TZID-qualified local times
    (`DTSTART;TZID=Europe/Stockholm:...`), never a bare local without a
    zone. A 09:00 Europe/Stockholm meeting in July (CEST, UTC+2) must
    resolve to 07:00 UTC -- the pre-fix code silently treated any non-'Z'
    value as already-UTC, a multi-hour skew on the `time` dimension the
    confidence table scores highest (0.95/by_construction)."""
    ics_text = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:tzid-event\r\n"
        "DTSTART;TZID=Europe/Stockholm:20260711T090000\r\n"
        "DTEND;TZID=Europe/Stockholm:20260711T093000\r\n"
        "SUMMARY:Stockholm Meeting\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    event = parse_vevent(ics_text)
    assert event is not None
    assert event.dtstart == datetime(2026, 7, 11, 7, 0, tzinfo=timezone.utc)
    assert event.dtend == datetime(2026, 7, 11, 7, 30, tzinfo=timezone.utc)
    assert event.time_is_floating is False

    contract = calendar_event_to_signal_contract(uid="tzid-event", etag="etag-1", event=event, scope="work")
    assert contract.observed_at_start == "2026-07-11T07:00:00+00:00"
    assert contract.dimensions_fed["time"].calibration == "by_construction"
    assert contract.dimensions_fed["time"].score == 0.95


def test_floating_local_dtstart_degrades_time_confidence() -> None:
    """Finding 1 (confirmed): a genuinely floating local time (no 'Z' AND
    no TZID param) has no fixed UTC instant -- it must never be silently
    asserted as `by_construction` UTC. The best-effort UTC-naive rendering
    is still produced (never a crash) but the `time` dimension degrades to
    a heuristic confidence, matching every other inferred dimension."""
    ics_text = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:floating-event\r\n"
        "DTSTART:20260711T090000\r\n"
        "SUMMARY:Floating Time Event\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    event = parse_vevent(ics_text)
    assert event is not None
    assert event.time_is_floating is True
    assert event.dtstart == datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)  # best-effort, never a crash

    contract = calendar_event_to_signal_contract(uid="floating-event", etag="etag-1", event=event, scope="work")
    assert contract.dimensions_fed["time"].calibration == "heuristic"
    assert contract.dimensions_fed["time"].score < 0.95


def test_unresolvable_tzid_degrades_rather_than_raises() -> None:
    """An unknown/garbage TZID (malformed feed, or a zone name this host's
    tz database doesn't have) never crashes the parse -- it degrades to
    floating exactly like a bare local time, never guessing an offset."""
    ics_text = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:bad-tzid-event\r\n"
        "DTSTART;TZID=Not/A_Real_Zone:20260711T090000\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    event = parse_vevent(ics_text)
    assert event is not None
    assert event.time_is_floating is True
    assert event.dtstart == datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)


def test_calendar_query_body_bounds_and_expands() -> None:
    """Findings 2 + 3 (confirmed / plausible): the production REPORT body
    must request a bounded `<C:time-range>` AND server-side `<C:expand>`
    over the SAME window -- without `<C:time-range>`, every tick refetches
    the whole calendar history (finding 3); without `<C:expand>`, a
    recurring master VEVENT comes back unexpanded and its later occurrences
    never emit (finding 2). RFC 4791 9.6.5 requires expand's start/end to
    match the query's bound, so the two fixes share one named window."""
    reference = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
    body = _calendar_query_body(now=reference)
    expected_start = "20260704T120000Z"  # 7 days back
    expected_end = "20260909T120000Z"  # 60 days forward
    assert f'<C:time-range start="{expected_start}" end="{expected_end}"/>' in body
    assert f'<C:expand start="{expected_start}" end="{expected_end}"/>' in body


def test_expanded_recurring_occurrences_each_emit_a_distinct_signal() -> None:
    """Finding 2 (confirmed): a server-side `<C:expand>` response returns
    MULTIPLE VEVENT components for one recurring master under ONE
    href/etag (each carrying its own RECURRENCE-ID/DTSTART) -- each
    occurrence must fold as ITS OWN signal (distinct signal_id/
    provenance_ref), never collide because signal_id was keyed on the
    constant uid:etag alone."""
    expanded_ics = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:recurring-standup\r\n"
        "RECURRENCE-ID:20260706T090000Z\r\n"
        "DTSTART:20260706T090000Z\r\n"
        "DTEND:20260706T091500Z\r\n"
        "SUMMARY:Daily Standup\r\n"
        "END:VEVENT\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:recurring-standup\r\n"
        "RECURRENCE-ID:20260707T090000Z\r\n"
        "DTSTART:20260707T090000Z\r\n"
        "DTEND:20260707T091500Z\r\n"
        "SUMMARY:Daily Standup\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    multistatus = (
        '<?xml version="1.0"?>\n'
        '<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">\n'
        "  <D:response>\n"
        "    <D:href>/calendars/work/recurring-standup.ics</D:href>\n"
        "    <D:propstat>\n"
        "      <D:prop>\n"
        '        <D:getetag>"etag-master"</D:getetag>\n'
        f"        <C:calendar-data>{expanded_ics}</C:calendar-data>\n"
        "      </D:prop>\n"
        "      <D:status>HTTP/1.1 200 OK</D:status>\n"
        "    </D:propstat>\n"
        "  </D:response>\n"
        "</D:multistatus>\n"
    )
    items = _parse_multistatus(multistatus)
    assert len(items) == 2
    assert {item.occurrence_key for item in items} == {"20260706T090000Z", "20260707T090000Z"}
    assert all(item.uid == "recurring-standup" and item.etag == "etag-master" for item in items)

    binding = _binding(calendar_id="work-cal", scope="work")
    signals = [_signal_from_calendar_row(binding, item, register_snapshot=()) for item in items]
    assert all(signal is not None for signal in signals)
    signal_ids = {signal.signal_id for signal in signals if signal is not None}
    # Review gate round 2 (finding 1): IDENTITY is `uid:occurrence_key`,
    # window-independent -- the shared master etag no longer participates
    # at all (finding 2: it must not, since it is one shared resource-level
    # value, not a per-occurrence one). Each id is the exact canonical
    # `calendar_signal_id` output for that occurrence's own parsed content.
    expected_ids = {
        calendar_signal_id(item.uid, item.etag, item.occurrence_key, parse_vevent(item.ics_text))
        for item in items
    }
    assert signal_ids == expected_ids
    # The IDENTITY portion (everything but the trailing change-token) is
    # exactly `uid:occurrence_key` -- no etag anywhere in it.
    assert {sid.rsplit(":", 1)[0] for sid in signal_ids} == {
        "recurring-standup:20260706T090000Z",
        "recurring-standup:20260707T090000Z",
    }

    # Both occurrences fold as SEPARATE evidence (a day apart, well past
    # TIME_GAP_MINUTES=45 -- one closes before the other opens), proving
    # neither collided into a single ever-emitted-once signal.
    updated_open, closed = fold_signals_into_segments(
        [signal for signal in signals if signal is not None], open_segments=None, frontiers={}
    )
    all_derived: set[str] = set()
    for seg in list(updated_open.values()) + closed:
        all_derived |= set(seg.derived_from)
    assert {f"calendar:{sid}" for sid in signal_ids} <= all_derived


def test_quoted_cn_attendee_strips_quotes_and_resolves() -> None:
    """Finding 4 (plausible): `CN="Doe, John"` (RFC 5545 requires quoting
    when the display name contains a comma) must resolve to the surface
    form `Doe, John` -- the pre-fix regex captured the literal quotes,
    so an exact-match against a register label always missed, misclassifying
    a known attendee as `AttendeeUnresolved` every tick."""
    ics_text = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:quoted-cn-event\r\n"
        "DTSTART:20260711T090000Z\r\n"
        'ATTENDEE;CN="Doe, John":mailto:doe@example.com\r\n'
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    event = parse_vevent(ics_text)
    assert event is not None
    assert len(event.attendees) == 1
    assert event.attendees[0].surface_form == "Doe, John"  # no literal quotes

    known = (
        RegisterEntrySnapshot(entity_id="ent:doe-john", label="Doe, John", aliases=(), lifecycle="canonical"),
    )
    resolved = resolve_attendee_readonly(event.attendees[0].surface_form, known_entries=known)
    assert isinstance(resolved, AttendeeResolved)
    assert resolved.entity_id == "ent:doe-john"


# ---------------------------------------------------------------------------
# Review gate round 2 (PR #3519, inline comments 3565621365 / 3565621498):
# recurring-occurrence signal_id STABILITY. Round 1 fixed "a recurring
# occurrence gets its own signal_id at all" (finding 2, round 1); round 2
# fixes "that signal_id must be the SAME id for the SAME occurrence no
# matter which tick observes it" -- both across a change in the tick's
# expand/time-range window population (finding 1) and across an unrelated
# sibling occurrence's edit bumping the shared resource etag (finding 2).
# ---------------------------------------------------------------------------


def _multistatus_response(href: str, etag: str, calendar_data: str) -> str:
    return (
        '<?xml version="1.0"?>\n'
        '<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">\n'
        "  <D:response>\n"
        f"    <D:href>{href}</D:href>\n"
        "    <D:propstat>\n"
        "      <D:prop>\n"
        f'        <D:getetag>"{etag}"</D:getetag>\n'
        f"        <C:calendar-data>{calendar_data}</C:calendar-data>\n"
        "      </D:prop>\n"
        "      <D:status>HTTP/1.1 200 OK</D:status>\n"
        "    </D:propstat>\n"
        "  </D:response>\n"
        "</D:multistatus>\n"
    )


def test_occurrence_signal_id_stable_single_vs_multiple_in_window() -> None:
    """Finding 1 (confirmed regression, inline comment 3565621365): the SAME
    real occurrence of a recurring series must resolve to the SAME
    signal_id whether it is the ONLY occurrence this tick's expand/
    time-range window returns, or a sibling occurrence also falls
    in-window this tick. The pre-fix code gated `occurrence_key` on
    `is_expanded = len(event_blocks) > 1` -- purely an artifact of how many
    siblings happened to share THIS tick's window, not a property of the
    occurrence itself -- so the same occurrence flipped between a bare
    `uid:etag` identity (alone in-window) and `uid:etag:occurrence_key`
    (paired with a sibling in-window), breaking same-occurrence idempotency
    and causing the segmenter to fold the SAME calendar instance twice
    under two different identities."""
    href = "/calendars/work/recurring-standup.ics"
    occurrence_a = (
        "BEGIN:VEVENT\r\n"
        "UID:recurring-standup\r\n"
        "RECURRENCE-ID:20260706T090000Z\r\n"
        "DTSTART:20260706T090000Z\r\n"
        "DTEND:20260706T091500Z\r\n"
        "SUMMARY:Daily Standup\r\n"
        "END:VEVENT\r\n"
    )
    occurrence_b_sibling = (
        "BEGIN:VEVENT\r\n"
        "UID:recurring-standup\r\n"
        "RECURRENCE-ID:20260707T090000Z\r\n"
        "DTSTART:20260707T090000Z\r\n"
        "DTEND:20260707T091500Z\r\n"
        "SUMMARY:Daily Standup\r\n"
        "END:VEVENT\r\n"
    )

    # Tick 1, a narrow window: occurrence A is the ONLY occurrence returned.
    alone_items = _parse_multistatus(_multistatus_response(href, "etag-master", occurrence_a))
    assert len(alone_items) == 1
    # Never None just because this occurrence happened to be alone --
    # RECURRENCE-ID is this occurrence's own field, independent of siblings.
    assert alone_items[0].occurrence_key == "20260706T090000Z"

    # Tick 2, a wider window: occurrence A AND sibling occurrence B both
    # fall in-window this time, in the SAME multistatus response (one
    # recurring master, one href/etag).
    paired_items = _parse_multistatus(
        _multistatus_response(href, "etag-master", occurrence_a + occurrence_b_sibling)
    )
    assert len(paired_items) == 2

    binding = _binding(calendar_id="work-cal", scope="work")
    alone_signal = _signal_from_calendar_row(binding, alone_items[0], register_snapshot=())
    paired_signal_a = next(
        signal
        for item in paired_items
        if item.occurrence_key == "20260706T090000Z"
        for signal in (_signal_from_calendar_row(binding, item, register_snapshot=()),)
    )
    assert alone_signal is not None and paired_signal_a is not None
    # THE SAME occurrence (A) resolves to the SAME identity+signal_id
    # whether it was alone in-window (tick 1) or paired with a sibling
    # in-window (tick 2) -- the confirmed idempotency regression, fixed.
    assert alone_signal.signal_id == paired_signal_a.signal_id
    assert alone_signal.provenance_ref == paired_signal_a.provenance_ref


def test_sibling_edit_bumps_shared_etag_but_not_unedited_occurrence_signal_id() -> None:
    """Finding 2 (plausible, inline comment 3565621498): a CalDAV recurring
    series is ONE resource with ONE etag. Editing any single occurrence
    bumps the WHOLE resource's shared etag on the next poll -- so every
    UNMODIFIED sibling occurrence must NOT get a new signal_id (that would
    wrongly re-emit it as "new" evidence, edit-noise on every unrelated
    sibling). Change detection must key on the occurrence's OWN content
    (DTSTART/DTEND/SUMMARY/SEQUENCE/LAST-MODIFIED), never the shared
    resource etag. The identity (finding 1: uid + recurrence-id) stays
    stable either way; only the edited occurrence's own change-token
    differs."""
    href = "/calendars/work/recurring-standup.ics"

    def _occurrence(recurrence_id: str, dtstart: str, dtend: str, summary: str) -> str:
        return (
            "BEGIN:VEVENT\r\n"
            "UID:recurring-standup\r\n"
            f"RECURRENCE-ID:{recurrence_id}\r\n"
            f"DTSTART:{dtstart}\r\n"
            f"DTEND:{dtend}\r\n"
            f"SUMMARY:{summary}\r\n"
            "END:VEVENT\r\n"
        )

    occurrence_a = _occurrence("20260706T090000Z", "20260706T090000Z", "20260706T091500Z", "Daily Standup")
    occurrence_b_v1 = _occurrence("20260707T090000Z", "20260707T090000Z", "20260707T091500Z", "Daily Standup")
    # Occurrence B is edited (its SUMMARY changes); occurrence A's ICS text
    # is byte-for-byte identical across both ticks.
    occurrence_b_v2 = _occurrence(
        "20260707T090000Z", "20260707T090000Z", "20260707T091500Z", "Daily Standup (moved to Room B)"
    )

    # Tick 1: both occurrences, shared etag v1.
    items_v1 = _parse_multistatus(
        _multistatus_response(href, "etag-v1", occurrence_a + occurrence_b_v1)
    )
    # Tick 2: occurrence B edited -> the ONE shared CalDAV resource's etag
    # bumps for the WHOLE series, even though occurrence A never changed.
    items_v2 = _parse_multistatus(
        _multistatus_response(href, "etag-v2", occurrence_a + occurrence_b_v2)
    )
    assert {item.etag for item in items_v1} == {"etag-v1"}
    assert {item.etag for item in items_v2} == {"etag-v2"}  # the shared etag DID bump

    binding = _binding(calendar_id="work-cal", scope="work")

    def _signal_for(items: list[CalendarRawItem], occurrence_key: str):
        item = next(i for i in items if i.occurrence_key == occurrence_key)
        return _signal_from_calendar_row(binding, item, register_snapshot=())

    signal_a_v1 = _signal_for(items_v1, "20260706T090000Z")
    signal_a_v2 = _signal_for(items_v2, "20260706T090000Z")
    signal_b_v1 = _signal_for(items_v1, "20260707T090000Z")
    signal_b_v2 = _signal_for(items_v2, "20260707T090000Z")
    assert all(s is not None for s in (signal_a_v1, signal_a_v2, signal_b_v1, signal_b_v2))

    # Occurrence A never changed -- despite the shared resource etag
    # bumping (v1 -> v2), its signal_id (identity AND change-token) must be
    # UNCHANGED. This is the confirmed edit-noise bug, fixed: the old
    # etag-keyed scheme would have re-emitted A as "new" here.
    assert signal_a_v1.signal_id == signal_a_v2.signal_id

    # Occurrence B WAS edited -- its own content changed, so its signal_id
    # must differ (the documented invariant "an edited event gets a new
    # signal_id", preserved at the occurrence level).
    assert signal_b_v1.signal_id != signal_b_v2.signal_id

    # The identity portion (uid:occurrence_key) of B is unchanged across
    # the edit -- only the trailing change-token differs -- proving
    # identity (finding 1) and change-detection (finding 2) are properly
    # decoupled.
    assert signal_b_v1.signal_id.rsplit(":", 1)[0] == signal_b_v2.signal_id.rsplit(":", 1)[0]


# ---------------------------------------------------------------------------
# Review gate round 3 (PR #3519, inline comments 3565668923 / 3565668944):
# the round-2 window-independence fix survived only on the RECURRENCE-ID
# path (the DTSTART fallback still gated identity on in-window block count),
# and the change-token hashed a '|'-joined string that free text could
# forge. Both are now closed.
# ---------------------------------------------------------------------------


def test_no_recurrence_id_occurrence_signal_id_stable_single_vs_multiple_in_window() -> None:
    """Finding 1 round 3 (confirmed, inline comment 3565668923): a recurring
    instance WITHOUT a RECURRENCE-ID must resolve to the SAME signal_id
    whether or not a sibling block shares this tick's response. The round-2
    DTSTART fallback was gated on `multiple_blocks_this_response`, so such
    an instance got a bare `uid:etag` identity when alone in-window but a
    DTSTART-keyed identity when a sibling was also in-window -- the exact
    window-dependent identity flip round 2 was meant to kill, surviving on
    the fallback path. The chosen rule (a): absent a RECURRENCE-ID, treat
    the block as a single event -> `occurrence_key` is None -> `uid:etag`,
    identically in both cases (the documented conservative residual: a
    non-compliant multi-block no-RECURRENCE-ID expansion under-counts, but
    never flips identity)."""
    href = "/calendars/work/no-recurrence-id.ics"
    # No RECURRENCE-ID on either block -- only DTSTART distinguishes them.
    block_a = (
        "BEGIN:VEVENT\r\n"
        "UID:no-rid-series\r\n"
        "DTSTART:20260706T090000Z\r\n"
        "DTEND:20260706T091500Z\r\n"
        "SUMMARY:Daily Standup\r\n"
        "END:VEVENT\r\n"
    )
    block_b_sibling = (
        "BEGIN:VEVENT\r\n"
        "UID:no-rid-series\r\n"
        "DTSTART:20260707T090000Z\r\n"
        "DTEND:20260707T091500Z\r\n"
        "SUMMARY:Daily Standup\r\n"
        "END:VEVENT\r\n"
    )

    # Tick 1: block A is the only block in the response.
    alone_items = _parse_multistatus(_multistatus_response(href, "etag-master", block_a))
    assert len(alone_items) == 1
    # No RECURRENCE-ID -> treated as a single event, window-independently.
    assert alone_items[0].occurrence_key is None

    # Tick 2: block A AND sibling block B share the SAME response (one
    # href/etag). Block-count is now 2 -- but that must NOT change A's
    # identity the way the removed round-2 fallback did.
    paired_items = _parse_multistatus(_multistatus_response(href, "etag-master", block_a + block_b_sibling))
    assert len(paired_items) == 2
    paired_a = next(i for i in paired_items if "20260706" in i.ics_text)
    assert paired_a.occurrence_key is None  # still None, regardless of sibling count

    binding = _binding(calendar_id="work-cal", scope="work")
    alone_signal = _signal_from_calendar_row(binding, alone_items[0], register_snapshot=())
    paired_signal_a = _signal_from_calendar_row(binding, paired_a, register_snapshot=())
    assert alone_signal is not None and paired_signal_a is not None
    # The identity-flip bug is dead on the fallback path too: same block,
    # same signal_id, whether alone or paired in-window.
    assert alone_signal.signal_id == paired_signal_a.signal_id
    assert alone_signal.signal_id == "no-rid-series:etag-master"


def test_content_token_summary_with_pipe_does_not_collide() -> None:
    """Finding 2 round 3 (plausible, inline comment 3565668944): the
    change-token must hash a structured encoding, not a `|`-joined string.
    The old token was ``"|".join([dtstart, dtend, summary, f"seq={seq}",
    f"lm={lm}"])``; free text in SUMMARY could impersonate a trailing field
    and shift the boundary, so two genuinely-different occurrences hashed
    identically -> a real content change MISSED (false-negative change
    detection, suppressing re-emission of an edited event).

    Concrete forgery, chosen to collide under the OLD join specifically:
      - event 1: SUMMARY=`Team Sync`, SEQUENCE=3
        -> old join `<dt>|<dt>|Team Sync|seq=3`
      - event 2: SUMMARY=`Team Sync|seq=3`, no SEQUENCE
        -> old join `<dt>|<dt>|Team Sync|seq=3`   (IDENTICAL)
    Same DTSTART/DTEND on both. The structured JSON hash (distinct
    `summary` and `sequence` fields, each self-delimited by JSON escaping)
    must keep them apart."""
    shared_times = "DTSTART:20260706T090000Z\r\nDTEND:20260706T091500Z\r\n"
    ics_1 = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\n"
        "UID:pipe-event\r\nRECURRENCE-ID:20260706T090000Z\r\n"
        f"{shared_times}"
        "SUMMARY:Team Sync\r\n"
        "SEQUENCE:3\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    ics_2 = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\n"
        "UID:pipe-event\r\nRECURRENCE-ID:20260706T090000Z\r\n"
        f"{shared_times}"
        "SUMMARY:Team Sync|seq=3\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    event_1 = parse_vevent(ics_1)
    event_2 = parse_vevent(ics_2)
    assert event_1 is not None and event_2 is not None
    # Genuinely different occurrences: different summary AND different
    # sequence -- yet their OLD '|'-joined encodings were byte-identical.
    assert (event_1.summary, event_1.sequence) != (event_2.summary, event_2.sequence)
    assert event_1.summary == "Team Sync" and event_1.sequence == 3
    assert event_2.summary == "Team Sync|seq=3" and event_2.sequence is None

    token_1 = _occurrence_content_token(event_1)
    token_2 = _occurrence_content_token(event_2)
    assert token_1 != token_2  # structured hash keeps them distinct

    # End-to-end: full signal_ids differ, so a real edit that happens to
    # involve a '|'-containing SUMMARY is never silently dropped as
    # unchanged; the shared identity portion still marks them as the SAME
    # occurrence (same uid + occurrence_key).
    id_1 = calendar_signal_id("pipe-event", "etag-x", "20260706T090000Z", event_1)
    id_2 = calendar_signal_id("pipe-event", "etag-x", "20260706T090000Z", event_2)
    assert id_1 != id_2
    assert id_1.rsplit(":", 1)[0] == id_2.rsplit(":", 1)[0] == "pipe-event:20260706T090000Z"
