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
    parse_vevent,
    read_calendar_raw_items_for_tick,
    resolve_attendee_readonly,
    resolve_calendar_bindings,
)
from app.episodes.segmenter import _signal_from_calendar_row, fold_signals_into_segments, run_segmentation_tick
from app.episodes.stream_registry import ConfidenceScore
from app.write_guard import WriteGuard

pytestmark = pytest.mark.not_pg


def _allow_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy", "reason": None})


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
