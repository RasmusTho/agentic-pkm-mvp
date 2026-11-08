"""MVR-06D: atomic recoverable PostgreSQL claims for the many-binding outbox dispatch.

`docs/MULTI_VAULT_RUNTIME/BIND_BACKGROUND_LIFECYCLES.md` (MVR-06D) and
`docs/EVENTS.md :: Outbox envelope (canonical)`. The singleton worker's plain
``select ... limit 1`` followed by a later acknowledgement is safe only while one worker
runs. Before more than one production lifecycle dispatches, every row gets at most one
concurrent claim owner through this module:

- :func:`claim_next` atomically selects (``FOR UPDATE SKIP LOCKED``) and leases one
  unclaimed or lease-expired row of exactly one routing scope (one vault binding, or the
  singleton ``global`` scope), stamping a database-monotonic fencing token from
  ``outbox_claim_token_seq``.
- :func:`mark_effect_pending` persists ``effect_pending`` with that token and a bounded
  effect descriptor *before* the handler runs.
- :func:`fenced_effect` is the production effect boundary: one store transaction that
  locks the row, rejects a stale token (the owner paused past its lease and another
  worker reclaimed the row), runs the admitted handler's store effect on the same
  connection, and records ``effect_outcome`` atomically with it.
- :func:`ack_claim` acknowledges only a row whose effect outcome is durable.

A crash after the effect but before the acknowledgement leaves ``effect_pending`` with a
durable outcome; once the lease expires another worker reclaims it and acknowledges it
without replaying the effect. A crash before the effect commit leaves no outcome, which
for an atomic-store handler proves the effect did not apply. At-least-once delivery and the
binding-scoped idempotency key are unchanged; nothing here claims exactly-once effects.

Every statement fails loud when the MVR-06D claim columns are missing; a database
without them is an error, never a silent fallback to the unfenced poll.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any

from app.instance.binding_ids import (
    COMPATIBILITY_BINDING_ID,
    OUTBOX_GLOBAL_BINDING_ID,
    OUTBOX_QUARANTINE_BINDING_ID,
)
from app.services.outbox import _coerce_event_from_db, _exec, _row_value

CLAIM_COLUMNS = (
    "claim_token",
    "claim_owner",
    "claim_expires_at",
    "claim_phase",
    "effect_descriptor",
    "effect_outcome",
    "effect_receipt",
    "consumer_context",
    "quarantined_at",
    "quarantine_reason",
)
CLAIM_TOKEN_SEQUENCE = "outbox_claim_token_seq"
PHASE_CLAIMED = "claimed"
PHASE_EFFECT_PENDING = "effect_pending"
PHASE_RECONCILIATION_REQUIRED = "effect_reconciliation_required"
OUTCOME_APPLIED = "applied"
OUTCOME_NO_EFFECT = "no_effect"
RECONCILIATION_OWNER = "effect-reconciliation-required"
_MIGRATION_HINT = "run `alembic upgrade head` (MVR-06D revision fa06d0c00001)"


class OutboxClaimSchemaMissing(RuntimeError):
    """The recoverable claim columns/sequence/constraints are not installed (fail loud)."""


class StaleClaimToken(RuntimeError):
    """The claim's fencing token is no longer the row's current claim (reject the effect)."""


class EffectAlreadyRecorded(RuntimeError):
    """The row already carries a durable effect outcome; reconcile, never replay."""


@dataclass(frozen=True)
class OutboxClaim:
    """One leased row; the token fences every later write of this claim."""

    row_id: str
    topic: str
    payload: dict[str, Any]
    event: Any
    vault_binding_id: str
    token: int
    owner: str
    phase: str
    effect_descriptor: dict[str, Any] | None
    effect_outcome: str | None
    attempts: int

    @property
    def recovered_effect_pending(self) -> bool:
        """Reclaimed after its lease expired with an effect already marked pending."""

        return self.phase == PHASE_EFFECT_PENDING

    @property
    def meta(self) -> Mapping[str, Any]:
        meta = getattr(self.event, "meta", None)
        return meta if isinstance(meta, Mapping) else {}

    def message(self) -> dict[str, Any]:
        """The worker's dispatch message shape (identical to ``poll_outbox_one``)."""

        return {
            "id": self.row_id,
            "topic": self.topic,
            "payload": dict(self.payload),
            "event": self.event,
            "vault_binding_id": self.vault_binding_id,
        }


def require_claim_schema(conn: Any) -> None:
    """Fail loud unless every MVR-06D claim column, the token sequence, and the CHECK exist."""

    cur = _exec(
        conn,
        "select column_name from information_schema.columns "
        "where table_schema = current_schema() and table_name = 'outbox'",
    )
    present = {_row_value(row, 0, "column_name") for row in cur.fetchall()}
    missing = [column for column in CLAIM_COLUMNS if column not in present]
    if missing:
        raise OutboxClaimSchemaMissing(
            f"outbox is missing MVR-06D claim column(s) {missing}; {_MIGRATION_HINT}"
        )
    cur = _exec(
        conn,
        "select "
        "to_regclass(quote_ident(current_schema()) || '.' || %s)::text as seq, "
        "(select count(*) from pg_constraint where conname = 'outbox_claim_phase_check') "
        "as checks",
        (CLAIM_TOKEN_SEQUENCE,),
    )
    row = cur.fetchone()
    if row is None or _row_value(row, 0, "seq") is None or int(_row_value(row, 1, "checks")) < 1:
        raise OutboxClaimSchemaMissing(
            f"outbox claim token sequence or claim-phase constraint is missing; {_MIGRATION_HINT}"
        )


_CLAIM_RETURNING = (
    "o.id, o.topic, o.payload, o.vault_binding_id, o.claim_token, o.claim_owner, "
    "o.claim_phase, o.effect_descriptor, o.effect_outcome, o.attempts"
)


def _as_mapping(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if isinstance(value, Mapping) else None


def _claim_from_row(row: Any) -> OutboxClaim:
    topic = _row_value(row, 1, "topic")
    event = _coerce_event_from_db(_row_value(row, 2, "payload"), topic)
    return OutboxClaim(
        row_id=str(_row_value(row, 0, "id")),
        topic=event.event_type,
        payload=dict(event.payload),
        event=event,
        vault_binding_id=str(_row_value(row, 3, "vault_binding_id")),
        token=int(_row_value(row, 4, "claim_token")),
        owner=str(_row_value(row, 5, "claim_owner")),
        phase=str(_row_value(row, 6, "claim_phase")),
        effect_descriptor=_as_mapping(_row_value(row, 7, "effect_descriptor")),
        effect_outcome=_row_value(row, 8, "effect_outcome"),
        attempts=int(_row_value(row, 9, "attempts") or 0),
    )


def _scope_binding(vault_binding_id: str) -> str:
    binding = (vault_binding_id or "").strip()
    if not binding or binding in {COMPATIBILITY_BINDING_ID, OUTBOX_QUARANTINE_BINDING_ID}:
        # An unscoped compatibility row or an MVR-05 unprovable row has no binding a
        # many-binding lifecycle may claim it under.
        raise ValueError(f"no claim scope exists for outbox binding {binding!r}")
    return binding


def claim_next(
    conn: Any,
    *,
    owner: str,
    vault_binding_id: str,
    lease_seconds: float,
    topics: tuple[str, ...] | None = None,
    exclude_topics: tuple[str, ...] = (),
    recovery_only: bool = False,
) -> OutboxClaim | None:
    """Atomically lease the oldest claimable row of one routing scope, or ``None``.

    Claimable: undelivered, not quarantined, and either unclaimed or holding an expired
    ``claimed``/``effect_pending`` lease. An ``effect_reconciliation_required`` row is never
    claimable. A reclaimed ``effect_pending`` row keeps that phase so the new owner
    reconciles the durable effect outcome before anything else. ``topics`` restricts the
    claim to admitted handlers and ``exclude_topics`` keeps unadmitted handlers pending;
    ``recovery_only`` reclaims only expired pending effects (any topic).
    """

    binding = _scope_binding(vault_binding_id)
    if not owner.strip():
        raise ValueError("an outbox claim requires an owner")
    if lease_seconds <= 0:
        raise ValueError("an outbox claim lease must be positive")
    conditions = [
        "delivered_at is null",
        "quarantined_at is null",
        "vault_binding_id = %s",
    ]
    params: list[object] = [binding]
    if recovery_only:
        conditions.append("claim_phase = 'effect_pending' and claim_expires_at <= now()")
    else:
        conditions.append(
            "(claim_phase is null or (claim_phase in ('claimed', 'effect_pending') "
            "and claim_expires_at <= now()))"
        )
    if topics is not None:
        if not topics:
            return None
        conditions.append("topic in (" + ", ".join("%s" for _ in topics) + ")")
        params.extend(topics)
    if exclude_topics:
        conditions.append("topic not in (" + ", ".join("%s" for _ in exclude_topics) + ")")
        params.extend(exclude_topics)
    cur = _exec(
        conn,
        "with candidate as (select id from outbox where "
        + " and ".join(conditions)
        + " order by created_at asc, id asc limit 1 for update skip locked) "
        "update outbox o set "
        f"claim_token = nextval('{CLAIM_TOKEN_SEQUENCE}'), "
        "claim_owner = %s, "
        "claim_expires_at = now() + make_interval(secs => %s), "
        "claim_phase = case when o.claim_phase = 'effect_pending' "
        "then 'effect_pending' else 'claimed' end "
        "from candidate where o.id = candidate.id "
        f"returning {_CLAIM_RETURNING}",
        (*params, owner, float(lease_seconds)),
    )
    row = cur.fetchone()
    return None if row is None else _claim_from_row(row)


def mark_effect_pending(
    conn: Any, claim: OutboxClaim, descriptor: Mapping[str, Any]
) -> OutboxClaim:
    """Persist ``effect_pending`` + descriptor under this live token, before the effect."""

    cur = _exec(
        conn,
        "update outbox set claim_phase = 'effect_pending', effect_descriptor = %s::jsonb "
        "where id = %s and claim_token = %s and claim_owner = %s "
        "and claim_expires_at > now() and delivered_at is null and quarantined_at is null "
        "and effect_outcome is null and claim_phase in ('claimed', 'effect_pending') "
        "returning 1",
        (json.dumps(dict(descriptor), sort_keys=True), claim.row_id, claim.token, claim.owner),
    )
    if cur.fetchone() is None:
        raise StaleClaimToken(f"outbox claim {claim.token} is no longer current")
    return replace(claim, phase=PHASE_EFFECT_PENDING, effect_descriptor=dict(descriptor))


@contextmanager
def fenced_effect(
    txn_conn: Any,
    claim: OutboxClaim,
    *,
    outcome: str,
    receipt: Mapping[str, Any],
) -> Iterator[Any]:
    """The production effect boundary: token check, store effect, outcome — one transaction.

    ``txn_conn`` must be a manual-commit connection owned by the caller. The row lock is
    taken first; a stale token, an expired lease, a delivered/quarantined row, or an
    already-recorded outcome rolls back before the handler runs. The handler writes its
    store effect on the yielded connection, so the effect and ``effect_outcome`` commit or
    roll back together.
    """

    if outcome not in {OUTCOME_APPLIED, OUTCOME_NO_EFFECT}:
        raise ValueError(f"unknown effect outcome {outcome!r}")
    try:
        cur = _exec(
            txn_conn,
            "select claim_token, claim_owner, claim_expires_at > now(), delivered_at, "
            "quarantined_at, effect_outcome, claim_phase from outbox where id = %s for update",
            (claim.row_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise StaleClaimToken("the claimed outbox row disappeared")
        token, owner, live, delivered, quarantined, recorded, phase = (
            _row_value(row, index) for index in range(7)
        )
        if recorded is not None:
            raise EffectAlreadyRecorded(f"outbox row {claim.row_id} already recorded {recorded}")
        if (
            token is None
            or int(token) != claim.token
            or owner != claim.owner
            or not live
            or delivered is not None
            or quarantined is not None
            or phase != PHASE_EFFECT_PENDING
        ):
            raise StaleClaimToken(
                f"outbox claim {claim.token} was superseded or expired before its effect"
            )
        yield txn_conn
        cur = _exec(
            txn_conn,
            "update outbox set effect_outcome = %s, effect_receipt = %s::jsonb "
            "where id = %s and claim_token = %s and effect_outcome is null returning 1",
            (outcome, json.dumps(dict(receipt), sort_keys=True), claim.row_id, claim.token),
        )
        if cur.fetchone() is None:
            raise StaleClaimToken("the effect outcome could not be recorded under this token")
        txn_conn.commit()
    except BaseException:
        txn_conn.rollback()
        raise


def ack_claim(conn: Any, claim: OutboxClaim, *, consumer_context: Mapping[str, Any]) -> bool:
    """Acknowledge a row whose effect outcome is durable; clears the lease, keeps the token.

    Acknowledgement is keyed on the recorded outcome rather than on lease liveness: an
    owner that already committed the effect may acknowledge late, and a reclaiming owner
    acknowledges the same durable outcome under its own token.
    """

    cur = _exec(
        conn,
        "update outbox set delivered_at = now(), claim_phase = null, claim_owner = null, "
        "claim_expires_at = null, consumer_context = %s::jsonb "
        "where id = %s and claim_token = %s and delivered_at is null "
        "and effect_outcome is not null returning 1",
        (json.dumps(dict(consumer_context), sort_keys=True), claim.row_id, claim.token),
    )
    return cur.fetchone() is not None


def release_claim(conn: Any, claim: OutboxClaim, *, failed: bool) -> int | None:
    """Return a not-yet-effected claim to the pool (a failed attempt counts toward poison)."""

    cur = _exec(
        conn,
        "update outbox set claim_phase = null, claim_owner = null, claim_expires_at = null, "
        "effect_descriptor = null, attempts = attempts + %s "
        "where id = %s and claim_token = %s and delivered_at is null "
        "and effect_outcome is null returning attempts",
        (1 if failed else 0, claim.row_id, claim.token),
    )
    row = cur.fetchone()
    return None if row is None else int(_row_value(row, 0, "attempts"))


def quarantine_claim(conn: Any, claim: OutboxClaim, *, reason: str) -> bool:
    """Move a claimed, provably unapplied row to durable quarantine (no dispatch, no ack).

    A row with a recorded effect outcome is never quarantined: it is acknowledged under
    its prior authorized provenance instead.
    """

    cur = _exec(
        conn,
        "update outbox set quarantined_at = now(), quarantine_reason = %s, "
        "claim_phase = null, claim_owner = null, claim_expires_at = null "
        "where id = %s and claim_token = %s and delivered_at is null "
        "and effect_outcome is null returning 1",
        (reason, claim.row_id, claim.token),
    )
    return cur.fetchone() is not None


def mark_reconciliation_required(conn: Any, claim: OutboxClaim, *, reason: str) -> bool:
    """Block an ambiguous post-crash outcome: no redispatch, ack, drop, or quarantine."""

    descriptor = dict(claim.effect_descriptor or {})
    descriptor["reconciliation_reason"] = reason
    cur = _exec(
        conn,
        "update outbox set claim_phase = 'effect_reconciliation_required', claim_owner = %s, "
        "claim_expires_at = 'infinity', effect_descriptor = %s::jsonb "
        "where id = %s and claim_token = %s and delivered_at is null "
        "and effect_outcome is null returning 1",
        (RECONCILIATION_OWNER, json.dumps(descriptor, sort_keys=True), claim.row_id, claim.token),
    )
    return cur.fetchone() is not None


def claimable_scopes(conn: Any) -> tuple[str, ...]:
    """Every binding scope holding undelivered, unquarantined, not-blocked work."""

    cur = _exec(
        conn,
        "select distinct vault_binding_id from outbox where delivered_at is null "
        "and quarantined_at is null and vault_binding_id not in (%s, %s) "
        "and (claim_phase is null or claim_phase <> 'effect_reconciliation_required')",
        (COMPATIBILITY_BINDING_ID, OUTBOX_QUARANTINE_BINDING_ID),
    )
    return tuple(sorted(str(_row_value(row, 0, "vault_binding_id")) for row in cur.fetchall()))


def quarantine_unclaimed_rows(conn: Any, vault_binding_id: str, *, reason: str) -> int:
    """Quarantine every unclaimed/lease-expired, unapplied row of one binding scope.

    Expired ``effect_pending`` rows are excluded: recovery reconciles their durable effect
    outcome first (:func:`claim_next` with ``recovery_only``).
    """

    binding = _scope_binding(vault_binding_id)
    if binding == OUTBOX_GLOBAL_BINDING_ID:
        raise ValueError("global rows are never quarantined by a binding lifecycle")
    cur = _exec(
        conn,
        "update outbox set quarantined_at = now(), quarantine_reason = %s, "
        "claim_phase = null, claim_owner = null, claim_expires_at = null "
        "where vault_binding_id = %s and delivered_at is null and quarantined_at is null "
        "and effect_outcome is null and (claim_phase is null or "
        "(claim_phase = 'claimed' and claim_expires_at <= now())) returning id",
        (reason, binding),
    )
    return len(cur.fetchall())


def reissue_quarantined(
    conn: Any,
    row_id: str,
    *,
    vault_binding_id: str,
    consumer_context: Mapping[str, Any],
) -> bool:
    """Governed reissue to the *same* stable binding; id/legacy_key lineage is preserved.

    The row's binding never changes: a request naming another binding matches nothing.
    """

    binding = _scope_binding(vault_binding_id)
    cur = _exec(
        conn,
        "update outbox set quarantined_at = null, consumer_context = %s::jsonb, "
        "quarantine_reason = null, effect_descriptor = null "
        "where id = %s and vault_binding_id = %s and quarantined_at is not null "
        "and delivered_at is null and effect_outcome is null returning 1",
        (
            json.dumps({"reissued": dict(consumer_context)}, sort_keys=True),
            row_id,
            binding,
        ),
    )
    return cur.fetchone() is not None


def drop_quarantined(conn: Any, row_id: str, *, reason: str) -> bool:
    """Terminally settle a quarantined row without dispatch (an operator decision)."""

    cur = _exec(
        conn,
        "update outbox set delivered_at = now(), "
        "quarantine_reason = 'operator_dropped:' || %s "
        "where id = %s and quarantined_at is not null and delivered_at is null returning 1",
        (reason, row_id),
    )
    return cur.fetchone() is not None


def quarantined_rows(conn: Any, vault_binding_id: str | None = None) -> list[dict[str, Any]]:
    """Redacted inspection: ids, topic, binding, reason — never the payload."""

    sql = (
        "select id, topic, vault_binding_id, quarantine_reason from outbox "
        "where quarantined_at is not null and delivered_at is null"
    )
    params: tuple[object, ...] = ()
    if vault_binding_id is not None:
        sql += " and vault_binding_id = %s"
        params = (vault_binding_id,)
    cur = _exec(conn, sql + " order by created_at asc, id asc", params)
    return [
        {
            "id": str(_row_value(row, 0, "id")),
            "topic": _row_value(row, 1, "topic"),
            "vault_binding_id": _row_value(row, 2, "vault_binding_id"),
            "reason": _row_value(row, 3, "quarantine_reason"),
        }
        for row in cur.fetchall()
    ]


def disposition_counts(conn: Any) -> dict[str, dict[str, int]]:
    """Per-scope counts of undelivered work by disposition (bounded health projection)."""

    cur = _exec(
        conn,
        "select vault_binding_id, "
        "count(*) filter (where quarantined_at is null and claim_phase is null) as pending, "
        "count(*) filter (where quarantined_at is null and claim_phase = 'claimed') as claimed, "
        "count(*) filter (where claim_phase = 'effect_pending') as effect_pending, "
        "count(*) filter (where claim_phase = 'effect_reconciliation_required') "
        "as reconciliation_required, "
        "count(*) filter (where quarantined_at is not null) as quarantined "
        "from outbox where delivered_at is null group by vault_binding_id",
    )
    names = ("pending", "claimed", "effect_pending", "reconciliation_required", "quarantined")
    return {
        str(_row_value(row, 0, "vault_binding_id")): {
            name: int(_row_value(row, index + 1, name) or 0) for index, name in enumerate(names)
        }
        for row in cur.fetchall()
    }


def classify_for_activation(conn: Any) -> dict[str, Any]:
    """Read-only MVR-05 classification census of undelivered rows for the 06D gate."""

    require_claim_schema(conn)
    cur = _exec(
        conn,
        "select "
        "count(*) filter (where vault_binding_id = %s) as unscoped, "
        "count(*) filter (where vault_binding_id = %s) as unprovable, "
        "count(*) filter (where vault_binding_id = %s) as global_rows, "
        "count(*) filter (where vault_binding_id not in (%s, %s, %s)) as scoped, "
        "count(*) filter (where claim_phase is not null or quarantined_at is not null "
        "or effect_outcome is not null) as queue_state "
        "from outbox where delivered_at is null",
        (
            COMPATIBILITY_BINDING_ID,
            OUTBOX_QUARANTINE_BINDING_ID,
            OUTBOX_GLOBAL_BINDING_ID,
            COMPATIBILITY_BINDING_ID,
            OUTBOX_QUARANTINE_BINDING_ID,
            OUTBOX_GLOBAL_BINDING_ID,
        ),
    )
    row = cur.fetchone()
    names = ("unscoped", "unprovable", "global_rows", "scoped", "queue_state")
    counts = {name: int(_row_value(row, index, name) or 0) for index, name in enumerate(names)}
    cur = _exec(
        conn,
        "select distinct vault_binding_id from outbox where delivered_at is null "
        "and vault_binding_id not in (%s, %s, %s)",
        (COMPATIBILITY_BINDING_ID, OUTBOX_QUARANTINE_BINDING_ID, OUTBOX_GLOBAL_BINDING_ID),
    )
    counts["scoped_bindings"] = sorted(
        str(_row_value(item, 0, "vault_binding_id")) for item in cur.fetchall()
    )
    return counts


__all__ = [
    "CLAIM_COLUMNS",
    "EffectAlreadyRecorded",
    "OUTCOME_APPLIED",
    "OUTCOME_NO_EFFECT",
    "OutboxClaim",
    "OutboxClaimSchemaMissing",
    "PHASE_CLAIMED",
    "PHASE_EFFECT_PENDING",
    "PHASE_RECONCILIATION_REQUIRED",
    "StaleClaimToken",
    "ack_claim",
    "claim_next",
    "claimable_scopes",
    "classify_for_activation",
    "disposition_counts",
    "drop_quarantined",
    "fenced_effect",
    "mark_effect_pending",
    "mark_reconciliation_required",
    "quarantine_claim",
    "quarantine_unclaimed_rows",
    "quarantined_rows",
    "reissue_quarantined",
    "release_claim",
    "require_claim_schema",
]
