from __future__ import annotations

import json
from collections import deque
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
CATCH_UP_STATES = {"catch_up", "degraded", "recovery"}
PROCESSING_MODE_IDLE = "idle"
PROCESSING_MODE_REPLAY = "replay"
PROCESSING_MODE_STALLED = "stalled"
INCIDENT_STATES = {"degraded", "safe_mode", "unhealthy"}


@dataclass
class HealthStateMachine:
    state: str = "boot"
    reason: str = "initializing"
    since: datetime = field(default_factory=lambda: datetime.now(UTC))  # noqa: UP017
    bad_counter: int = 0
    good_counter: int = 0

    def reset(self) -> None:
        self.state = "boot"
        self.reason = "initializing"
        self.since = datetime.now(UTC)  # noqa: UP017
        self.bad_counter = 0
        self.good_counter = 0

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
                reason = f"outbox lag {age:.1f}s exceeded {degrade_limit}s"
            else:
                next_state = "catch_up"
                reason = f"catching up (lag {age:.1f}s)"
        elif age < recover_limit:
            self.good_counter += 1
            self.bad_counter = 0
            if self.state in {"degraded", "recovery"}:
                if self.good_counter >= recover_samples:
                    next_state = "running"
                    reason = "outbox lag recovered"
                else:
                    next_state = "recovery"
                    reason = "recovering (lag improving)"
            else:
                next_state = "running"
                reason = "operational"
        else:
            self.bad_counter = 0
            self.good_counter = 0
            next_state = "running"
            reason = "normal"

        if next_state != prev_state or reason != self.reason:
            self.state = next_state
            self.reason = reason
            self.since = now
        return self.state, self.reason, self.since.isoformat()


class HealthContract:
    def __init__(
        self,
        *,
        state_machine: HealthStateMachine | None = None,
        now_fn: Callable[[], datetime] | None = None,
        vault_root_fn: Callable[[], Path] | None = None,
        history_limit: int = 32,
    ):
        self.state_machine = state_machine or HealthStateMachine()
        self.now_fn = now_fn or (lambda: datetime.now(UTC))  # noqa: UP017
        self.vault_root_fn = vault_root_fn or resolve_vault_root
        self._transition_history: deque[dict[str, str]] = deque(maxlen=history_limit)

    def evaluate(self) -> dict[str, Any]:
        now = self.now_fn()
        vault_root = self.vault_root_fn()
        settings_result = load_health_settings(vault_root=vault_root)
        records = read_outbox()
        outbox_count = len(records)
        oldest_ts = self._earliest_timestamp(records)
        age = self._compute_age(oldest_ts, now)
        prev_state = self.state_machine.state
        prev_reason = self.state_machine.reason
        state, reason, since_ts = self.state_machine.update(
            age,
            settings_result.settings.thresholds,
            now=now,
        )
        if state != prev_state or reason != prev_reason:
            self._transition_history.append(
                {"state": state, "reason": reason, "since_ts": since_ts}
            )
        index_result = diagnose_index()
        index_status = self._summary_status(
            index_result.get("issues"), index_result.get("warnings")
        )
        events_status = self._events_status(records)
        errors = self._count_errors(records, now)
        writes_allowed = state not in WRITE_BLOCKED_STATES
        write_guard_reason = None if writes_allowed else reason
        catch_up_progress = self._build_catch_up_progress(
            state,
            outbox_count,
            age,
            writes_allowed,
        )
        suggested_actions = self._build_suggested_actions(
            age,
            settings_result.settings.thresholds,
            writes_allowed,
            index_status,
        )
        history_payload = (
            list(self._transition_history)
            if settings_result.settings.incident_capture.transition_history
            and self._transition_history
            else None
        )
        entered_incident_state = state in INCIDENT_STATES and prev_state != state
        self._maybe_log_incident(
            now,
            entered_incident_state,
            state,
            reason,
            since_ts,
            settings_result,
            outbox_count,
            age,
            index_status,
            events_status,
            writes_allowed,
            write_guard_reason,
            catch_up_progress,
            suggested_actions,
            history_payload,
        )
        payload: dict[str, Any] = {
            "state": state,
            "reason": reason,
            "since_ts": since_ts,
            "outbox_count": outbox_count,
            "outbox_oldest_age_s": age,
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
            "recent_transition_history": history_payload,
        }
        return payload

    def _maybe_log_incident(
        self,
        now: datetime,
        entered_incident_state: bool,
        state: str,
        reason: str,
        since_ts: str,
        settings_result: Any,
        outbox_count: int,
        age: float,
        index_status: str,
        events_status: str,
        writes_allowed: bool,
        write_guard_reason: str | None,
        catch_up_progress: dict[str, Any] | None,
        suggested_actions: list[str],
        history_payload: list[dict[str, str]] | None,
    ) -> None:
        settings = settings_result.settings
        if not entered_incident_state or not settings.incident_capture.enabled:
            return
        entry: dict[str, Any] = {
            "ts": now.isoformat(),
            "state": state,
            "reason": reason,
            "since_ts": since_ts,
            "settings_source": settings_result.source.to_payload(),
            "outbox_count": outbox_count,
            "outbox_oldest_age_s": age,
            "index_doctor_status": index_status,
            "events_doctor_status": events_status,
            "writes_allowed": writes_allowed,
            "write_guard_reason": write_guard_reason,
            "suggested_actions": suggested_actions,
        }
        if catch_up_progress is not None:
            entry["catch_up_progress"] = catch_up_progress
        if history_payload is not None:
            entry["recent_transition_history"] = history_payload
        log_path = settings.incident_log_path
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as out:
                out.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            return

    def _earliest_timestamp(self, records: Iterable[dict[str, Any]]) -> datetime | None:
        earliest: datetime | None = None
        for rec in records:
            value = normalize_timestamp(rec)
            ts = self._parse_timestamp(value)
            if ts is None:
                continue
            if earliest is None or ts < earliest:
                earliest = ts
        return earliest

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

    def _build_catch_up_progress(
        self,
        state: str,
        outbox_count: int,
        age: float,
        writes_allowed: bool,
    ) -> dict[str, Any] | None:
        if state not in CATCH_UP_STATES:
            return None
        return {
            "outbox_count": outbox_count,
            "outbox_oldest_age_s": age,
            "processing_mode": self._processing_mode(state, writes_allowed),
        }

    def _processing_mode(self, state: str, writes_allowed: bool) -> str:
        if not writes_allowed:
            return PROCESSING_MODE_STALLED
        if state in CATCH_UP_STATES:
            return PROCESSING_MODE_REPLAY
        return PROCESSING_MODE_IDLE

    def _build_suggested_actions(
        self,
        age: float,
        thresholds: HealthThresholds,
        writes_allowed: bool,
        index_status: str,
    ) -> list[str]:
        actions: list[str] = []
        if age > thresholds.outbox_degrade_oldest_age_s:
            actions.append("python -m app.cli events doctor --json")
        if index_status in {"warn", "fail"}:
            actions.append("python -m app.cli index doctor --json")
        if not writes_allowed:
            actions.append(
                "python -m app.cli health explain (resolve write guard reason before retrying writes)"
            )
        return actions


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
