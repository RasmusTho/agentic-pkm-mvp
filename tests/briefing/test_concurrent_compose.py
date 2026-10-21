"""Regression coverage for #5656: one readable briefing per date, never rewritten.

The dev incident left ``_conflicts/`` with four ``concurrent-save`` copies per
event and a briefing whose frontmatter/body no longer matched. That signature is
exactly one ingest-time uuid heal (``ensure_note_uuid``) rewriting the derived,
read-only briefing after it was composed: the vault-wide watcher emits
``ingest.vault.changed`` for the new or re-observed dated note, the outbox
worker's ``handle_ingest_vault_changed`` heals the missing ``uuid`` through the
multiwriter adapter, and the reserialized note fails the canonical re-render
check. These tests race first-contact triggers against that ingest writer and
replay the restart path against an existing past-date briefing.
"""

from __future__ import annotations

import os
import threading
import time
import hashlib
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.briefing import compose as compose_module
from app.briefing import load_briefing
from app.briefing.compose import briefing_note_path, migrate_briefing_identity
from app.briefing.trigger import first_contact_briefing, scheduled_briefing_tick
from app.knowledge.errors import KnowledgeWriteConflict
from app.knowledge.profile_authority import ProfileIdentityRecord
from app.knowledge.profile_authority_store import ProfileAuthorityStore
from app.services import note_uuid as note_uuid_module
from app.vault.manager import VaultContext
from app.workers.outbox_worker import _ensure_uuid_with_backoff
from app.write_guard import WriteGuard

HEALTHY = WriteGuard(lambda: {"state": "healthy"})
TODAY = date(2026, 9, 24)
PAST = date(2026, 8, 19)
TODAY_MORNING = datetime(2026, 9, 24, 4, 41, 34, tzinfo=timezone.utc)  # 06:41 Stockholm
TODAY_SCHEDULED = datetime(2026, 9, 24, 5, 15, tzinfo=timezone.utc)  # 07:15 Stockholm
CONCURRENT_TRIGGERS = 6


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> VaultContext:
    root = tmp_path / "vault"
    root.mkdir()
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "⚙️ System")
    monkeypatch.setenv("STORE_BACKEND", "memory")
    from app.episodes.stream_registry import StreamRegistry

    monkeypatch.setattr(compose_module, "load_registry", lambda: StreamRegistry(entries={}))
    monkeypatch.setattr(compose_module, "read_calendar_raw_items_for_tick", lambda: ([], []))
    # The ingest uuid heal runs under the production guard; the test vault is healthy.
    monkeypatch.setattr(note_uuid_module, "DEFAULT_WRITE_GUARD", HEALTHY)
    return VaultContext(status="selected", active_vault_id="v1", active_vault_path=str(root))


def _conflict_copies(context: VaultContext, for_date: date) -> list[str]:
    conflicts = briefing_note_path(vault_context=context, for_date=for_date).parent / "_conflicts"
    if not conflicts.exists():
        return []
    return sorted(
        path.name for path in conflicts.iterdir() if path.name.startswith(for_date.isoformat())
    )


def _ingest_uuid_heal(context: VaultContext, for_date: date) -> str:
    """Replay the worker's ingest uuid heal (``handle_ingest_vault_changed``)."""

    note = briefing_note_path(vault_context=context, for_date=for_date)
    assert note.exists()
    return _ensure_uuid_with_backoff(note, vault_root=Path(context.active_vault_path or ""))


def test_concurrent_first_contact_composes_one_readable_briefing(
    vault: VaultContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_compose = compose_module.compose_briefing
    compose_calls = 0
    count_lock = threading.Lock()

    def counting_compose(**kwargs: object) -> object:
        nonlocal compose_calls
        with count_lock:
            compose_calls += 1
        return real_compose(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("app.briefing.trigger.compose_briefing", counting_compose)
    target = briefing_note_path(vault_context=vault, for_date=TODAY)
    barrier = threading.Barrier(CONCURRENT_TRIGGERS + 1)
    results = []
    errors: list[BaseException] = []

    def companion_request() -> None:
        try:
            barrier.wait()
            results.append(
                first_contact_briefing(
                    vault_context=vault, now=TODAY_MORNING, write_guard=HEALTHY
                )
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    def ingest_worker() -> None:
        # The watcher observes the freshly composed note and the worker ingests it
        # while other first-contact requests are still in flight.
        try:
            barrier.wait()
            deadline = time.monotonic() + 30
            while not target.exists() and time.monotonic() < deadline:
                time.sleep(0.001)
            _ingest_uuid_heal(vault, TODAY)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=companion_request) for _ in range(CONCURRENT_TRIGGERS)]
    threads.append(threading.Thread(target=ingest_worker))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert compose_calls == 1
    assert sum(result.triggered for result in results) == 1
    assert {result.reason for result in results if not result.triggered} == {
        "already_generated_today"
    }
    note = load_briefing(vault_context=vault, for_date=TODAY)
    assert note is not None and note.briefing_date == TODAY
    assert _conflict_copies(vault, TODAY) == []


def test_existing_past_briefing_is_not_recomposed(vault: VaultContext) -> None:
    compose_module.compose_briefing(vault_context=vault, for_date=PAST, write_guard=HEALTHY)
    past = briefing_note_path(vault_context=vault, for_date=PAST)
    original_bytes = past.read_bytes()
    original_stat = os.stat(past)

    # Service restart: the watcher re-observes every vault note (the old
    # briefing included), the worker ingests it, and the briefing hooks run for
    # the current local day.
    identity_before = _ingest_uuid_heal(vault, PAST)
    scheduled = scheduled_briefing_tick(
        vault_context=vault, now=TODAY_SCHEDULED, write_guard=HEALTHY
    )
    first_contact = first_contact_briefing(
        vault_context=vault, now=TODAY_MORNING, write_guard=HEALTHY
    )
    identity_after = _ingest_uuid_heal(vault, PAST)

    # Re-ingest keeps one stable identity for the note without persisting it.
    assert identity_before and identity_before == identity_after
    assert scheduled.briefing_date == TODAY
    assert first_contact.briefing_date == TODAY
    assert past.read_bytes() == original_bytes
    current_stat = os.stat(past)
    assert (current_stat.st_ino, current_stat.st_mtime_ns) == (
        original_stat.st_ino,
        original_stat.st_mtime_ns,
    )
    assert _conflict_copies(vault, PAST) == []
    note = load_briefing(vault_context=vault, for_date=PAST)
    assert note is not None and note.briefing_date == PAST


def test_daily_briefing_identity_migration_uses_cas_and_retains_original(
    vault: VaultContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    compose_module.compose_briefing(vault_context=vault, for_date=PAST, write_guard=HEALTHY)
    target = briefing_note_path(vault_context=vault, for_date=PAST)
    note = load_briefing(vault_context=vault, for_date=PAST)
    assert note is not None and note.uuid is not None
    legacy = compose_module._render_note(replace(note, uuid=None))
    target.write_text(legacy, encoding="utf-8")
    expected_version = hashlib.sha256(legacy.encode()).hexdigest()
    observed_versions: list[object] = []
    original_write = compose_module.write_note_relative

    def capture_expected_version(*args: object, **kwargs: object) -> object:
        if kwargs.get("vault_root") == Path(vault.active_vault_path or ""):
            observed_versions.append(kwargs.get("expected_version"))
        return original_write(*args, **kwargs)

    monkeypatch.setattr(compose_module, "write_note_relative", capture_expected_version)
    receipt = migrate_briefing_identity(
        vault_context=vault,
        for_date=PAST,
        write_guard=HEALTHY,
    )
    assert receipt is not None and receipt.outcome == "written"
    assert observed_versions == [expected_version]
    retained = target.parent / "_conflicts"
    assert any(
        candidate.read_text(encoding="utf-8") == legacy
        for candidate in retained.glob("*.md.conflict")
    )

    target.write_text(legacy, encoding="utf-8")

    def edit_before_conditional_write(*args: object, **kwargs: object) -> object:
        if kwargs.get("expected_version") is not None and kwargs.get("vault_root") == Path(
            vault.active_vault_path or ""
        ):
            target.write_text(legacy + "\nowner edit\n", encoding="utf-8")
        return original_write(*args, **kwargs)

    monkeypatch.setattr(compose_module, "write_note_relative", edit_before_conditional_write)
    with pytest.raises(KnowledgeWriteConflict):
        migrate_briefing_identity(vault_context=vault, for_date=PAST, write_guard=HEALTHY)
    assert target.read_text(encoding="utf-8").endswith("owner edit\n")


@pytest.mark.parametrize("authority_drift", ["profile", "symlink"])
def test_daily_briefing_identity_migration_revalidates_authority_at_write_seam(
    vault: VaultContext,
    monkeypatch: pytest.MonkeyPatch,
    authority_drift: str,
) -> None:
    compose_module.compose_briefing(vault_context=vault, for_date=PAST, write_guard=HEALTHY)
    root = Path(vault.active_vault_path or "")
    target = briefing_note_path(vault_context=vault, for_date=PAST)
    note = load_briefing(vault_context=vault, for_date=PAST)
    assert note is not None
    legacy = compose_module._render_note(replace(note, uuid=None))
    target.write_text(legacy, encoding="utf-8")
    proposal = compose_module.prepare_briefing_identity_migration(
        vault_context=vault,
        for_date=PAST,
    )
    assert proposal is not None
    monkeypatch.setattr(
        compose_module,
        "prepare_briefing_identity_migration",
        lambda **_kwargs: proposal,
    )

    foreign: Path | None = None
    if authority_drift == "profile":
        expected_uuid = note_uuid_module.resolve_read_only_derived_uuid(
            target,
            vault_root=root,
        )
        ProfileAuthorityStore(root, profile_note_id=expected_uuid).initialize(
            ProfileIdentityRecord(
                event_id="daily-briefing-profile-drift",
                vault_id="test-vault",
                profile_note_id=expected_uuid,
                note_path=target.relative_to(root).as_posix(),
                initial_content_digest=hashlib.sha256(legacy.encode()).hexdigest(),
            )
        )
    else:
        foreign = root / "foreign.md"
        foreign.write_text(legacy, encoding="utf-8")
        target.unlink()
        target.symlink_to(foreign)

    with pytest.raises(KnowledgeWriteConflict, match="not eligible"):
        migrate_briefing_identity(vault_context=vault, for_date=PAST, write_guard=HEALTHY)

    if foreign is None:
        assert target.read_text(encoding="utf-8") == legacy
    else:
        assert foreign.read_text(encoding="utf-8") == legacy
        assert target.is_symlink()
