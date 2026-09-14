"""FCA-09 specialization of the existing PostgreSQL record/receipt transaction.

There is no separate state store: current selection is the immutable predecessor
chain in BuilderOpsReceipt records, serialized under one trial/acceptance guard.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any

from psycopg.types.json import Jsonb

from app.builderops.control_plane.models import AuthorityEnvelope, AuthorityObjectResult, canonical_repository
from app.builderops.owner_fact_producers import (
    CONTRACT, OUTCOME_PREFIX, OwnerFactRefusal, OwnerOutcomeAdmission, digest,
    outcome_record_id, outcome_request_hash, read_owner_binding, receipt_hash,
    validate_current_binding,
)

if TYPE_CHECKING:
    from app.builderops.control_plane.store import PostgresBuilderOpsStore


def is_owner_outcome(record_id: str, payload: Mapping[str, Any]) -> bool:
    body = payload.get("receipt_body")
    return record_id.startswith(OUTCOME_PREFIX) or payload.get("contract") == CONTRACT or (
        isinstance(body, Mapping) and body.get("contract") == CONTRACT
    )


def _lock(conn: Any, repository: str, subject: str, binding_hash: str) -> None:
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                 (f"owner-outcome:{repository}:{subject}:{binding_hash}",))


def _epoch(conn: Any) -> int:
    row = conn.execute("SELECT authority_epoch FROM builderops_authority_metadata WHERE singleton FOR SHARE").fetchone()
    if row is None:
        raise OwnerFactRefusal("owner_authority_history_unavailable", 503)
    return int(row["authority_epoch"])


def _history(conn: Any, repository: str, subject: str) -> list[dict[str, Any]]:
    # Every committed journal entry and idempotency result must still resolve
    # its immutable record. Starting only from surviving records could silently
    # select an older acceptance after a terminal correction disappeared.
    lineage = conn.execute(
        "SELECT journal.task_id, journal.receipt_sequence, journal.idempotency_key, "
        "record.record_id, record.payload, idem.request_hash, idem.result "
        "FROM builderops_receipts AS journal "
        "LEFT JOIN builderops_records AS record ON record.repository=journal.repository AND record.record_id=journal.task_id "
        "LEFT JOIN builderops_idempotency AS idem ON idem.repository=journal.repository AND idem.idempotency_key=journal.idempotency_key "
        "WHERE journal.repository=%s AND journal.authority_envelope->>'scope'='owner-outcome' "
        "AND journal.event_type IN ('owner_outcome_recorded','owner_outcome_corrected') "
        "AND journal.authority_envelope->'source_refs' ? %s",
        (repository, subject),
    ).fetchall()
    journal_keys = set()
    for row in lineage:
        if row["record_id"] is None or row["result"] is None:
            raise OwnerFactRefusal("owner_authority_history_unavailable", 503)
        if row["result"].get("object_id") != row["task_id"] or row["result"].get("receipt_sequence") != row["receipt_sequence"] or row["request_hash"] != row["payload"].get("receipt_body", {}).get("request_sha256"):
            raise OwnerFactRefusal("owner_history_conflict", 409)
        journal_keys.add(row["idempotency_key"])
    idem_rows = conn.execute(
        "SELECT idempotency_key FROM builderops_idempotency WHERE repository=%s "
        "AND authority_envelope->>'scope'='owner-outcome' AND authority_envelope->'source_refs' ? %s",
        (repository, subject),
    ).fetchall()
    if {row["idempotency_key"] for row in idem_rows} != journal_keys:
        raise OwnerFactRefusal("owner_authority_history_unavailable", 503)
    rows = conn.execute(
        "SELECT record.record_id, record.payload, record.authority_envelope, receipt.receipt_sequence "
        "FROM builderops_records AS record LEFT JOIN builderops_receipts AS receipt "
        "ON receipt.repository = record.repository AND receipt.task_id = record.record_id "
        "AND receipt.receipt_sequence::text = record.payload->>'receipt_sequence' "
        "AND receipt.authority_envelope->>'scope' = 'owner-outcome' "
        "AND receipt.event_type IN ('owner_outcome_recorded','owner_outcome_corrected') "
        "WHERE record.repository = %s AND record.record_type = 'BuilderOpsReceipt' "
        "AND record.payload->'receipt_body'->>'contract' = %s "
        "AND record.payload->'receipt_body'->'request'->>'subject_ref' = %s",
        (repository, CONTRACT, subject),
    ).fetchall()
    receipts = []
    seen = set()
    for row in rows:
        value = row["payload"]
        try:
            body, request = value["receipt_body"], value["receipt_body"]["request"]
            confirmation = body["confirmation_ref"]
            if (
                row["record_id"] in seen or row["receipt_sequence"] is None
                or row["record_id"] != value["id"]
                or value["receipt_sequence"] != row["receipt_sequence"]
                or value["hash"] != receipt_hash(value)
                or body["request_sha256"] != outcome_request_hash(request)
                or confirmation["request_sha256"] != body["request_sha256"]
                or confirmation["id"] != value["id"] + "#confirmation"
                or confirmation["human_principal"] != request["owner_actor"]["id"]
                or confirmation["authorization_ref"] != request["authorization_ref"]
                or request["repository"] != repository
                or value["actor"] != request["owner_actor"]
                or row["authority_envelope"]["actor"] != request["owner_actor"]["id"]
                or row["authority_envelope"]["scope"] != "owner-outcome"
                or request["fact_kind"] not in {"owner_trial", "owner_acceptance"}
                or datetime.fromisoformat(confirmation["confirmed_at"]) > datetime.fromisoformat(body["recorded_at"])
            ):
                raise ValueError
            seen.add(row["record_id"])
            receipts.append(value)
        except Exception as exc:
            raise OwnerFactRefusal("owner_history_incompatible", 409) from exc
    return receipts


def _selection(history: list[dict[str, Any]], binding_hash: str, kind: str) -> dict[str, Any] | None:
    slot = {r["id"]: r for r in history if r["binding_hash"] == binding_hash and r["receipt_body"]["request"]["fact_kind"] == kind}
    if not slot:
        return None
    roots = [r for r in slot.values() if r["receipt_body"]["request"]["expected_previous_receipt_id"] is None]
    if len(roots) != 1:
        raise OwnerFactRefusal("owner_history_conflict", 409)
    current = roots[0]
    visited = {current["id"]}
    while True:
        children = [r for r in slot.values() if r["receipt_body"]["request"]["expected_previous_receipt_id"] == current["id"]]
        if not children:
            if visited != set(slot):
                raise OwnerFactRefusal("owner_history_conflict", 409)
            return current
        if len(children) != 1 or children[0]["id"] in visited:
            raise OwnerFactRefusal("owner_history_conflict", 409)
        child = children[0]
        request = child["receipt_body"]["request"]
        if request["supersedes_receipt_id"] != current["id"] or request["correction_reason"] != "owner_correction" or child["receipt_sequence"] <= current["receipt_sequence"]:
            raise OwnerFactRefusal("owner_history_conflict", 409)
        current = child
        visited.add(current["id"])


def _valid_trial(trial: dict[str, Any] | None, trial_ref: Any) -> bool:
    return trial is not None and trial["id"] == trial_ref and trial["receipt_body"]["request"]["outcome"] == "tried"


def _project(receipt: dict[str, Any], history: list[dict[str, Any]], binding: dict[str, Any]) -> dict[str, str]:
    if receipt["binding_hash"] != binding["binding_hash"]:
        return {"status": "withdrawn", "reason": "source_binding_changed"}
    kind = receipt["receipt_body"]["request"]["fact_kind"]
    selected = _selection(history, binding["binding_hash"], kind)
    if selected is None or selected["id"] != receipt["id"]:
        return {"status": "superseded", "reason": "owner_correction"}
    request = receipt["receipt_body"]["request"]
    if binding["owner_grant_status"] != "available":
        return {"status": "withdrawn", "reason": "owner_grant_unavailable"}
    if binding["readiness_status"] != "current" and request["outcome"] != "unable_to_try":
        return {"status": "withdrawn", "reason": "readiness_withdrawn"}
    if kind == "owner_acceptance" and request["trial_receipt_ref"] is not None:
        trial = _selection(history, binding["binding_hash"], "owner_trial")
        if not _valid_trial(trial, request["trial_receipt_ref"]):
            return {"status": "withdrawn", "reason": "trial_corrected"}
    return {"status": "current", "reason": "source_and_lineage_verified"}


def commit_owner_outcome(
    store: PostgresBuilderOpsStore, *, envelope: AuthorityEnvelope,
    admission: OwnerOutcomeAdmission, idempotency_key: str, fault_at: str | None,
) -> AuthorityObjectResult:
    request = admission.request
    repository, subject = request["repository"], request["subject_ref"]
    if envelope.repository != repository or envelope.actor != request["owner_actor"]["id"]:
        raise OwnerFactRefusal("owner_principal_mismatch", 403)
    record_id = outcome_record_id(repository, idempotency_key)
    key = "owner-outcome:" + idempotency_key
    replayed = False
    with store._connect() as conn:
        conn.execute("SET LOCAL synchronous_commit = on")
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"idempotency:{repository}:{key}",))
        existing = conn.execute("SELECT request_hash, result FROM builderops_idempotency WHERE repository = %s AND idempotency_key = %s FOR UPDATE", (repository, key)).fetchone()
        if existing is not None:
            if existing["request_hash"] != admission.request_sha256:
                raise OwnerFactRefusal("idempotency_conflict", 409)
            history = _history(conn, repository, subject)
            original = next((r for r in history if r["id"] == record_id), None)
            if original is None:
                raise OwnerFactRefusal("owner_authority_history_unavailable", 503)
            provisional = store._authority_result(existing["result"], replayed=True)
            receipt_sequence = provisional.receipt_sequence
            replayed = True
        else:
            epoch = _epoch(conn)
            binding = admission.revalidate(epoch)
            _lock(conn, repository, subject, binding["binding_hash"])
            current_binding = admission.revalidate(epoch)
            validate_current_binding(request, binding)
            if binding["binding_hash"] != current_binding["binding_hash"]:
                raise OwnerFactRefusal("owner_binding_changed", 409)
            history = _history(conn, repository, subject)
            previous = _selection(history, binding["binding_hash"], request["fact_kind"])
            if request["expected_previous_receipt_id"] != (previous["id"] if previous else None):
                raise OwnerFactRefusal("current_receipt_conflict", 409)
            trial = _selection(history, binding["binding_hash"], "owner_trial")
            if request["fact_kind"] == "owner_acceptance" and (
                request["outcome"] == "accepted" or request["trial_receipt_ref"] is not None
            ) and not _valid_trial(trial, request["trial_receipt_ref"]):
                raise OwnerFactRefusal("trial_receipt_conflict", 409)
            # Recheck mutable permission and external source versions after all
            # guarded reads, immediately before generating commit metadata.
            store._fault(fault_at, "before_owner_outcome_commit")
            latest = admission.revalidate(epoch)
            if latest["binding_hash"] != binding["binding_hash"]:
                raise OwnerFactRefusal("owner_binding_changed", 409)
            recorded_at = store._database_now(conn)
            if datetime.fromisoformat(admission.confirmed_at) > recorded_at:
                raise OwnerFactRefusal("owner_confirmation_clock_unavailable", 503)
            stamp = recorded_at.isoformat()
            event = "owner_outcome_corrected" if previous else "owner_outcome_recorded"
            log = conn.execute(
                "INSERT INTO builderops_receipts(repository, task_id, event_type, idempotency_key, authority_envelope) VALUES (%s,%s,%s,%s,%s) RETURNING receipt_sequence",
                (repository, record_id, event, key, Jsonb(envelope.as_json())),
            ).fetchone()
            assert log is not None
            receipt_sequence = int(log["receipt_sequence"])
            body = {"contract": CONTRACT, "request": request, "request_sha256": admission.request_sha256,
                    "confirmation_ref": {"id": record_id + "#confirmation", "request_sha256": admission.request_sha256,
                                         "human_principal": envelope.actor, "confirmed_at": admission.confirmed_at,
                                         "authorization_ref": request["authorization_ref"]}, "recorded_at": stamp}
            sources = [{"ref_type": "source", "ref": ref, "authority_surface": "builderops"} for ref in envelope.source_refs]
            receipt = {"id": record_id, "object_type": "BuilderOpsReceipt", "authority_class": "receipt",
                "lifecycle_state": "active", "promotion_status": "not_promotable", "created_at": stamp, "updated_at": stamp,
                "created_by": {"actor_type": "service", "id": "builderops-control-plane"},
                "source_refs": sources, "target_refs": [{"ref_type": "subject", "ref": subject, "authority_surface": "github"}],
                "summary": "Explicit owner outcome recorded", "event_type": event, "actor": request["owner_actor"],
                "occurred_at": stamp, "action": "record_" + request["fact_kind"], "outcome": "succeeded",
                "receipt_body": body, "idempotency_key": idempotency_key, "binding_hash": binding["binding_hash"],
                "receipt_sequence": receipt_sequence}
            receipt["hash"] = receipt_hash(receipt)
            conn.execute("INSERT INTO builderops_records(repository, record_id, record_type, state, payload, authority_envelope) VALUES (%s,%s,'BuilderOpsReceipt','active',%s,%s)", (repository, record_id, Jsonb(receipt), Jsonb(envelope.as_json())))
            store._fault(fault_at, "after_owner_outcome_receipt")
            provisional = AuthorityObjectResult(repository=repository, object_kind="record", object_id=record_id,
                                                state="active", receipt_sequence=receipt_sequence, recovery_lsn="0/0")
            conn.execute("INSERT INTO builderops_idempotency(repository,idempotency_key,request_hash,result,authority_envelope) VALUES (%s,%s,%s,%s,%s)", (repository,key,admission.request_sha256,Jsonb(store._authority_result_json(provisional)),Jsonb(envelope.as_json())))
            # An intent is a rebuild request, not a stored projection. Rebuild
            # always rechecks the current chain, including trial withdrawal.
            intent = {"subject_ref": subject, "binding_hash": binding["binding_hash"], "receipt_id": record_id}
            conn.execute("INSERT INTO builderops_outbox(repository,operation_key,task_id,effect_type,payload,intent_receipt_sequence,authority_envelope) VALUES (%s,%s,%s,'owner_outcomes.project',%s,%s,%s)",
                         (repository,digest(intent),record_id,Jsonb(intent),receipt_sequence,Jsonb(envelope.as_json())))
            store._fault(fault_at, "after_owner_outcome_intent")
    store._fault(fault_at, "after_owner_outcome_commit")
    result = store._finalize_authority_object(repository,key,receipt_sequence,store._flushed_lsn(),replayed=replayed)
    with store._connect() as conn:
        conn.execute("UPDATE builderops_outbox SET intent_lsn=COALESCE(intent_lsn,%s) WHERE repository=%s AND intent_receipt_sequence=%s AND effect_type='owner_outcomes.project'", (result.recovery_lsn,repository,receipt_sequence))
    return result


def read_owner_outcomes(
    store: PostgresBuilderOpsStore, repository: str, subject_ref: str, *, idempotency_key: str | None,
    grant_reader: Callable[[str, str], bool],
) -> dict[str, Any]:
    repository = canonical_repository(repository)
    with store._connect() as conn:
        epoch = _epoch(conn)
        historical = _history(conn, repository, subject_ref)
        original = None
        if idempotency_key is not None:
            existing = conn.execute("SELECT result FROM builderops_idempotency WHERE repository=%s AND idempotency_key=%s", (repository,"owner-outcome:" + idempotency_key)).fetchone()
            if existing is None:
                raise OwnerFactRefusal("owner_outcome_not_found", 404)
            original = next((r for r in historical if r["id"] == existing["result"]["object_id"]), None)
            if original is None:
                raise OwnerFactRefusal("owner_authority_history_unavailable", 503)
        try:
            binding = read_owner_binding(repository, subject_ref, authority_epoch=epoch, allow_withdrawn_readiness=True)
        except OwnerFactRefusal:
            if original is None:
                raise
            return {"contract": "builder_owner_facts.v1", "repository": repository, "subject_ref": subject_ref,
                    "receipt": original, "projection": {"status": "unavailable", "reason": "current_source_unavailable"},
                    "authority_epoch": epoch, "observed_at": store._database_now(conn).isoformat()}
        _lock(conn, repository, subject_ref, binding["binding_hash"])
        current_binding = read_owner_binding(repository, subject_ref, authority_epoch=epoch, allow_withdrawn_readiness=True)
        if current_binding["binding_hash"] != binding["binding_hash"]:
            raise OwnerFactRefusal("owner_binding_changed", 409)
        binding = current_binding
        binding["owner_grant_status"] = "available" if grant_reader(repository, binding["owner_actor"]["id"]) else "unavailable"
        history = _history(conn, repository, subject_ref)
        facts: dict[str, Any] = {"ready_to_try": binding if binding["readiness_status"] == "current" else None, "owner_trial": None, "owner_acceptance": None}
        for kind in ("owner_trial", "owner_acceptance"):
            current = _selection(history, binding["binding_hash"], kind)
            if current is not None and _project(current, history, binding)["status"] == "current":
                facts[kind] = current
        result: dict[str, Any] = {"contract": "builder_owner_facts.v1", "repository": repository,
            "subject_ref": subject_ref, "binding": binding, "facts": facts, "history": history,
            "authority_epoch": epoch, "observed_at": store._database_now(conn).isoformat()}
        if idempotency_key is not None:
            existing = conn.execute("SELECT result FROM builderops_idempotency WHERE repository=%s AND idempotency_key=%s", (repository,"owner-outcome:" + idempotency_key)).fetchone()
            if existing is None:
                raise OwnerFactRefusal("owner_outcome_not_found", 404)
            receipt = next((r for r in history if r["id"] == existing["result"]["object_id"]), None)
            if receipt is None:
                raise OwnerFactRefusal("owner_authority_history_unavailable", 503)
            result.update(receipt=receipt, projection=_project(receipt, history, binding))
        return result
