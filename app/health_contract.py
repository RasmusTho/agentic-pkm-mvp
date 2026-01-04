from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.config.paths import resolve_vault_root
from app.events.outbox import event_name, latest_trace_story, normalize_timestamp, read_outbox
from app.index.doctor import diagnose_index
from app.settings.health_settings import HealthThresholds, load_health_settings

WRITE_BLOCKED_STATES = {"safe_mode", "unhealthy"}
INCIDENT_STATES = {"degraded", "unhealthy", "safe_mode"}


def _transition_entry(state: str, reason: str, since: datetime) -> dict[str, str]:
    return {
        "state": state,
        "reason": reason,
        "since_ts": since.isoformat(),
    }


@dataclass
class HealthStateMachine:
    state: str = "boot"
    reason: str = "initializing"
    since: datetime = field(default_factory=lambda: datetime.now(UTC))  # noqa: UP017
    bad_counter: int = 0
    good_counter: int = 0
    transition_history: list[dict[str, str]] = field(default_factory=list)

    def reset(self) -> None:
        self.state = "boot"
        self.reason = "initializing"
        self.since = datetime.now(UTC)  # noqa: UP017
        self.bad_counter = 0
        self.good_counter = 0
        self.transition_history = []

    def update(
        self,
        age: float,
        thresholds: HealthThresholds,
        *,
        now: datetime | None = None,
    ) -> tuple[str, str, str]:
        now = now or datetime.now(UTC)  # noqa: UP017
        prev_state = self.state
        next_state = self.state
        reason = self.reason
        degrade_limit = thresholds.outbox_degrade_oldest_age_s
        recover_limit = thresholds.outbox_recover_oldest_age_s
        degrade_samples = thresholds.degrade_samples
        recover_samples = thresholds.recover_samples

        if age > degrade_limit:
            self.bad_counter += 1
            self.good_counter = 0
            if self.bad_counter >= degrade_samples:
                next_state = "degraded"
                reason = f"outbox idle, last event {age:.1f}s ago"
            else:
                next_state = "catch_up"
                reason = f"catching up (last event {age:.1f}s ago)"
        elif age < recover_limit:
            self.good_counter += 1
            self.bad_counter = 0
            if self.state in {"degraded", "recovery"}:
                if self.good_counter >= recover_samples:
                    next_state = "running"
                    reason = "outbox activity recovered"
                else:
                    next_state = "recovery"
                    reason = "recovering (activity improving)"
            else:
                next_state = "running"
                reason = "recent activity"
        else:
            self.bad_counter = 0
            self.good_counter = 0
            next_state = "running"
            reason = "recent activity"

        if next_state != prev_state:
            self.state = next_state
            self.reason = reason
            self.since = now
            self._record_transition()
        return self.state, self.reason, self.since.isoformat()

    def _record_transition(self) -> None:
        entry = _transition_entry(self.state, self.reason, self.since)
        self.transition_history.insert(0, entry)
        if len(self.transition_history) > 20:
            self.transition_history = self.transition_history[:20]


class HealthContract:
    def __init__(
        self,
        *,
        state_machine: HealthStateMachine | None = None,
        now_fn: Callable[[], datetime] | None = None,
        vault_root_fn: Callable[[], Path] | None = None,
    ):
        self.state_machine = state_machine or HealthStateMachine()
        self.now_fn = now_fn or (lambda: datetime.now(UTC))  # noqa: UP017
        self.vault_root_fn = vault_root_fn or resolve_vault_root

    def evaluate(self) -> dict[str, Any]:
        now = self.now_fn()
        vault_root = self.vault_root_fn()
        settings_result = load_health_settings(vault_root=vault_root)
        records = read_outbox()
        outbox_count = len(records)
        latest_ts = self._latest_timestamp(records)
        age = self._compute_age(latest_ts, now)
        prev_state = self.state_machine.state
        state, reason, since_ts = self.state_machine.update(
            age,
            settings_result.settings.thresholds,
            now=now,
        )
        catch_up_progress = self._catch_up_progress(
            outbox_count,
            age,
            settings_result.settings.thresholds,
        )
        index_result = diagnose_index()
        index_status = self._summary_status(
            index_result.get("issues"),
            index_result.get("warnings"),
        )
        events_status = self._events_status(records)
        errors = self._count_errors(records, now)
        writes_allowed = state not in WRITE_BLOCKED_STATES
        write_guard_reason = None if writes_allowed else reason
        suggested_actions = self._suggested_actions(age, index_status, writes_allowed)

        if settings_result.settings.incident_capture.enabled:
            transitioned = state != prev_state
            if transitioned and state in INCIDENT_STATES:
                    self._append_incident_log(
                        path=settings_result.settings.incident_log_path,
                        entry=self._incident_entry(
                            now=now,
                            state=state,
                            reason=reason,
                            since_ts=since_ts,
                            settings_result=settings_result,
                            outbox_count=outbox_count,
                            outbox_recent_age_s=age,
                            index_status=index_status,
                            events_status=events_status,
                            writes_allowed=writes_allowed,
                            write_guard_reason=write_guard_reason,
                            catch_up_progress=catch_up_progress,
                            suggested_actions=suggested_actions,
                        ),
                    )

        result = {
            "state": state,
            "reason": reason,
            "since_ts": since_ts,
            "outbox_count": outbox_count,
            "outbox_recent_age_s": age,
            "embedding_identity": {
                "backend": index_result.get("backend"),
                "expected_identity": index_result.get("expected_identity"),
                "stored_identity": index_result.get("stored_identity"),
            },
            "index_doctor_status": index_status,
            "events_doctor_status": events_status,
            "errors_last_10m": errors,
            "settings_status": settings_result.status,
            "settings_source": settings_result.source.to_payload(),
            "settings_errors": settings_result.errors,
            "thresholds": settings_result.settings.thresholds.to_payload(),
            "writes_allowed": writes_allowed,
            "write_guard_reason": write_guard_reason,
            "catch_up_progress": catch_up_progress,
            "suggested_actions": suggested_actions,
        }
        if settings_result.settings.incident_capture.transition_history:
            result["recent_transition_history"] = list(self.state_machine.transition_history)
        return result

    def _latest_timestamp(self, records: Iterable[dict[str, Any]]) -> datetime | None:
        latest: datetime | None = None
        for rec in records:
            value = normalize_timestamp(rec)
            ts = self._parse_timestamp(value)
            if ts is None:
                continue
            if latest is None or ts > latest:
                latest = ts
        return latest

    def _compute_age(self, ts: datetime | None, now: datetime) -> float:
        if ts is None:
            return 0.0
        delta = now - ts
        return max(delta.total_seconds(), 0.0)

    def _parse_timestamp(self, value: str) -> datetime | None:
        if not value:
            return None
        text = value.strip()
        if text.endswith("Z") and not text.endswith("+00:00"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text)
        except Exception:
            return None

    def _summary_status(self, issues: Any, warnings: Any) -> str:
        if issues:
            return "fail"
        if warnings:
            return "warn"
        return "pass"

    def _events_status(self, records: Iterable[dict[str, Any]]) -> str:
        rows = list(records)
        if not rows:
            return "warn"
        story = latest_trace_story(rows)
        if story.get("count", 0) > 0:
            return "pass"
        return "warn"

    def _count_errors(self, records: Iterable[dict[str, Any]], now: datetime) -> int | None:
        cutoff = now - timedelta(minutes=10)
        errors = 0
        seen = False
        for rec in records:
            seen = True
            ts = self._parse_timestamp(normalize_timestamp(rec))
            if ts is None:
                continue
            if ts < cutoff:
                continue
            name = event_name(rec).lower()
            if "error" in name:
                errors += 1
        return errors if seen else None

    def _catch_up_progress(
        self,
        outbox_count: int,
        outbox_recent_age_s: float,
        thresholds: HealthThresholds,
    ) -> dict[str, Any] | None:
        if outbox_count <= 0:
            mode = "idle"
        elif outbox_recent_age_s > thresholds.outbox_degrade_oldest_age_s:
            mode = "replay"
        elif outbox_recent_age_s > thresholds.outbox_recover_oldest_age_s:
            mode = "stalled"
        else:
            mode = "idle"
        return {
            "outbox_count": outbox_count,
            "outbox_recent_age_s": outbox_recent_age_s,
            "processing_mode": mode,
        }

    def _suggested_actions(self, age: float, index_status: str, writes_allowed: bool) -> list[str]:
        actions: list[str] = []
        if age > 0:
            actions.append("python -m app.cli events-doctor --path $INDEX_OUTBOX_PATH")
        if index_status in {"warn", "fail"}:
            actions.append("python -m app.cli index doctor --json")
        if not writes_allowed:
            actions.append("python -m app.cli health status --json")
        return actions

    def _incident_entry(
        self,
        *,
        now: datetime,
        state: str,
        reason: str,
        since_ts: str,
        settings_result: Any,
        outbox_count: int,
        outbox_recent_age_s: float,
        index_status: str,
        events_status: str,
        writes_allowed: bool,
        write_guard_reason: str | None,
        catch_up_progress: dict[str, Any] | None,
        suggested_actions: list[str],
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "ts": now.isoformat(),
            "state": state,
            "reason": reason,
            "since_ts": since_ts,
            "settings_source": settings_result.source.to_payload(),
            "outbox_count": outbox_count,
            "outbox_recent_age_s": outbox_recent_age_s,
            "index_doctor_status": index_status,
            "events_doctor_status": events_status,
            "writes_allowed": writes_allowed,
            "write_guard_reason": write_guard_reason,
            "catch_up_progress": catch_up_progress,
            "suggested_actions": suggested_actions,
        }
        if settings_result.settings.incident_capture.transition_history:
            entry["recent_transition_history"] = list(self.state_machine.transition_history)
        return entry

    def _append_incident_log(self, *, path: Path, entry: dict[str, Any]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False))
                handle.write("\n")
        except Exception:
            return


GLOBAL_STATE_MACHINE = HealthStateMachine()
DEFAULT_CONTRACT = HealthContract(state_machine=GLOBAL_STATE_MACHINE)


def reset_state_machine() -> None:
    GLOBAL_STATE_MACHINE.reset()


__all__ = [
    "HealthStateMachine",
    "GLOBAL_STATE_MACHINE",
    "DEFAULT_CONTRACT",
    "HealthContract",
    "reset_state_machine",
]
