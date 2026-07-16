"""Read-only PROD deploy preflight: detect pending outbox rows already at a
terminal retry boundary (#3903).

Two independent outbox retry-budget mechanisms live in
``app/workers/outbox_worker.py``. Both mark a state where the row's very
next processing pass dead-letters it instead of retrying again:

1. **Worker-level transient retry counter.** The re-emitted event payload
   carries ``_worker_retry_count``, stamped by the PRIOR cycle onto the new
   retry row. Once a pending row's payload already shows
   ``_worker_retry_count >= _MAX_TRANSIENT_RETRY_ATTEMPTS`` (3), the next
   transient failure for that row dead-letters immediately instead of being
   re-queued (``_queue_transient_retry``).
2. **Dispatch-attempt crash-loop counter.** The outbox row's own ``attempts``
   column is bumped by ``bump_outbox_attempts`` on every non-transient
   dispatch failure. The worker bumps and then checks/dead-letters/acks in
   the SAME consume cycle (``run()``: bump ~L1764, threshold check ~L1771,
   dead-letter ~L1773, ack ~L1782), so a row observed PENDING between cycles
   tops out at ``attempts == max_dispatch_attempts - 1`` (4 with the default
   budget of 5); ``attempts == max`` is only observable in the milliseconds
   crash window between the bump and the ack. The terminal-boundary
   condition for a pending row is therefore
   ``attempts >= max_dispatch_attempts - 1``: its next non-transient
   dispatch failure dead-letters it. (With ``max_dispatch_attempts <= 1``
   the threshold degenerates to 0 and this mechanism stops discriminating —
   every pending row is at the boundary by definition of a 1-attempt
   budget.)

Row shape: ``app/services/outbox.py::write_outbox_event`` stores the full
``Event`` ENVELOPE in the ``payload`` column (``event_type`` at the top
level, the actual event payload nested under ``"payload"``), while legacy
rows may carry the flat payload dict directly. The worker unwraps this via
``_coerce_event_from_db`` before reading ``_worker_retry_count``, so this
preflight mirrors the same unwrapping (:func:`_pending_row_inner_payload`);
reading only the top level would miss every retry row the current writer
produces — the exact #3124 incident shape.

This is the failure class that let #3124's promotion pass every existing
gate (deploy, health, exact-SHA, embedding, live smoke) while eight
``panel.scan.requested`` rows already at retry-3 silently dead-lettered the
moment the worker restarted.

The script prefers the canonical DSN normalizer (``app.db.dsn.resolve_dsn``)
when the ``app`` package is importable and falls back to inline
normalization otherwise (the same layered pattern as
``app/services/outbox.py::_open_conn``); it never imports the worker module
or any heavy dependency graph at runtime — deploy hosts may run a bare
``python3``. Constant/behavior parity with the worker is enforced by
``tests/scripts/test_prod_deploy_retry_preflight_constants_parity.py``. It
never mutates the outbox (KERNEL-12 read-only invariant) and never prints
event payloads, note/source paths, DSNs, or credentials -- only aggregate
counts and topic/classification labels.

Exit codes:
  0  no terminal-boundary pending rows found (this includes every "cannot
     tell" case -- no DSN configured, the DB unreachable, or the query
     itself failing -- which fails OPEN: DB/outbox availability is a
     separate, already-gated concern, not this check's job).
  1  terminal-boundary pending rows found; the caller (scripts/deploy_channel.sh)
     must not proceed to pin write or Compose mutation.

Usage: ``python scripts/prod_deploy_retry_preflight.py`` (no arguments).
Reads ``DATABASE_URL`` or ``DB_DSN`` from the process environment, same
precedence as ``app/services/outbox.py::_open_conn``; the production caller
(``scripts/deploy_channel.sh::prod_pending_retry_preflight``) sources the
DSN from the channel's governed runtime env file and injects it into THIS
subprocess only. Prints one JSON receipt object to stdout.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# Mirrors app/workers/outbox_worker.py::_MAX_TRANSIENT_RETRY_ATTEMPTS. Kept as
# a literal (not imported) so this preflight stays import-light and does not
# pull in the worker module's full dependency graph; parity with the worker is
# enforced by tests/scripts/test_prod_deploy_retry_preflight_constants_parity.py.
MAX_TRANSIENT_RETRY_ATTEMPTS = 3

# Mirrors app/workers/outbox_worker.py::_MAX_DISPATCH_ATTEMPTS (the default;
# _resolve_max_dispatch_attempts() below mirrors the same
# WORKER_MAX_DISPATCH_ATTEMPTS override the worker itself honors). Same parity
# test as above.
DEFAULT_MAX_DISPATCH_ATTEMPTS = 5

TRANSIENT_RETRY_EXHAUSTED = "transient_retry_exhausted"
DISPATCH_ATTEMPTS_EXHAUSTED = "dispatch_attempts_exhausted"

# Server-side pre-filter so full payloads are only shipped for candidate rows,
# not the whole pending queue (exact classification stays in Python below).
# Guarded on purpose: jsonb_typeof(...) = 'number' never aborts on a
# non-numeric value, unlike a bare (payload->>'_worker_retry_count')::int cast,
# whose failure the caller's fail-open handling would turn into a silent
# full-gate skip. Two retry-counter arms because write_outbox_event stores the
# Event ENVELOPE (counter nested at payload->'payload'->'_worker_retry_count')
# while legacy flat rows carry it at the top level (see module docstring).
PENDING_TERMINAL_CANDIDATES_SQL = (
    "select topic, payload, attempts from outbox "
    "where delivered_at is null "
    "and (attempts >= %(attempts_threshold)s "
    "or jsonb_typeof(payload->'_worker_retry_count') = 'number' "
    "or jsonb_typeof(payload->'payload'->'_worker_retry_count') = 'number')"
)


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
    """DATABASE_URL/DB_DSN precedence as app/services/outbox.py::_open_conn.

    Prefers the canonical normalizer ``app.db.dsn.resolve_dsn`` when the app
    package is importable (repo checkout present), falling back to the inline
    prefix strip otherwise -- the same layered pattern ``_open_conn`` uses.
    The repo root is added to sys.path first because this script is invoked
    by path (sys.path[0] is scripts/, not the repo root).
    """
    url = os.environ.get("DATABASE_URL") or os.environ.get("DB_DSN")
    if not url:
        return None
    try:
        repo_root = str(Path(__file__).resolve().parents[1])
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
        from app.db.dsn import resolve_dsn

        return resolve_dsn(url) or None
    except Exception:
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


def _pending_row_inner_payload(raw_column: Any) -> dict[str, Any]:
    """Unwrap an outbox ``payload`` column value to the event's inner payload.

    Mirrors app/services/outbox.py::_coerce_event_from_db: a dict carrying
    ``event_type`` is the Event ENVELOPE written by write_outbox_event and the
    actual event payload sits under its ``payload`` key; a dict without
    ``event_type`` is a legacy flat payload used directly. Tolerates a
    JSON-string column value the same way the worker's read path does.
    """
    data = raw_column
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (TypeError, ValueError):
            return {}
    if not isinstance(data, dict):
        return {}
    if "event_type" in data:
        inner = data.get("payload")
        return inner if isinstance(inner, dict) else {}
    return data


def _payload_retry_count(payload: Any) -> int:
    """Mirrors app/workers/outbox_worker.py::_payload_retry_count exactly.

    Takes the coerced INNER event payload (see _pending_row_inner_payload),
    matching what the worker itself passes in. Parity is enforced by
    tests/scripts/test_prod_deploy_retry_preflight_constants_parity.py.
    """
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
    ``execute(sql, params)`` and ``fetchall()``. Issues exactly one SELECT;
    never an UPDATE/DELETE (KERNEL-12 read-only invariant). Rows are plain
    tuples: psycopg.connect() is used without a row_factory.
    """
    # A pending row's steady-state ceiling is max - 1: the worker bumps
    # attempts and then dead-letters+acks in the same consume cycle (see
    # module docstring, mechanism 2), so max - 1 IS the terminal boundary
    # for a row observed pending. Non-discriminating when max <= 1
    # (threshold 0 flags every pending row -- honest for a 1-attempt budget).
    attempts_threshold = max_dispatch_attempts - 1

    cur = conn.cursor()
    cur.execute(
        PENDING_TERMINAL_CANDIDATES_SQL,
        {"attempts_threshold": attempts_threshold},
    )
    rows = cur.fetchall()

    by_topic: dict[str, int] = {}
    by_classification = {TRANSIENT_RETRY_EXHAUSTED: 0, DISPATCH_ATTEMPTS_EXHAUSTED: 0}
    terminal_pending_count = 0

    for topic, payload, attempts in rows:
        topic_label = str(topic) if topic else "unknown"
        try:
            attempts_value = int(attempts) if attempts is not None else 0
        except (TypeError, ValueError):
            attempts_value = 0

        inner_payload = _pending_row_inner_payload(payload)
        retry_exhausted = _payload_retry_count(inner_payload) >= MAX_TRANSIENT_RETRY_ATTEMPTS
        dispatch_exhausted = attempts_value >= attempts_threshold
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
            "pending_attempts_threshold": attempts_threshold,
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
