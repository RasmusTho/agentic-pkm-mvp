"""#3316: Daily Briefing consumes the already-live ERE calendar interfaces."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.briefing import compose_briefing, load_briefing
from app.episodes.calendar_stream import CalendarBinding, CalendarRawItem
from app.episodes.notes import render_episode_note
from app.episodes.stream_registry import STATUS_LIVE, StreamRegistry, StreamRegistryEntry
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard


BRIEFING_DATE = date(2026, 7, 10)


def _context(vault_root: Path) -> VaultContext:
    return VaultContext(
        status="selected",
        active_vault_id="test-vault",
        active_vault_name="Test Vault",
        active_vault_path=str(vault_root),
    )


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, VaultContext]:
    root = tmp_path / "vault"
    root.mkdir()
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "_system")
    return root, _context(root)


def _calendar_registry() -> StreamRegistry:
    return StreamRegistry(
        entries={
            "calendar": StreamRegistryEntry(
                stream_id="calendar",
                status=STATUS_LIVE,
                owner_constituent="private-bindings",
                dimensions_fed=("time",),
                transport="module:app.episodes.calendar_stream",
                consent_class="operator-bound",
                cadence="sparse",
            )
        }
    )


def _calendar_item() -> tuple[CalendarBinding, CalendarRawItem]:
    binding = CalendarBinding(
        calendar_id="work",
        base_url="https://calendar.example.test",
        username="owner",
        app_password="not-a-secret",
        calendar_path="/calendars/work/",
        scope="work",
    )
    return binding, CalendarRawItem(
        uid="planning-1",
        etag="etag-1",
        ics_text=(
            "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:planning-1\n"
            "SUMMARY:Planning session\nDTSTART:20260710T090000Z\n"
            "DTEND:20260710T100000Z\nEND:VEVENT\nEND:VCALENDAR\n"
        ),
    )


def _seed_episode(root: Path) -> None:
    fields = {
        "episode_id": "ep-00000000-0000-4000-8000-000000000001",
        "scope": "work",
        "title": "Planning episode",
        "time": {
            "start": "2026-07-10T08:30:00Z",
            "end": "2026-07-10T10:30:00Z",
            "closed": False,
        },
        "space": [],
        "protagonists": [],
        "goal": [],
        "causation": [],
        "parent_episode": None,
        "segmentation": "proposed",
        "derived_from": ["calendar:planning-1:etag-1"],
    }
    path = root / "episodes" / "ep-00000000-0000-4000-8000-000000000001.md"
    path.parent.mkdir(parents=True)
    path.write_text(render_episode_note(fields), encoding="utf-8")


def test_briefing_includes_todays_calendar_episodes_when_stream_live(
    vault: tuple[Path, VaultContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC1: only ERE's registered stream and episode-note interfaces are read."""
    from app.briefing import compose as compose_module

    root, context = vault
    _seed_episode(root)
    monkeypatch.setattr(compose_module, "load_registry", _calendar_registry)
    monkeypatch.setattr(
        compose_module,
        "read_calendar_raw_items_for_tick",
        lambda: ([_calendar_item()], []),
    )

    compose_briefing(
        vault_context=context,
        for_date=BRIEFING_DATE,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )

    note = load_briefing(vault_context=context, for_date=BRIEFING_DATE)
    assert note is not None
    section = note.sections["calendar_episodes"]
    assert section.status == "available"
    assert [(item.source, item.provenance_ref) for item in section.items] == [
        ("episode", "ep-00000000-0000-4000-8000-000000000001"),
        ("calendar", "calendar:planning-1:etag-1"),
    ]


def test_degraded_calendar_stream_names_missing_section(
    vault: tuple[Path, VaultContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC2: ERE read failures use the existing briefing degrade convention."""
    from app.briefing import compose as compose_module

    _root, context = vault
    monkeypatch.setattr(compose_module, "load_registry", _calendar_registry)
    monkeypatch.setattr(
        compose_module,
        "read_calendar_raw_items_for_tick",
        lambda: (_ for _ in ()).throw(RuntimeError("ERE unavailable")),
    )

    compose_briefing(
        vault_context=context,
        for_date=BRIEFING_DATE,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )

    note = load_briefing(vault_context=context, for_date=BRIEFING_DATE)
    assert note is not None
    assert note.degraded_sections == ("calendar_episodes",)
    assert note.sections["calendar_episodes"].reason == "source_read_failed"


def test_calendar_section_reads_existing_ere_interfaces_only(
    vault: tuple[Path, VaultContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC3: the composer only consumes ERE fixtures; it owns no adapter/segmenter."""
    from app.briefing import compose as compose_module

    root, context = vault
    _seed_episode(root)
    monkeypatch.setattr(compose_module, "load_registry", _calendar_registry)
    monkeypatch.setattr(
        compose_module,
        "read_calendar_raw_items_for_tick",
        lambda: ([_calendar_item()], []),
    )

    compose_briefing(
        vault_context=context,
        for_date=BRIEFING_DATE,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )

    rendered = (root / "_system" / "briefings" / "2026-07-10.md").read_text(encoding="utf-8")
    assert "calendar:planning-1:etag-1" in rendered
    assert "ep-00000000-0000-4000-8000-000000000001" in rendered


def test_calendar_section_uses_stockholm_day_boundaries_and_excludes_old_points(
    vault: tuple[Path, VaultContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Entries are bounded by the local day used by the briefing scheduler."""
    from app.briefing import compose as compose_module

    root, context = vault
    binding, _item = _calendar_item()
    local_midnight_entry = CalendarRawItem(
        uid="local-start",
        etag="etag-local",
        ics_text=(
            "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:local-start\n"
            "SUMMARY:Local midnight\nDTSTART:20260709T223000Z\n"
            "DTEND:20260709T230000Z\nEND:VEVENT\nEND:VCALENDAR\n"
        ),
    )
    old_point_entry = CalendarRawItem(
        uid="old-point",
        etag="etag-old",
        ics_text=(
            "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:old-point\n"
            "SUMMARY:Yesterday point\nDTSTART:20260709T120000Z\n"
            "END:VEVENT\nEND:VCALENDAR\n"
        ),
    )
    monkeypatch.setattr(compose_module, "load_registry", _calendar_registry)
    monkeypatch.setattr(
        compose_module,
        "read_calendar_raw_items_for_tick",
        lambda: ([(binding, local_midnight_entry), (binding, old_point_entry)], []),
    )

    compose_briefing(
        vault_context=context,
        for_date=BRIEFING_DATE,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
    )

    note = load_briefing(vault_context=context, for_date=BRIEFING_DATE)
    assert note is not None
    assert [item.provenance_ref for item in note.sections["calendar_episodes"].items] == [
        "calendar:local-start:etag-local"
    ]
