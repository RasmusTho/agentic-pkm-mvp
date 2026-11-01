"""MVR-05D rollout preflight: refuse worker activation over upgrade-stranded rows.

An MVR-05D worker dispatches a live-binding outbox row only when it carries the
complete ``mvr05.outbox-envelope.v1`` envelope. A row that an MVR-05A..05C
worker could still have dispatched -- pending, on the worker's live binding,
with the matching 05A binding stamp -- but that lacks the envelope would stay
pending forever after an upgrade. This preflight is the fail-loud runtime
precondition for that contract.

``app/workers/outbox_worker.py::run`` calls :func:`require_upgrade_drained`
after bootstrap and before its first poll, with the worker's own live binding
stamp. Any such row makes the worker refuse to start (the process exits loud and
its readiness never reports healthy), so the deploy cannot activate an MVR-05D
worker over work only the previous image can deliver. The remedy is to run the
previous image until its worker drains those rows, then redeploy.

The count is deliberately narrow: rows with a stale or foreign binding stamp,
explicitly global, scalar-era compatibility, and quarantined rows are not
counted. The previous image could not deliver those either (or they keep their
MVR-05A treatment), so they never wedge activation. The check is read-only.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from typing import Any

from app.services.outbox_producers import OUTBOX_ENVELOPE_VERSION

PREFLIGHT_SCHEMA = "mvr05d-outbox-envelope-preflight.v1"
BLOCKED_EXIT_CODE = 79

_UPGRADE_STRANDED_SQL = (
    "select count(*) from outbox where delivered_at is null "
    "and vault_binding_id = %s "
    "and payload #>> '{meta,vault_binding_id}' = %s "
    "and payload #>> '{meta,binding_authority}' = %s "
    "and payload #>> '{meta,binding_authorization_epoch}' = %s "
    "and payload #>> '{meta,binding_revision}' = %s "
    "and payload #>> '{meta,vault_root}' = %s "
    "and coalesce(payload #>> '{meta,outbox_envelope}', '') <> %s"
)


class OutboxEnvelopeUpgradeBlocked(RuntimeError):
    """Pending live-binding work predates the envelope and only the old image can drain it."""

    def __init__(self, count: int) -> None:
        self.count = count
        super().__init__(
            "MVR-05D outbox envelope preflight refused worker activation: "
            f"{count} pending live-binding outbox row(s) predate the "
            f"{OUTBOX_ENVELOPE_VERSION} envelope and would never be dispatched. Run the "
            "previous image until its worker drains them, then redeploy "
            "(docs/EVENTS.md :: Outbox consumer contract)."
        )


def count_upgrade_stranded_rows(conn: Any, required_binding_stamp: Mapping[str, object]) -> int:
    """Count pending rows the previous worker could dispatch but this one never will."""

    binding_id = str(required_binding_stamp["vault_binding_id"])
    cur = conn.execute(
        _UPGRADE_STRANDED_SQL,
        (
            binding_id,
            binding_id,
            str(required_binding_stamp["binding_authority"]),
            str(required_binding_stamp["binding_authorization_epoch"]),
            str(required_binding_stamp["binding_revision"]),
            str(required_binding_stamp["vault_root"]),
            OUTBOX_ENVELOPE_VERSION,
        ),
    )
    row = cur.fetchone()
    if row is None:
        return 0
    value = next(iter(row.values()), 0) if isinstance(row, dict) else row[0]
    return int(value or 0)


def evaluate(conn: Any, required_binding_stamp: Mapping[str, object] | None) -> dict[str, Any]:
    if required_binding_stamp is None:
        return {"schema": PREFLIGHT_SCHEMA, "status": "skipped", "reason": "no_binding_runtime"}
    count = count_upgrade_stranded_rows(conn, required_binding_stamp)
    return {
        "schema": PREFLIGHT_SCHEMA,
        "status": "blocked" if count else "ok",
        "upgrade_stranded_pending_count": count,
    }


def require_upgrade_drained(
    required_binding_stamp: Mapping[str, object] | None, *, conn: Any = None
) -> dict[str, Any]:
    """Fail loud before the worker's first poll when upgrade-stranded rows exist."""

    if required_binding_stamp is None:
        return evaluate(conn, None)
    from app.services.outbox import _use_conn

    conn, close = _use_conn(conn)
    try:
        receipt = evaluate(conn, required_binding_stamp)
    finally:
        if close:
            conn.close()
    if receipt["status"] == "blocked":
        raise OutboxEnvelopeUpgradeBlocked(int(receipt["upgrade_stranded_pending_count"]))
    return receipt


def main() -> int:
    """Operator probe: evaluate this process's live binding without starting a worker."""

    from app.instance.scalar_binding_runtime import resolve_scalar_binding_runtime
    from app.workers.outbox_binding_gate import required_worker_binding_stamp

    stamp = required_worker_binding_stamp(resolve_scalar_binding_runtime())
    try:
        receipt = require_upgrade_drained(stamp)
    except OutboxEnvelopeUpgradeBlocked as exc:
        print(json.dumps({"schema": PREFLIGHT_SCHEMA, "status": "blocked",
                          "upgrade_stranded_pending_count": exc.count}, sort_keys=True))
        print(f"ERROR: {exc}", file=sys.stderr)
        return BLOCKED_EXIT_CODE
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
