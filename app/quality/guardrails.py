from __future__ import annotations

import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Any, Callable, Deque, Dict, Iterable


_FORBIDDEN_RE = re.compile(r"(?i)\b(api key|password|secret)\b")


def enforce_quality(
    answer: str,
    sources: Iterable[dict],
    *,
    min_sources: int = 1,
    max_tokens: int = 800,
) -> Dict[str, Any]:
    issues = []
    token_count = len(answer.split())
    if token_count > max_tokens:
        issues.append("too_long")
    if len(list(sources)) < min_sources:
        issues.append("insufficient_sources")
    if _FORBIDDEN_RE.search(answer or ""):
        issues.append("forbidden_content")
    return {"ok": not issues, "issues": issues, "token_count": token_count}


def timeout_wrapper(fn: Callable, seconds: float, *args: Any, **kwargs: Any) -> Any:
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn, *args, **kwargs)
        return future.result(timeout=seconds)


class CircuitBreaker:
    def __init__(self, max_failures: int = 3, window_seconds: int = 60):
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: Deque[float] = deque()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        now = time.time()
        with self._lock:
            while self._failures and now - self._failures[0] > self.window_seconds:
                self._failures.popleft()
            return len(self._failures) < self.max_failures

    def record_failure(self) -> None:
        with self._lock:
            self._failures.append(time.time())

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()


DEFAULT_BREAKER = CircuitBreaker()


__all__ = [
    "enforce_quality",
    "timeout_wrapper",
    "CircuitBreaker",
    "DEFAULT_BREAKER",
]
