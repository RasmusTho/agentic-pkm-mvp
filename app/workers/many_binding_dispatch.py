"""MVR-06D: the many-binding worker tick over recoverable PostgreSQL claims.

`docs/MULTI_VAULT_RUNTIME/BIND_BACKGROUND_LIFECYCLES.md` (MVR-06D). Once the registry
carries ``minimumRuntimeSchema=mvr-06d`` every worker process dispatches through this
module instead of the singleton ``poll_outbox_one`` path (which stays the behaviour of
every pre-activation install). One tick:

1. reconciles every supervised lifecycle from durable registry revision + auth epoch;
2. recovers and quarantines the pending rows of bindings that no running lifecycle may
   serve: removed (unregistered), not enrolled in durable intent, or denied by GOV. An
   expired ``effect_pending`` row is reconciled *first* from its durable effect outcome:
   applied -> acknowledged under its prior authorized provenance; provably not applied ->
   current-authority quarantine; ambiguous -> ``effect_reconciliation_required``;
3. runs the separately fenced singleton ``global`` claim (no binding lease is invented);
4. for each running binding, inside the host-global ownership fence then that binding's
   shared effect lease, claims one row of exactly that binding, revalidates it against the
   current stable binding and payload locator, persists ``effect_pending``, runs the
   admitted handler inside the token-checked effect transaction, and acknowledges.

Handler admission (:func:`effect_contract`): only handlers whose effect is atomic with the
claim's effect outcome may run here -- topics with no consumer effect, and the store-atomic
knowledge-acquisition signal handlers. Every other handled topic (vault-file and derived
projection effects) has no post-effect reconciliation read yet, so its rows stay pending
and are reported ``unadmitted`` instead of being dispatched.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.instance.binding_ids import OUTBOX_GLOBAL_BINDING_ID

logger = logging.getLogger(__name__)

EFFECT_CONTRACT_VERSION = "agentic-pkm.mvr06d-effect-contract.v1"
DEFAULT_CLAIM_LEASE_SECONDS = 300.0
_RECOVERY_BUDGET = 100
_LOCATOR_KEYS = ("vault_path", "path", "note_path", "source_ref", "artifact_path")
_RELATIVE_LOCATOR_KEYS = ("relative_path",)

EffectKind = Literal["store_atomic", "no_effect"]


@dataclass(frozen=True)
class EffectContract:
    """The admission record of one topic in the many-binding worker."""

    topic: str
    kind: EffectKind

    def descriptor(self, claim: Any, *, consumer_context: Mapping[str, Any]) -> dict[str, Any]:
        """The bounded effect descriptor persisted with ``effect_pending`` (no payload)."""

        idempotency = claim.meta.get("idempotency")
        return {
            "contract": EFFECT_CONTRACT_VERSION,
            "kind": self.kind,
            "topic": self.topic,
            "vault_binding_id": claim.vault_binding_id,
            "claim_token": claim.token,
            "binding_scoped_key": (
                idempotency.get("binding_scoped_key")
                if isinstance(idempotency, Mapping)
                else claim.row_id
            ),
            "consumer_context": dict(consumer_context),
        }


def _handled_topics() -> frozenset[str]:
    from app.workers.outbox_worker import HANDLED_DISPATCH_TOPICS

    return HANDLED_DISPATCH_TOPICS


def _store_atomic_topics() -> frozenset[str]:
    from app.workers.outbox_worker import STORE_ATOMIC_DISPATCH_TOPICS

    return STORE_ATOMIC_DISPATCH_TOPICS


def effect_contract(topic: str) -> EffectContract | None:
    """The admitted effect contract of ``topic``, or ``None`` when it is not admitted."""

    if topic in _store_atomic_topics():
        return EffectContract(topic=topic, kind="store_atomic")
    if topic not in _handled_topics():
        return EffectContract(topic=topic, kind="no_effect")
    return None


def unadmitted_topics() -> tuple[str, ...]:
    """Handled topics without a reconcilable effect contract (never claimed here)."""

    return tuple(sorted(_handled_topics() - _store_atomic_topics()))


def _proves_no_effect(descriptor: Mapping[str, Any] | None, topic: str) -> bool:
    """A missing outcome proves "not applied" only under an atomic contract we still run."""

    contract = effect_contract(topic)
    return (
        contract is not None
        and isinstance(descriptor, Mapping)
        and descriptor.get("contract") == EFFECT_CONTRACT_VERSION
        and descriptor.get("kind") == contract.kind
        and descriptor.get("topic") == topic
    )


# -- revalidation -------------------------------------------------------------------------


def revalidate_vault_bound_claim(claim: Any, runtime: Any) -> str | None:
    """Return a quarantine reason, or ``None`` when the row may dispatch on ``runtime``.

    Captured producer context and generation stay immutable provenance: a supervisor
    restart or generation rotation alone never invalidates a row. The row must still name
    the same stable binding with a complete envelope, and every payload locator must
    resolve safely under the binding's *current* root -- a relocation leaves an absolute
    old-root locator incompatible, while a relative one follows the binding.
    """

    from app.services.outbox import binding_envelope_is_dispatchable

    meta = claim.meta
    if claim.vault_binding_id != runtime.vault_binding_id or (
        meta.get("vault_binding_id") != claim.vault_binding_id
    ):
        return "binding_identity_mismatch"
    if not binding_envelope_is_dispatchable(claim.message()):
        return "envelope_incomplete"
    root = Path(runtime.root).resolve()
    payload = claim.payload
    for key in _LOCATOR_KEYS:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        if not candidate.resolve(strict=False).is_relative_to(root):
            return "incompatible_locator"
    for key in _RELATIVE_LOCATOR_KEYS:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        relative = Path(value)
        if relative.is_absolute() or not (root / relative).resolve(strict=False).is_relative_to(
            root
        ):
            return "incompatible_locator"
    return None


def consumer_context_for(claim: Any, lifecycle: Any | None, *, owner: str) -> dict[str, Any]:
    """The consumer context linked to the row's immutable producer context (redacted)."""

    meta = claim.meta
    linked = {
        "owner": owner,
        "producer_context": meta.get("producer_context"),
        "producer_binding_revision": meta.get("binding_revision"),
        "producer_authorization_epoch": meta.get("binding_authorization_epoch"),
    }
    if lifecycle is None:
        return {"routing_class": "global", **linked}
    return {
        "routing_class": "vault_bound",
        "context_id": lifecycle.context.context_id,
        "generation": lifecycle.generation,
        "binding_revision": lifecycle.binding_revision,
        "intent_revision": lifecycle.intent_revision,
        "authorization_epoch": lifecycle.authorization_epoch,
        **linked,
    }


# -- the tick -----------------------------------------------------------------------------


@dataclass
class ScopeOutcome:
    """What one routing scope did this tick (bounded, redacted)."""

    scope: str
    lifecycle_status: str
    state: str
    processed: int = 0
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "lifecycle_status": self.lifecycle_status,
            "state": self.state,
            "processed": self.processed,
            "detail": self.detail,
        }


@dataclass
class ManyBindingTick:
    outcomes: list[ScopeOutcome] = field(default_factory=list)
    queue: str = "postgres"

    @property
    def processed(self) -> int:
        return sum(item.processed for item in self.outcomes)

    @property
    def state(self) -> str:
        """``processed`` > ``background_lifecycle_failed`` > ``no_vault`` > ``idle``."""

        if self.processed:
            return "processed"
        if any(item.lifecycle_status == "failed" for item in self.outcomes):
            return "background_lifecycle_failed"
        if all(item.lifecycle_status == "idle" for item in self.outcomes if item.scope != "global"):
            return "no_vault"
        return "idle"

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "queue": self.queue,
            "processed": self.processed,
            "scopes": [item.as_dict() for item in self.outcomes],
        }


def _claim_fault_point(stage: str, claim: Any = None) -> None:
    """Process-failure injection seam for the claim protocol; production is a no-op."""

    del stage, claim


def _lease_seconds() -> float:
    raw = os.getenv("WORKER_CLAIM_LEASE_SECONDS", "").strip()
    try:
        value = float(raw) if raw else DEFAULT_CLAIM_LEASE_SECONDS
    except ValueError:
        value = DEFAULT_CLAIM_LEASE_SECONDS
    return value if value > 0 else DEFAULT_CLAIM_LEASE_SECONDS


def _max_attempts() -> int:
    from app.workers.outbox_worker import _resolve_max_dispatch_attempts

    return _resolve_max_dispatch_attempts()


def queue_configured() -> bool:
    """The DB outbox exists for this process (absent memory store is not an error)."""

    from app.services.outbox import _self_owned_database_is_named

    return (
        _self_owned_database_is_named()
        or (os.getenv("STORE_BACKEND") or "").strip().lower() == "pg"
    )


class ManyBindingDispatcher:
    """One worker process's many-binding dispatcher over its reconciling supervisor."""

    def __init__(self, supervisor: Any, *, owner: str | None = None) -> None:
        self.supervisor = supervisor
        self.owner = owner or f"worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"

    # -- connections ---------------------------------------------------------------------

    @staticmethod
    def _conn() -> Any:
        from app.services.outbox import _open_conn

        return _open_conn()

    @staticmethod
    def _txn_conn() -> Any:
        from app.services.outbox import open_outbox_txn_conn

        conn = open_outbox_txn_conn()
        if conn is None:
            raise RuntimeError("the many-binding worker requires a transactional DB connection")
        return conn

    # -- recovery ------------------------------------------------------------------------

    def _reconcile_recovered(
        self,
        conn: Any,
        claim: Any,
        *,
        lifecycle: Any | None,
        quarantine_reason: str | None,
    ) -> str | None:
        """Resolve a reclaimed ``effect_pending`` row; ``None`` means proceed to dispatch."""

        from app.services import outbox_claims as claims

        if claim.effect_outcome is not None:
            context = consumer_context_for(claim, lifecycle, owner=self.owner)
            context["reconciled"] = "effect_outcome_durable"
            if quarantine_reason is not None:
                context["authority_at_recovery"] = quarantine_reason
            claims.ack_claim(conn, claim, consumer_context=context)
            return "reconciled_applied"
        if not _proves_no_effect(claim.effect_descriptor, claim.topic):
            claims.mark_reconciliation_required(
                conn, claim, reason="effect outcome is neither durable nor provably absent"
            )
            return "reconciliation_required"
        if quarantine_reason is not None:
            claims.quarantine_claim(conn, claim, reason=quarantine_reason)
            return "quarantined"
        return None

    def _recover_and_quarantine(self, conn: Any, scope: str, reason: str) -> ScopeOutcome:
        from app.services import outbox_claims as claims

        resolved = 0
        for _ in range(_RECOVERY_BUDGET):
            claim = claims.claim_next(
                conn,
                owner=f"{self.owner}:recovery",
                vault_binding_id=scope,
                lease_seconds=_lease_seconds(),
                recovery_only=True,
            )
            if claim is None:
                break
            self._reconcile_recovered(conn, claim, lifecycle=None, quarantine_reason=reason)
            resolved += 1
        quarantined = claims.quarantine_unclaimed_rows(conn, scope, reason=reason)
        return ScopeOutcome(
            scope=scope,
            lifecycle_status="absent",
            state="quarantined" if quarantined or resolved else "idle",
            processed=0,
            detail=reason,
        )

    def _quarantine_reason(
        self, scope: str, snapshot: Any, intent_ids: set[str], lifecycles: Mapping[str, Any]
    ) -> str | None:
        transfer = snapshot.extensions.get("channelTransfer")
        if isinstance(transfer, Mapping) and transfer.get("source_binding_id") == scope:
            return None  # a channel transfer drains this binding's queue; block, never quarantine
        registration = snapshot.registrations.get(scope)
        if registration is None:
            return "binding_removed"
        if registration.extensions.get("lifecycleState") is not None:
            return None  # sealed (removal/reactivation/relocation) work blocks until it settles
        if scope not in intent_ids:
            return "lifecycle_not_enrolled"
        lifecycle = lifecycles.get(scope)
        if lifecycle is not None and lifecycle.failure_kind == "authorization":
            return "authority_lost"
        return None  # a transient failure blocks; it never quarantines

    # -- dispatch ------------------------------------------------------------------------

    def _dispatch_claim(self, conn: Any, claim: Any, *, lifecycle: Any | None, runtime: Any) -> str:
        from app.services import outbox_claims as claims
        from app.workers.outbox_worker import (
            SchemaViolationDispatchError,
            _validate_dispatch_payload,
            dispatch_store_atomic_effect,
        )

        if claim.recovered_effect_pending:
            settled = self._reconcile_recovered(
                conn, claim, lifecycle=lifecycle, quarantine_reason=None
            )
            if settled is not None:
                return settled
        contract = effect_contract(claim.topic)
        if contract is None:
            claims.release_claim(conn, claim, failed=False)
            return "unadmitted"
        if runtime is not None:
            reason = revalidate_vault_bound_claim(claim, runtime)
            if reason is not None:
                claims.quarantine_claim(conn, claim, reason=reason)
                return "quarantined"
        message = claim.message()
        try:
            _validate_dispatch_payload(claim.topic, claim.payload, message=message)
        except SchemaViolationDispatchError:
            claims.quarantine_claim(conn, claim, reason="schema_violation")
            return "quarantined"
        context = consumer_context_for(claim, lifecycle, owner=self.owner)
        claim = claims.mark_effect_pending(
            conn, claim, contract.descriptor(claim, consumer_context=context)
        )
        _claim_fault_point("effect_pending", claim)
        txn = self._txn_conn()
        try:
            with claims.fenced_effect(
                txn,
                claim,
                outcome=(
                    claims.OUTCOME_APPLIED
                    if contract.kind == "store_atomic"
                    else claims.OUTCOME_NO_EFFECT
                ),
                receipt={"consumer_context": context, "claim_token": claim.token},
            ) as effect_conn:
                if contract.kind == "store_atomic":
                    dispatch_store_atomic_effect(
                        claim.topic,
                        claim.payload,
                        conn=effect_conn,
                        trace_id=claim.payload.get("trace_id"),
                        source_vault_binding_id=claim.vault_binding_id,
                        message=message,
                    )
                _claim_fault_point("effect_running", claim)
        except (claims.StaleClaimToken, claims.EffectAlreadyRecorded):
            logger.warning(
                "many-binding effect rejected: claim %s for row %s is no longer current",
                claim.token,
                claim.row_id,
            )
            return "stale_claim_rejected"
        except Exception as exc:
            # The effect transaction rolled back, so the effect provably did not apply.
            attempts = claim.attempts + 1
            logger.error(
                "many-binding dispatch failed topic=%s row=%s attempts=%s: %s",
                claim.topic,
                claim.row_id,
                attempts,
                exc,
            )
            if attempts >= _max_attempts():
                # Poison: a terminal, observable, reissuable disposition (never a drop).
                claims.quarantine_claim(conn, claim, reason="dispatch_failed")
            else:
                claims.release_claim(conn, claim, failed=True)
            return "dispatch_failed"
        finally:
            try:
                txn.close()
            except Exception:  # pragma: no cover - defensive close
                pass
        _claim_fault_point("effect_committed", claim)
        claims.ack_claim(conn, claim, consumer_context=context)
        return "processed"

    def tick(self) -> ManyBindingTick:
        from app.instance.background_supervisor import (
            BackgroundBindingIdle,
            BackgroundLifecycleError,
            durable_background_state,
        )
        from app.instance.binding_effect_lease import BindingEffectLeaseError
        from app.instance.scalar_binding_runtime import (
            background_effect_runtime,
            frozen_binding_effect,
        )
        from app.instance.vault_registry import RegistryError
        from app.services import outbox_claims as claims

        lifecycles = self.supervisor.reconcile_all()
        by_binding = {item.binding_id: item for item in lifecycles if item.binding_id}
        result = ManyBindingTick()
        if not queue_configured():
            result.queue = "absent"
            result.outcomes = [
                ScopeOutcome(
                    scope=item.binding_id or "none",
                    lifecycle_status=item.status,
                    state="no_queue",
                    detail=item.failure,
                )
                for item in lifecycles
            ]
            return result
        snapshot = self.supervisor.registry.load()
        state = durable_background_state(snapshot)
        intent_ids = set(state.binding_ids if state is not None else ())
        running = {key: item for key, item in by_binding.items() if item.status == "running"}
        conn = self._conn()
        try:
            claims.require_claim_schema(conn)
            excluded = unadmitted_topics()
            for scope in claims.claimable_scopes(conn):
                if scope == OUTBOX_GLOBAL_BINDING_ID or scope in running:
                    continue
                reason = self._quarantine_reason(scope, snapshot, intent_ids, by_binding)
                if reason is not None:
                    result.outcomes.append(self._recover_and_quarantine(conn, scope, reason))
            # The separately fenced singleton global scope: no binding lease, no vault.
            global_claim = claims.claim_next(
                conn,
                owner=f"{self.owner}:global",
                vault_binding_id=OUTBOX_GLOBAL_BINDING_ID,
                lease_seconds=_lease_seconds(),
                exclude_topics=excluded,
            )
            global_state = (
                "idle"
                if global_claim is None
                else self._dispatch_claim(conn, global_claim, lifecycle=None, runtime=None)
            )
            result.outcomes.append(
                ScopeOutcome(
                    scope="global",
                    lifecycle_status="singleton",
                    state=global_state,
                    processed=int(global_state in {"processed", "reconciled_applied"}),
                )
            )
            for lifecycle in lifecycles:
                if lifecycle.binding_id is None or lifecycle.status != "running":
                    result.outcomes.append(
                        ScopeOutcome(
                            scope=lifecycle.binding_id or "none",
                            lifecycle_status=lifecycle.status,
                            state="blocked" if lifecycle.status == "failed" else "idle",
                            detail=lifecycle.failure,
                        )
                    )
                    continue
                binding = lifecycle.binding_id
                try:
                    with self.supervisor.effect(binding) as held:
                        runtime = background_effect_runtime(self.supervisor, held)
                        with frozen_binding_effect(runtime):
                            claim = claims.claim_next(
                                conn,
                                owner=f"{self.owner}:{binding}",
                                vault_binding_id=binding,
                                lease_seconds=_lease_seconds(),
                                exclude_topics=excluded,
                            )
                            outcome = (
                                "idle"
                                if claim is None
                                else self._dispatch_claim(
                                    conn, claim, lifecycle=held, runtime=runtime
                                )
                            )
                except (
                    BackgroundBindingIdle,
                    BackgroundLifecycleError,
                    BindingEffectLeaseError,
                    RegistryError,
                ) as exc:
                    # Only this binding performs no effect this tick; no row is redirected.
                    result.outcomes.append(
                        ScopeOutcome(
                            scope=binding,
                            lifecycle_status="failed",
                            state="blocked",
                            detail=str(exc),
                        )
                    )
                    continue
                result.outcomes.append(
                    ScopeOutcome(
                        scope=binding,
                        lifecycle_status="running",
                        state=outcome,
                        processed=int(outcome in {"processed", "reconciled_applied"}),
                    )
                )
        finally:
            try:
                conn.close()
            except Exception:  # pragma: no cover - defensive close
                pass
        return result


# -- governed quarantine administration -------------------------------------------------


class QueuedWorkAdminError(ValueError):
    """A governed quarantine command was refused (typed, redacted)."""


def _admin_supervisor(supervisor: Any | None) -> Any:
    if supervisor is not None:
        return supervisor
    from app.instance.background_supervisor import process_background_supervisor

    resolved = process_background_supervisor("queue-admin")
    if resolved is None:
        raise QueuedWorkAdminError("queued-work administration requires the completed MVR-06B handoff")
    return resolved


def list_quarantined(*, vault_binding_id: str | None = None) -> list[dict[str, Any]]:
    """Redacted quarantine inspection (ids, topic, binding, reason; never the payload)."""

    from app.services.outbox import _open_conn
    from app.services.outbox_claims import quarantined_rows, require_claim_schema

    conn = _open_conn()
    try:
        require_claim_schema(conn)
        return quarantined_rows(conn, vault_binding_id)
    finally:
        conn.close()


def reissue_quarantined_row(
    row_id: str, *, vault_binding_id: str, supervisor: Any | None = None
) -> dict[str, Any]:
    """Reissue a quarantined row only to its *same* stable binding, freshly re-authorized.

    The binding must have a running lifecycle (registered, enrolled, owned, GOV-allowed)
    under a fresh context; the row keeps its id, legacy key, and binding. A request
    naming any other binding is refused: quarantine can never retarget work.
    """

    from app.services.outbox import _open_conn
    from app.services.outbox_claims import reissue_quarantined, require_claim_schema

    resolved = _admin_supervisor(supervisor)
    lifecycles = {item.binding_id: item for item in resolved.reconcile_all()}
    lifecycle = lifecycles.get(vault_binding_id)
    if lifecycle is None or lifecycle.status != "running" or lifecycle.context is None:
        raise QueuedWorkAdminError(
            f"binding {vault_binding_id} is not running under current authority; "
            "re-authorize it before reissuing its work"
        )
    conn = _open_conn()
    try:
        require_claim_schema(conn)
        reissued = reissue_quarantined(
            conn,
            row_id,
            vault_binding_id=vault_binding_id,
            consumer_context={
                "context_id": lifecycle.context.context_id,
                "generation": lifecycle.generation,
                "binding_revision": lifecycle.binding_revision,
            },
        )
    finally:
        conn.close()
    if not reissued:
        raise QueuedWorkAdminError(
            "no quarantined row with that id belongs to that binding; quarantined work is "
            "reissued only to its original binding"
        )
    return {"row_id": row_id, "vault_binding_id": vault_binding_id, "state": "reissued"}


def drop_quarantined_row(row_id: str, *, reason: str) -> dict[str, Any]:
    from app.services.outbox import _open_conn
    from app.services.outbox_claims import drop_quarantined, require_claim_schema

    conn = _open_conn()
    try:
        require_claim_schema(conn)
        dropped = drop_quarantined(conn, row_id, reason=reason)
    finally:
        conn.close()
    if not dropped:
        raise QueuedWorkAdminError("no undelivered quarantined row has that id")
    return {"row_id": row_id, "state": "dropped"}


_PROCESS_DISPATCHERS: dict[int, ManyBindingDispatcher] = {}


def process_many_binding_dispatcher(supervisor: Any) -> ManyBindingDispatcher:
    """The one dispatcher (one stable claim owner) per process supervisor."""

    dispatcher = _PROCESS_DISPATCHERS.get(id(supervisor))
    if dispatcher is None or dispatcher.supervisor is not supervisor:
        dispatcher = ManyBindingDispatcher(supervisor)
        _PROCESS_DISPATCHERS[id(supervisor)] = dispatcher
    return dispatcher


__all__ = [
    "DEFAULT_CLAIM_LEASE_SECONDS",
    "EFFECT_CONTRACT_VERSION",
    "EffectContract",
    "ManyBindingDispatcher",
    "ManyBindingTick",
    "QueuedWorkAdminError",
    "ScopeOutcome",
    "consumer_context_for",
    "drop_quarantined_row",
    "effect_contract",
    "list_quarantined",
    "process_many_binding_dispatcher",
    "queue_configured",
    "reissue_quarantined_row",
    "revalidate_vault_bound_claim",
    "unadmitted_topics",
]
