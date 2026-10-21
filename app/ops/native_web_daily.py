"""Fixed current-day producer/version observer in the actual Product API heap."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import hashlib
from importlib import import_module
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app.ops.native_web_acceptance import NativeWebRefusal, hash_json


class DailyBriefingState:
    def __init__(self, vault: Path, effects: dict[str, dict[str, int]]) -> None:
        from app.briefing.config import BRIEFING_TIMEZONE
        from app.briefing.compose import briefing_note_path
        from app.vault.manager import get_vault_manager
        self.vault, self.effects = vault, effects
        self.context = get_vault_manager().context
        if Path(self.context.active_vault_path or '').resolve() != vault.resolve():
            raise NativeWebRefusal('daily_selected_fixture_unknown')
        self.timezone = BRIEFING_TIMEZONE
        self.day = datetime.now(ZoneInfo(self.timezone)).date()
        self.path = briefing_note_path(vault_context=self.context, for_date=self.day).relative_to(vault).as_posix()
        self.version: str | None = None
        self.healthy_version: str | None = None
        self.pending: dict[str, Any] | None = None
        self.active: dict[str, Any] | None = None
        self.contacts: dict[str, Any] = {}
        self.scheduled: dict[str, Any] | None = None
        self.gateway_replays = 0
        self.require_current()  # Pre-existing dated notes cannot be fresh proof.

    def require_current(self, *, present: bool = False) -> None:
        if datetime.now(ZoneInfo(self.timezone)).date() != self.day:
            raise NativeWebRefusal('daily_fixture_date_changed')
        path = self.vault / self.path
        if path.is_symlink():
            raise NativeWebRefusal('daily_briefing_identity_unknown')
        if self.version is None:
            if path.exists() or present:
                raise NativeWebRefusal('daily_fresh_generation_required')
        elif not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != self.version:
            raise NativeWebRefusal('daily_briefing_version_drift')

    def expected_bytes(self) -> bytes:
        # Read-only use of the same finite canonical readers and renderer as
        # compose_briefing. These bytes are an assertion, never written/served.
        composer = import_module('app.briefing.compose')
        from app.vault.paths import get_vault_system_dir_rel
        system = get_vault_system_dir_rel(self.vault)
        sections = {
            'commitments': composer._read_section(lambda: composer._read_commitments(vault_context=self.context, vault_root=self.vault)),
            'moments': composer._read_section(lambda: composer._read_moments(vault_context=self.context, system_dir=system)),
            'decision_receipts': composer._read_section(lambda: composer._read_decision_receipts(vault_root=self.vault, system_dir=system, for_date=self.day)),
            'calendar_episodes': composer._read_section(lambda: composer._read_calendar_episodes(vault_root=self.vault, for_date=self.day)),
        }
        from app.services.note_uuid import resolve_read_only_derived_uuid
        note = composer.BriefingNote(
            briefing_date=self.day,
            degraded_sections=tuple(
                name for name in composer.SECTION_ORDER if sections[name].status == 'degraded'
            ),
            sections=sections,
            uuid=resolve_read_only_derived_uuid(
                self.vault / self.path,
                vault_root=self.vault,
            ),
        )
        return composer._render_note(note).encode()

    def grant(self, effect: str) -> None:
        if effect not in {'first_contact', 'navigation'}:
            return
        index = self.effects['daily-briefing'][effect]
        if index not in (range(1, 3) if effect == 'first_contact' else range(1, 5)):
            raise NativeWebRefusal('daily_contact_without_budget')
        key = effect + ':' + str(index)
        if self.pending is not None or key in self.contacts:
            raise NativeWebRefusal('daily_contact_grant_replayed')
        self.require_current(present=effect == 'navigation' or index != 1)
        if effect == 'first_contact' and index == 1 and self.version is not None:
            raise NativeWebRefusal('daily_fresh_generation_required')
        self.pending = {'key': key, 'effect': effect, 'index': index, 'pre_sha256': self.version}

    def begin_contact(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.require_current()
        if payload or self.active is not None:
            raise NativeWebRefusal('daily_first_contact_request_unknown')
        if self.version is None and (self.pending is None or self.pending['key'] != 'first_contact:1'):
            raise NativeWebRefusal('daily_unadmitted_generation')
        admitted = {'pre_sha256': self.version, 'grant': self.pending}
        self.active = admitted
        return admitted

    def observe_contact(self, response: dict[str, Any], admitted: dict[str, Any]) -> None:
        if admitted is not self.active or response.get('date') != self.day.isoformat():
            raise NativeWebRefusal('daily_first_contact_acknowledgement_unknown')
        path = self.vault / self.path
        if path.is_symlink() or not path.is_file():
            raise NativeWebRefusal('daily_first_contact_artifact_missing')
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        fresh = admitted['pre_sha256'] is None
        if fresh:
            if response.get('triggered') is not True or response.get('reason') != 'first_contact' or raw != self.expected_bytes():
                raise NativeWebRefusal('daily_first_contact_poststate_unknown')
            self.version = self.healthy_version = digest
        elif (response.get('triggered') is not False or response.get('reason') != 'already_generated_today'
              or digest != admitted['pre_sha256']):
            raise NativeWebRefusal('daily_replay_changed_artifact')
        from app.briefing.compose import load_briefing
        note = load_briefing(vault_context=self.context, for_date=self.day)
        record = {'target': self.path, 'date': self.day.isoformat(), 'pre_sha256': admitted['pre_sha256'],
                  'post_sha256': digest, 'triggered': fresh, 'reason': response['reason'],
                  'response_sha256': hash_json(response), 'degraded_sections': list(note.degraded_sections) if note else None}
        if admitted['grant'] is not None:
            self.contacts[admitted['grant']['key']] = record
            self.pending = None
        else:
            self.gateway_replays += 1
            if self.gateway_replays > 256:
                raise NativeWebRefusal('daily_gateway_replay_over_budget')
        self.active = None

    def regenerate(self, require_sources: Callable[[], None]) -> dict[str, Any]:
        from app.briefing.compose import load_briefing
        from app.briefing.trigger import regenerate_briefing
        from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard
        self.require_current(present=True)
        prior = self.version
        expected = self.expected_bytes()
        self.require_current(present=True)  # Reader-to-producer drift refuses.
        def version_bound_snapshot() -> dict[str, Any]:
            # The normal composer reads its CAS token internally. Bind its
            # actual guard-at-write seam to the previously admitted version,
            # so a later reader cannot absorb an intervening owner edit.
            require_sources()
            self.require_current(present=True)
            return dict(DEFAULT_WRITE_GUARD.snapshot_fn())
        guarded = WriteGuard(version_bound_snapshot, bootstrap_actions=DEFAULT_WRITE_GUARD.bootstrap_actions)
        result = regenerate_briefing(vault_context=self.context, for_date=self.day, write_guard=guarded)
        receipt = result.receipt
        raw = (self.vault / self.path).read_bytes()
        if (not result.triggered or result.reason != 'manual_regenerate' or result.briefing_date != self.day
            or receipt is None or receipt.operation != 'write_note' or receipt.outcome != 'written'
            or receipt.locator.path != self.path or raw != expected):
            raise NativeWebRefusal('daily_regeneration_not_acknowledged')
        note = load_briefing(vault_context=self.context, for_date=self.day)
        self.version = hashlib.sha256(raw).hexdigest()
        return {'receipt': asdict(receipt), 'target': self.path, 'pre_sha256': prior, 'post_sha256': self.version,
                'degraded_sections': list(note.degraded_sections) if note else None}

    def scheduled_replay(self) -> dict[str, Any]:
        from app.briefing.config import BRIEFING_GENERATION_HOUR
        from app.briefing.trigger import scheduled_briefing_tick
        self.require_current(present=True)
        if self.scheduled is not None:
            raise NativeWebRefusal('daily_scheduled_replay_duplicate')
        prior = self.version
        now = datetime.combine(self.day, datetime.min.time(), tzinfo=ZoneInfo(self.timezone)).replace(hour=BRIEFING_GENERATION_HOUR)
        result = scheduled_briefing_tick(vault_context=self.context, now=now)
        self.require_current(present=True)
        if result.triggered or result.reason != 'already_generated_today' or result.receipt is not None:
            raise NativeWebRefusal('daily_scheduled_replay_changed_artifact')
        self.scheduled = {'target': self.path, 'date': self.day.isoformat(), 'triggered': False,
                          'reason': result.reason, 'briefing_sha256': prior, 'durable_writes': 0}
        return self.scheduled

    def require_restored(self) -> None:
        self.require_current()
        if self.version != self.healthy_version:
            raise NativeWebRefusal('daily_generated_artifact_restore_incomplete')

    def snapshot(self) -> dict[str, Any]:
        return {'target': self.path, 'date': self.day.isoformat(), 'initial_absent': True,
                'version': self.version, 'healthy_version': self.healthy_version, 'contacts': self.contacts,
                'scheduled_replay': self.scheduled, 'gateway_replays': self.gateway_replays}
