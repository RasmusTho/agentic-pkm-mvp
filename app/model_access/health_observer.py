"""Bounded process-local sampling for Product model-access health."""

from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Callable, Mapping


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_observed_at(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


class ProductHealthObserver:
    """Cache raw route observations while bounding duplicate and pending probes."""

    def __init__(
        self,
        *,
        max_workers: int = 2,
        max_in_flight: int = 2,
        max_observations: int = 64,
        max_pending: int = 64,
        refresh_after_seconds: float = 15.0,
        clock: Callable[[], datetime] = _now_utc,
    ) -> None:
        if (
            max_workers < 1
            or max_in_flight < 1
            or max_observations < 1
            or max_pending < 1
        ):
            raise ValueError("health observer bounds must be positive")
        if max_in_flight < max_workers:
            raise ValueError("max_in_flight must be at least max_workers")
        if refresh_after_seconds <= 0:
            raise ValueError("refresh_after_seconds must be positive")
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="product-model-health",
        )
        self._max_in_flight = max_in_flight
        self._max_observations = max_observations
        self._max_pending = max_pending
        self._refresh_after_seconds = refresh_after_seconds
        self._clock = clock
        self._lock = Lock()
        self._observations: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._in_flight: set[str] = set()
        self._pending_cold: OrderedDict[str, Callable[[], Mapping[str, Any]]] = (
            OrderedDict()
        )
        self._pending_refresh: OrderedDict[str, Callable[[], Mapping[str, Any]]] = (
            OrderedDict()
        )

    def observe(
        self,
        key: str,
        sampler: Callable[[], Mapping[str, Any]],
    ) -> dict[str, Any] | None:
        """Return the last raw observation and start a bounded refresh if due."""
        now = self._clock()
        with self._lock:
            observation = self._observations.get(key)
            if observation is not None:
                self._observations.move_to_end(key)
            refresh_due = observation is None or self._refresh_due(observation, now)
            if refresh_due and key not in self._in_flight:
                if key not in self._pending_cold and key not in self._pending_refresh:
                    if len(self._in_flight) < self._max_in_flight:
                        self._submit_locked(key, sampler)
                    else:
                        self._queue_locked(key, sampler, cold=observation is None)
            return deepcopy(observation) if observation is not None else None

    def _submit_locked(
        self,
        key: str,
        sampler: Callable[[], Mapping[str, Any]],
    ) -> None:
        self._in_flight.add(key)
        try:
            self._executor.submit(self._sample, key, sampler)
        except RuntimeError:
            self._in_flight.discard(key)

    def _queue_locked(
        self,
        key: str,
        sampler: Callable[[], Mapping[str, Any]],
        *,
        cold: bool,
    ) -> None:
        pending_size = len(self._pending_cold) + len(self._pending_refresh)
        if pending_size >= self._max_pending:
            if not cold or not self._pending_refresh:
                return
            self._pending_refresh.popitem(last=False)
        pending = self._pending_cold if cold else self._pending_refresh
        pending[key] = sampler

    def _start_pending_locked(self) -> None:
        while len(self._in_flight) < self._max_in_flight:
            pending = self._pending_cold or self._pending_refresh
            if not pending:
                return
            key, sampler = pending.popitem(last=False)
            self._submit_locked(key, sampler)

    def _refresh_due(self, observation: Mapping[str, Any], now: datetime) -> bool:
        observed_at = _parse_observed_at(observation.get("observed_at"))
        if observed_at is None:
            return True
        age = (now.astimezone(timezone.utc) - observed_at).total_seconds()
        return age < 0 or age >= self._refresh_after_seconds

    def _sample(
        self,
        key: str,
        sampler: Callable[[], Mapping[str, Any]],
    ) -> None:
        try:
            raw = sampler()
            completed_at = self._clock().astimezone(timezone.utc).isoformat()
            if not isinstance(raw, Mapping):
                result: dict[str, Any] = {
                    "status": "unknown",
                    "reason_code": "readiness_unknown",
                    "capabilities": {},
                }
            else:
                result = deepcopy(dict(raw))
            result["observed_at"] = completed_at
            transport = result.get("transport_observation")
            if isinstance(transport, dict):
                transport["observed_at"] = completed_at
        except Exception:
            completed_at = self._clock().astimezone(timezone.utc).isoformat()
            result = {
                "status": "unknown",
                "reason_code": "observation_unavailable",
                "observed_at": completed_at,
                "capabilities": {},
                "transport_observation": {
                    "status": "unknown",
                    "reason_code": "transport_unknown",
                    "observed_at": completed_at,
                },
            }
        with self._lock:
            self._observations[key] = result
            self._observations.move_to_end(key)
            self._in_flight.discard(key)
            self._trim_locked()
            self._start_pending_locked()

    def _trim_locked(self) -> None:
        while len(self._observations) > self._max_observations:
            oldest = next(
                (
                    key
                    for key in self._observations
                    if key not in self._in_flight
                    and key not in self._pending_cold
                    and key not in self._pending_refresh
                ),
                None,
            )
            if oldest is None:
                return
            del self._observations[oldest]


PRODUCT_HEALTH_OBSERVER = ProductHealthObserver()


__all__ = ["PRODUCT_HEALTH_OBSERVER", "ProductHealthObserver"]
