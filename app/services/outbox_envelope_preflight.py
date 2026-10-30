"""MVR-05D rollout preflight: refuse runtime activation over pre-envelope work.

An MVR-05D worker dispatches a live-binding outbox row only when it carries the
complete ``mvr05.outbox-envelope.v1`` envelope. Rows written by an MVR-05A..05C
runtime carry only the 05A binding stamp, so after an upgrade they would stay
pending forever (fail-closed, ``blocked_pending_mvr06``). This preflight is the
fail-loud runtime precondition for that contract: it counts undelivered
live-binding rows without the envelope and refuses activation while any exist.

It runs in ``scripts/run_migrations.sh``, the one-shot ``migrate`` authority
that every Compose runtime service depends on, so no MVR-05D API/worker/watcher
starts over incompatible pending work. Migration-bearing deploys run it after
``scripts/deploy_channel.sh :: apply_changed_migrations`` has stopped every
runtime writer, i.e. under producer quiescence. The check is read-only; the
remedy is to let the previous image's worker drain the rows (roll back, drain,
redeploy), never to rewrite or acknowledge them here.

Explicitly global, scalar-era compatibility, and quarantined rows are outside
the check: global and compatibility rows keep their MVR-05A treatment, and the
quarantine marker never dispatches.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from app.instance.binding_ids import (
    COMPATIBILITY_BINDING_ID,
    OUTBOX_GLOBAL_BINDING_ID,
    OUTBOX_QUARANTINE_BINDING_ID,
)
from app.services.outbox_producers import OUTBOX_ENVELOPE_VERSION

PREFLIGHT_SCHEMA = "mvr05d-outbox-envelope-preflight.v1"
BLOCKED_EXIT_CODE = 79

_INCOMPATIBLE_PENDING_SQL = (
    "select count(*) from outbox where delivered_at is null "
    "and vault_binding_id not in (%s, %s, %s) "
    "and coalesce(payload #>> '{meta,outbox_envelope}', '') <> %s"
)


def _fetch_one(conn: Any, sql: str, params: tuple = ()) -> Any:
    cur = conn.execute(sql, params)
    return cur.fetchone()


def _first(row: Any) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()), None)
    return row[0]


def evaluate(conn: Any) -> dict[str, Any]:
    """Return the preflight receipt for one database connection (read-only)."""

    oid = _first(_fetch_one(conn, "select to_regclass('outbox')::oid"))
    if not oid:
        return {"schema": PREFLIGHT_SCHEMA, "status": "skipped", "reason": "outbox_absent"}
    column = _fetch_one(
        conn,
        "select 1 from pg_attribute where attrelid = %s and attname = 'vault_binding_id' "
        "and attnum > 0 and not attisdropped",
        (oid,),
    )
    if column is None:
        # Pre-MVR-05A schema: every row is scalar-era and the migration
        # classifies it as compatibility work, which keeps 05A treatment.
        return {"schema": PREFLIGHT_SCHEMA, "status": "skipped", "reason": "pre_binding_schema"}
    count = int(
        _first(
            _fetch_one(
                conn,
                _INCOMPATIBLE_PENDING_SQL,
                (
                    COMPATIBILITY_BINDING_ID,
                    OUTBOX_GLOBAL_BINDING_ID,
                    OUTBOX_QUARANTINE_BINDING_ID,
                    OUTBOX_ENVELOPE_VERSION,
                ),
            )
        )
        or 0
    )
    return {
        "schema": PREFLIGHT_SCHEMA,
        "status": "blocked" if count else "ok",
        "incompatible_pending_count": count,
    }


def main() -> int:
    import psycopg

    from app.db.dsn import resolve_dsn

    dsn = resolve_dsn()
    if not dsn:
        print(json.dumps({"schema": PREFLIGHT_SCHEMA, "status": "skipped", "reason": "no_database"}))
        return 0
    with psycopg.connect(dsn, autocommit=True) as conn:
        receipt = evaluate(conn)
    print(json.dumps(receipt, sort_keys=True))
    if receipt["status"] == "blocked":
        print(
            "ERROR: MVR-05D outbox envelope preflight blocked runtime activation: "
            f"{receipt['incompatible_pending_count']} pending live-binding outbox row(s) "
            "predate the mvr05.outbox-envelope.v1 envelope and would never be dispatched. "
            "Run the previous image until its worker drains them, then redeploy "
            "(docs/EVENTS.md :: Outbox consumer contract).",
            file=sys.stderr,
        )
        return BLOCKED_EXIT_CODE
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through run_migrations.sh
    raise SystemExit(main())
