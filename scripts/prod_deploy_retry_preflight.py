"""Read-only PROD deploy preflight: detect pending outbox rows already at a
terminal retry boundary (#3903).

Two independent outbox retry-budget mechanisms live in
``app/workers/outbox_worker.py``. Both mark a state where the row's very
next processing pass dead-letters it instead of retrying again:

1. **Worker-level transient retry counter.** The re-emitted event payload
   carries ``_worker_retry_count``. Once a pending row's payload already
   shows ``_worker_retry_count >= _MAX_TRANSIENT_RETRY_ATTEMPTS`` (3), the
   next transient failure for that row dead-letters immediately instead of
   being re-queued (``_queue_transient_retry``).
2. **Dispatch-attempt crash-loop counter.** The outbox row's own ``attempts``
   column is bumped by ``bump_outbox_attempts`` on every non-transient
   dispatch failure. Once a pending row's ``attempts`` already reaches
   ``_MAX_DISPATCH_ATTEMPTS`` (5 by default, ``WORKER_MAX_DISPATCH_ATTEMPTS``
   override), the next non-transient dispatch failure dead-letters
   immediately.

This is the exact failure class that let #3124's promotion pass every
existing gate (deploy, health, exact-SHA, embedding, live smoke) while eight
``panel.scan.requested`` rows already at retry-3 silently dead-lettered the
moment the worker restarted.

This script is intentionally standalone (no ``app.*`` imports): it duplicates
the two threshold constants above with a comment pointing back at the
authoritative source rather than importing the worker module and its full
dependency graph. It never mutates the outbox (KERNEL-12 read-only
invariant) and never prints event payloads, note/source paths, DSNs, or
credentials -- only aggregate counts and topic/classification labels.

Exit codes:
  0  no terminal-boundary pending rows found (this includes every "cannot
     tell" case -- no DSN configured, the DB unreachable, or the query
     itself failing -- which fails OPEN: DB/outbox availability is a
     separate, already-gated concern, not this check's job).
  1  terminal-boundary pending rows found; the caller (scripts/deploy_channel.sh)
     must not proceed to pin write or Compose mutation.

Usage: ``python scripts/prod_deploy_retry_preflight.py`` (no arguments).
Reads ``DATABASE_URL`` or ``DB_DSN`` from the environment, same precedence as
``app/services/outbox.py::_open_conn``. Prints one JSON object to stdout.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

# Mirrors app/workers/outbox_worker.py::_MAX_TRANSIENT_RETRY_ATTEMPTS. Kept as
# a literal (not imported) so this preflight stays import-light and does not
# pull in the worker module's full dependency graph; update both together.
MAX_TRANSIENT_RETRY_ATTEMPTS = 3

# Mirrors app/workers/outbox_worker.py::_MAX_DISPATCH_ATTEMPTS (the default;
# _resolve_max_dispatch_attempts() below mirrors the same
# WORKER_MAX_DISPATCH_ATTEMPTS override the worker itself honors).
DEFAULT_MAX_DISPATCH_ATTEMPTS = 5

TRANSIENT_RETRY_EXHAUSTED = "transient_retry_exhausted"
DISPATCH_ATTEMPTS_EXHAUSTED = "dispatch_attempts_exhausted"


def _resolve_max_dispatch_attempts() -> int:
    raw = os.environ.get("WORKER_MAX_DISPATCH_ATTEMPTS")
    if raw is None:
        return DEFAULT_MAX_DISPATCH_ATTEMPTS
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_DISPATCH_ATTEMPTS
    return value if value >= 1 else DEFAULT_MAX_DISPATCH_ATTEMPTS


def _resolve_dsn() -> str | None:
    """Same precedence and minimal normalization as app/services/outbox.py::_open_conn.

    Deliberately does not import app.db.dsn.resolve_dsn: this script must stay
    importable and runnable independent of the app package and its
    dependency graph (see module docstring).
    """
    url = os.environ.get("DATABASE_URL") or os.environ.get("DB_DSN")
    if not url:
        return None
    if url.startswith("postgresql+psycopg://"):
        return "postgresql://" + url.split("postgresql+psycopg://", 1)[1]
    return url


def _skip(reason: str) -> dict[str, Any]:
    return {
        "status": "skipped",
        "reason": reason,
        "terminal_pending_count": 0,
        "by_topic": {},
        "by_classification": {},
    }


def _payload_retry_count(raw_payload: Any) -> int:
    """Mirrors app/workers/outbox_worker.py::_payload_retry_count."""
    payload = raw_payload
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            return 0
    if not isinstance(payload, dict):
        return 0
    raw = payload.get("_worker_retry_count")
    if raw is None:
        return 0
    try:
        return max(int(raw), 0)
    except (TypeError, ValueError):
        return 0


def evaluate(conn: Any, *, max_dispatch_attempts: int) -> dict[str, Any]:
    """Read-only classification pass over pending outbox rows.

    ``conn`` must expose a DB-API-style ``cursor()`` whose cursor supports
    ``execute(sql)`` and ``fetchall()``. Issues exactly one SELECT; never an
    UPDATE/DELETE (KERNEL-12 read-only invariant).
    """
    cur = conn.cursor()
    cur.execute("select topic, payload, attempts from outbox where delivered_at is null")
    rows = cur.fetchall()

    by_topic: dict[str, int] = {}
    by_classification = {TRANSIENT_RETRY_EXHAUSTED: 0, DISPATCH_ATTEMPTS_EXHAUSTED: 0}
    terminal_pending_count = 0

    for row in rows:
        if isinstance(row, dict):
            topic = row.get("topic")
            payload = row.get("payload")
            attempts = row.get("attempts")
        else:
            topic, payload, attempts = row[0], row[1], row[2]
        topic_label = str(topic) if topic else "unknown"
        try:
            attempts_value = int(attempts) if attempts is not None else 0
        except (TypeError, ValueError):
            attempts_value = 0

        retry_exhausted = _payload_retry_count(payload) >= MAX_TRANSIENT_RETRY_ATTEMPTS
        dispatch_exhausted = attempts_value >= max_dispatch_attempts
        if not (retry_exhausted or dispatch_exhausted):
            continue

        terminal_pending_count += 1
        by_topic[topic_label] = by_topic.get(topic_label, 0) + 1
        if retry_exhausted:
            by_classification[TRANSIENT_RETRY_EXHAUSTED] += 1
        if dispatch_exhausted:
            by_classification[DISPATCH_ATTEMPTS_EXHAUSTED] += 1

    return {
        "status": "blocked" if terminal_pending_count else "ok",
        "reason": None,
        "terminal_pending_count": terminal_pending_count,
        "by_topic": by_topic,
        "by_classification": by_classification,
        "thresholds": {
            "max_transient_retry_attempts": MAX_TRANSIENT_RETRY_ATTEMPTS,
            "max_dispatch_attempts": max_dispatch_attempts,
        },
    }


def main(argv: list[str]) -> int:
    del argv  # no arguments accepted; env-driven like the rest of deploy_channel.sh's gates

    dsn = _resolve_dsn()
    if not dsn:
        result = _skip("no_dsn")
        print(json.dumps(result, sort_keys=True))
        return 0

    try:
        import psycopg
    except Exception:
        result = _skip("psycopg_unavailable")
        print(json.dumps(result, sort_keys=True))
        return 0

    try:
        conn = psycopg.connect(dsn, connect_timeout=5)
    except Exception:
        result = _skip("db_unreachable")
        print(json.dumps(result, sort_keys=True))
        return 0

    try:
        try:
            result = evaluate(conn, max_dispatch_attempts=_resolve_max_dispatch_attempts())
        except Exception:
            result = _skip("outbox_query_failed")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    print(json.dumps(result, sort_keys=True))
    return 1 if result.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
