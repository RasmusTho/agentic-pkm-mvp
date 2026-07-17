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

DSN resolution (#3903 round 4): the effective DATABASE_URL/DB_DSN a running
prod service actually binds to is a Compose layering question, NOT something
this script may re-derive from pin/env files by hand -- rounds 2 and 3 tried
exactly that and both were wrong, because Compose's own rule (documented at
``docker-compose.dev.yml:29`` and ``docs/RELEASE_CHANNELS/README.md``
:: Compose/env binding invariant) is that a service's ``environment:`` block
always wins over its ``env_file:`` chain for the same key, and
``docker-compose.prod.yml`` sets ``DATABASE_URL``/``DB_DSN`` directly in
``environment:`` for every channel-critical service. This script instead
calls the one purpose-built, tested resolver for this exact precedence puzzle
-- ``app.release_channels.channel_isolation_preflight.resolve_effective_dsn``
-- against the real ``docker-compose.prod.yml`` (+ base ``docker-compose.yaml``),
asking it "what does the prod worker service actually bind to" rather than
reconstructing the answer independently. That resolver is read-only, no
Docker, no network (pure YAML + env_file text), and its own module docstring
documents the identical environment-vs-env_file precedence this script must
never re-derive.

The resolved value names the Compose-internal service hostname (``db``) in
the normal case, which is not reachable from the host this script runs on
(it runs alongside ``docker compose`` invocations, not inside the Compose
network). :func:`_host_reachable_dsn` translates ONLY that specific,
known-stable address to the host-published port
(``docker-compose.yaml``'s ``db`` service publishes ``15432:5432``, and
``docker-compose.prod.yml`` does not override it) -- any other resolved host
(e.g. an explicit ambient ``DATABASE_URL``/``DB_DSN`` override, which Compose
interpolation also honors and which already names something host-reachable)
is left untouched. This is a narrow connectivity bridge, not a second attempt
at precedence resolution.

Retry-budget constant/behavior parity with the worker is enforced by
``tests/scripts/test_prod_deploy_retry_preflight_constants_parity.py``. This
script never mutates the outbox (KERNEL-12 read-only invariant) and never
prints event payloads, note/source paths, DSNs, or credentials -- only
aggregate counts and topic/classification labels.

Exit codes:
  0  no terminal-boundary pending rows found (this includes every "cannot
     tell" case -- no DSN resolvable, the DB unreachable, or the query
     itself failing -- which fails OPEN: DB/outbox availability is a
     separate, already-gated concern, not this check's job).
  1  terminal-boundary pending rows found; the caller (scripts/deploy_channel.sh)
     must not proceed to pin write or Compose mutation.

Usage: ``python scripts/prod_deploy_retry_preflight.py`` (no arguments).
Resolves DATABASE_URL/DB_DSN via ``channel_isolation_preflight.resolve_effective_dsn``
against ``docker-compose.prod.yml``, using this process's own environment as
the Compose interpolation source (matching what the real ``docker compose``
invocation from the same shell would see). Prints one JSON receipt object to
stdout.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

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


# The prod service this preflight asks channel_isolation_preflight about.
# api/worker/watcher/heimdal-capture-watch all carry identical DATABASE_URL/
# DB_DSN bindings in docker-compose.prod.yml; "worker" is the actual outbox
# consumer, matching this issue's own framing.
PROD_DSN_SERVICE = "worker"

# docker-compose.yaml's `db` service Compose-internal DNS name, and the host
# port it publishes that container's 5432 to (`ports: ["15432:5432"]`;
# docker-compose.prod.yml does not override it). See _host_reachable_dsn.
_COMPOSE_INTERNAL_DB_HOST = "db"
_PROD_DB_HOST_PUBLISHED_PORT = "15432"


def _repo_root() -> Path:
    # This script is invoked by path (sys.path[0] is scripts/, not the repo
    # root), so the repo root is added to sys.path explicitly before any
    # `app.*` import.
    root = Path(__file__).resolve().parents[1]
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return root


def _parse_simple_env_file(path: Path) -> dict[str, str]:
    """Minimal ``KEY=VALUE`` parser for the channel pin file.

    Mirrors the pin file's own writer (``write_pin()`` in
    ``scripts/deploy_channel.sh``, which only ever emits a leading comment
    plus ``KEY=VALUE`` lines) and is a close enough model of Compose's
    ``--env-file`` interpolation-source format for this narrow, read-only
    need: comments (``#``) and blank lines are skipped, and a bare ``KEY``
    line (no ``=``) is skipped rather than treated as an empty-string
    contribution. This is deliberately not the full ``env_file:`` CHAIN
    semantics ``channel_isolation_preflight.py`` implements (bare-key-as-
    winning-unset, required-layer fail-closed, multi-layer precedence) --
    ``--env-file`` is a flat interpolation source, not a layered container
    env injection, and the pin file is a single file, not a chain.
    """
    result: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return result
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, value = stripped.partition("=")
        if not sep:
            continue
        key = key.strip()
        if key:
            result[key] = value.strip()
    return result


def _interpolation_environ(repo_root: Path) -> dict[str, str] | None:
    """The real interpolation-source layering for the prod channel's Compose
    invocation, for ``resolve_effective_dsn``'s ``environ=`` parameter.

    ``scripts/lib/deploy_channel_compose.sh`` invokes
    ``docker compose --env-file "${channel_env_file}" ...`` -- the channel
    pin file (``config/deploy/prod.env``) is a genuine Compose interpolation
    source for ``docker-compose.prod.yml``'s ``${DATABASE_URL:-default}``
    expression, not just the ambient shell environment. Compose's own
    precedence is: shell environment wins over ``--env-file``, but
    ``--env-file`` still contributes when the shell does not set a key -- so
    the pin file's values are layered UNDER ``os.environ`` here, matching
    that order exactly (``os.environ`` applied last, on top).

    Committed pin files carry only ``APP_IMAGE_*`` keys today, so this is
    currently a no-op overlay of ``os.environ`` in practice. But nothing
    prevents an operator adding ``DATABASE_URL``/``DB_DSN`` to the pin file
    directly: ``write_pin()`` only strips ``APP_IMAGE_*`` keys on rewrite,
    preserving every other key untouched -- the exact mechanism
    ``WATCHER_RUNTIME_ENV_FILE``/``VAULT_HOST_ROOT`` already use to persist
    there. If that ever happens, the real ``docker compose`` invocation
    honors it; this preflight must resolve identically, or it silently
    inspects a different database than the one the real deploy targets --
    the same failure class rounds 1-4 fixed, one layer deeper (#3903 round 6).

    Returns ``None`` (matching ``resolve_effective_dsn``'s own ``os.environ``
    default) when the pin file cannot be read or is empty, so a missing pin
    file never narrows the interpolation source available to a normal run.
    """
    pin_path = repo_root / "config" / "deploy" / "prod.env"
    if not pin_path.is_file():
        return None
    pin_values = _parse_simple_env_file(pin_path)
    if not pin_values:
        return None
    merged = dict(pin_values)
    merged.update(os.environ)
    return merged


def _resolve_prod_dsn() -> str | None:
    """The effective DATABASE_URL/DB_DSN the real prod worker service binds to.

    Delegates entirely to
    ``app.release_channels.channel_isolation_preflight.resolve_effective_dsn``
    against the committed ``docker-compose.prod.yml`` (+ base
    ``docker-compose.yaml``), with the ``environ=`` override from
    :func:`_interpolation_environ` so the pin file's own ``--env-file``
    contribution is consulted exactly like the real deploy consults it -- see
    the module docstring for why this must not be re-derived by hand. Tries
    ``DATABASE_URL`` then ``DB_DSN``, matching
    ``app/services/outbox.py::_open_conn``'s own key precedence; both are
    bound to the identical expression in docker-compose.prod.yml, so this only
    matters if a future overlay edit ever splits them. Returns ``None`` when
    neither key is resolvable/verifiable (see resolve_effective_dsn's own
    docstring for what that covers) or when the compose files/module cannot
    be loaded at all (e.g. this script copied out of a full repo checkout).
    """
    try:
        repo_root = _repo_root()
        from app.release_channels.channel_isolation_preflight import (
            resolve_effective_dsn,
        )

        compose_path = repo_root / "docker-compose.prod.yml"
        if not compose_path.is_file():
            return None
        environ = _interpolation_environ(repo_root)
        for key in ("DATABASE_URL", "DB_DSN"):
            value = resolve_effective_dsn(compose_path, PROD_DSN_SERVICE, key, environ=environ)
            if value:
                return value
        return None
    except Exception:
        return None


def _host_reachable_dsn(dsn: str) -> str:
    """Translate the Compose-internal `db` address to its host-published port.

    This preflight runs on the host invoking `docker compose`, not inside the
    Compose network, so a resolved DSN naming the internal service hostname
    `db` is not connectable as-is. Only that specific, known-stable address is
    rewritten (see the constants above); any other resolved host -- e.g. an
    explicit ambient DATABASE_URL/DB_DSN override, which Compose interpolation
    also honors and which already names something host-reachable -- is left
    untouched. This is a connectivity bridge, not a second precedence
    resolution: the DSN's value (credentials, dbname, query string) already
    came from resolve_effective_dsn and is never re-derived here.
    """
    try:
        parts = urlsplit(dsn)
    except ValueError:
        return dsn
    if parts.hostname != _COMPOSE_INTERNAL_DB_HOST:
        return dsn
    userinfo = ""
    if parts.username:
        userinfo = parts.username
        if parts.password:
            userinfo += f":{parts.password}"
        userinfo += "@"
    netloc = f"{userinfo}127.0.0.1:{_PROD_DB_HOST_PUBLISHED_PORT}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


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

    dsn = _resolve_prod_dsn()
    if not dsn:
        result = _skip("no_dsn")
        print(json.dumps(result, sort_keys=True))
        return 0
    dsn = _host_reachable_dsn(dsn)

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
