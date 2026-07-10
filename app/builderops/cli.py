from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping

import click

from app.builderops.completeness_report import (
    build_completeness_report,
    load_records_from_db,
)
from app.builderops.ci_handoff_state import (
    CiHandoffStateError,
    build_ci_pending_handoff,
    find_ci_handoff,
    pending_check_summary,
    plan_ci_handoff_resume,
    record_ci_pending_handoff,
)
from app.builderops.ckm_reevaluation import (
    CkmReevaluationError,
    build_ckm_reevaluation_report,
)
from app.builderops.config import load_paths
from app.builderops.evidence_bridge import (
    EvidenceBridgeError,
    build_evidence_bridge_report,
)
from app.builderops.epic_dispatch import EpicDispatchError, build_dispatch_plan
from app.builderops.epic_delivery_ledger import (
    EpicDeliveryLedgerError,
    build_parent_epic_delivery_ledger,
)
from app.builderops.epic_lifecycle_plan import (
    EpicLifecyclePlanError,
    build_lifecycle_transition_plan,
)
from app.builderops.epic_run_state import (
    EpicRunStateError,
    apply_epic_run_update,
    create_epic_run_state,
    epic_run_state_path,
    load_epic_run_state,
    new_epic_run_state,
    unresolved_learning_evaluation_candidates,
    update_epic_run_state,
)
from app.builderops.models import BuilderOpsValidationError, normalize_actor
from app.builderops.pattern_routing import (
    PatternRoutingError,
    build_pattern_routing_report,
)
from app.builderops.promotion_gateway import BuilderOpsPromotionGateway
from app.builderops.projections import (
    PROJECTION_SPECS,
    BuilderOpsProjectionGenerator,
)
from app.builderops.ready_repair_batch import (
    ReadyRepairBatchError,
    build_ready_repair_batch,
)
from app.builderops.retrospective_closure import (
    RetrospectiveClosureError,
    build_retrospective_closure_ledger,
)
from app.builderops.store import SqliteBuilderOpsStore
from app.builderops.vault_queue import (
    VaultQueueError,
    claim_ticket,
    import_dispatcher_tasks,
    init_vault,
    move_ticket,
    next_ticket,
    note_ticket,
    release_ticket,
    renew_ticket,
    ticket_payload,
    validate_vault,
)
from app.dispatcher.config import load_paths as load_dispatcher_paths
from app.dispatcher.store import SqliteStore as DispatcherSqliteStore


def _parse_json_object(value: str | None, *, field: str) -> dict[str, Any]:
    if value is None or value == "":
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise click.BadParameter(f"{field} must be a JSON object") from exc
    if not isinstance(parsed, dict):
        raise click.BadParameter(f"{field} must be a JSON object")
    return parsed


def _load_json_object_file(path: Path | None, *, field: str) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise click.BadParameter(f"{field} must contain a JSON object") from exc
    if not isinstance(parsed, dict):
        raise click.BadParameter(f"{field} must contain a JSON object")
    return parsed


def _load_json_value_file(path: Path | None, *, field: str) -> Any:
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise click.BadParameter(f"{field} must contain valid JSON") from exc


def _merge_json_objects(*objects: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for item in objects:
        merged.update(item)
    return merged


def _parse_ref(value: str) -> dict[str, Any]:
    value = value.strip()
    if value.startswith("{"):
        return _parse_json_object(value, field="ref")
    if ":" not in value:
        raise click.BadParameter(
            "refs must be JSON objects or shorthand like github_issue:#1501"
        )
    ref_type, ref = value.split(":", 1)
    if not ref_type or not ref:
        raise click.BadParameter("ref shorthand requires ref_type and ref")
    return {"ref_type": ref_type, "ref": ref}


def _parse_refs(values: tuple[str, ...]) -> list[dict[str, Any]]:
    return [_parse_ref(value) for value in values]


def _parse_actor(value: str | None) -> dict[str, Any]:
    if value is None:
        return normalize_actor(None)
    value = value.strip()
    if value.startswith("{"):
        return normalize_actor(_parse_json_object(value, field="actor"))
    return normalize_actor(value)


def _emit(payload: Any, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    if isinstance(payload, list):
        for item in payload:
            click.echo(f"{item['id']}\t{item['object_type']}\t{item.get('summary', '')}")
        return
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _emit_projection_results(payload: list[dict[str, Any]], as_json: bool) -> None:
    if as_json:
        _emit(payload, True)
        return
    for item in payload:
        click.echo(
            f"{item['projection_type']}\t{item['record_count']}\t{item['path']}"
        )


def _epic_run_state_payload(
    *,
    dry_run: bool,
    path: Path,
    state: dict[str, Any],
    state_exists: bool,
) -> dict[str, Any]:
    unresolved_candidates = unresolved_learning_evaluation_candidates(state)
    return {
        "dry_run": dry_run,
        "path": str(path),
        "state": state,
        "state_exists": state_exists,
        "learning_evaluation_candidates_terminal": not unresolved_candidates,
        "unresolved_learning_evaluation_candidates": unresolved_candidates,
    }


def _extract_pr_number(pull_request: Mapping[str, Any]) -> int:
    value = pull_request.get("number", pull_request.get("pr_number"))
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise click.BadParameter("pull request number is required")
    return value


def _extract_pr_head_sha(pull_request: Mapping[str, Any]) -> str:
    for key in ("head_sha", "headRefOid"):
        value = pull_request.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    head = pull_request.get("head")
    if isinstance(head, Mapping):
        value = head.get("sha")
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise click.BadParameter("pull request head SHA is required")


def _store(ctx: click.Context) -> SqliteBuilderOpsStore:
    db_path = ctx.obj.get("db_path") if ctx.obj else None
    if db_path is None:
        paths = load_paths()
        paths.ensure()
        db_path = paths.db_path
    store = SqliteBuilderOpsStore(Path(db_path))
    store.initialize()
    return store


def _gateway(ctx: click.Context) -> BuilderOpsPromotionGateway:
    return BuilderOpsPromotionGateway(_store(ctx))


def _projection_generator(ctx: click.Context) -> BuilderOpsProjectionGenerator:
    return BuilderOpsProjectionGenerator(_store(ctx))


def _handle_create(
    ctx: click.Context,
    create_fn: Callable[..., Any],
    payload: dict[str, Any],
    as_json: bool,
) -> None:
    try:
        record = create_fn(**payload)
    except BuilderOpsValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(record, as_json)


@click.group(help="BuilderOps Vault local store commands.")
@click.option(
    "--db-path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Override BuilderOps SQLite DB path. Defaults to BUILDEROPS_DB_PATH or runtime/builderops/builderops.sqlite3.",
)
@click.pass_context
def builderops(ctx: click.Context, db_path: Path | None) -> None:
    ctx.ensure_object(dict)
    ctx.obj["db_path"] = db_path


@builderops.command("create-worklog", help="Create an AgentWorklog record.")
@click.option("--summary", required=True)
@click.option("--body", required=True)
@click.option("--task-context", default="{}", help="JSON object with task context.")
@click.option("--source-ref", multiple=True, required=True, help="JSON ref or shorthand ref_type:ref.")
@click.option("--created-by", default=None, help="Actor JSON object or agent id.")
@click.option("--idempotency-key", default=None)
@click.option("--promotion-status", default=None)
@click.option("--tag", "tags", multiple=True)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def create_worklog(
    ctx: click.Context,
    summary: str,
    body: str,
    task_context: str,
    source_ref: tuple[str, ...],
    created_by: str | None,
    idempotency_key: str | None,
    promotion_status: str | None,
    tags: tuple[str, ...],
    as_json: bool,
) -> None:
    payload: dict[str, Any] = {
        "summary": summary,
        "body": body,
        "task_context": _parse_json_object(task_context, field="task_context"),
        "source_refs": _parse_refs(source_ref),
        "created_by": _parse_actor(created_by),
    }
    if idempotency_key:
        payload["idempotency_key"] = idempotency_key
    if promotion_status:
        payload["promotion_status"] = promotion_status
    if tags:
        payload["tags"] = list(tags)
    _handle_create(ctx, _store(ctx).create_agent_worklog, payload, as_json)


@builderops.command("create-learning-signal", help="Create a LearningSignal record.")
@click.option("--summary", required=True)
@click.option("--content", required=True)
@click.option("--signal-type", required=True)
@click.option("--source-ref", multiple=True, required=True, help="JSON ref or shorthand ref_type:ref.")
@click.option("--created-by", default=None, help="Actor JSON object or agent id.")
@click.option("--idempotency-key", default=None)
@click.option("--promotion-status", default=None)
@click.option("--tag", "tags", multiple=True)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def create_learning_signal(
    ctx: click.Context,
    summary: str,
    content: str,
    signal_type: str,
    source_ref: tuple[str, ...],
    created_by: str | None,
    idempotency_key: str | None,
    promotion_status: str | None,
    tags: tuple[str, ...],
    as_json: bool,
) -> None:
    payload: dict[str, Any] = {
        "summary": summary,
        "content": content,
        "signal_type": signal_type,
        "source_refs": _parse_refs(source_ref),
        "created_by": _parse_actor(created_by),
    }
    if idempotency_key:
        payload["idempotency_key"] = idempotency_key
    if promotion_status:
        payload["promotion_status"] = promotion_status
    if tags:
        payload["tags"] = list(tags)
    _handle_create(ctx, _store(ctx).create_learning_signal, payload, as_json)


@builderops.command("create-promotion-intent", help="Create a PromotionIntent record.")
@click.option("--summary", required=True)
@click.option("--target-authority-surface", required=True)
@click.option("--target-action", required=True)
@click.option("--target-ref", required=True)
@click.option("--target-authority-class", required=True)
@click.option("--intended-output", required=True)
@click.option("--source-ref", multiple=True, required=True, help="JSON ref or shorthand ref_type:ref.")
@click.option("--created-by", default=None, help="Actor JSON object or agent id.")
@click.option("--idempotency-key", default=None)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def create_promotion_intent(
    ctx: click.Context,
    summary: str,
    target_authority_surface: str,
    target_action: str,
    target_ref: str,
    target_authority_class: str,
    intended_output: str,
    source_ref: tuple[str, ...],
    created_by: str | None,
    idempotency_key: str | None,
    as_json: bool,
) -> None:
    payload = {
        "summary": summary,
        "target_authority_surface": target_authority_surface,
        "target_action": target_action,
        "target_ref": target_ref,
        "target_authority_class": target_authority_class,
        "intended_output": intended_output,
        "source_refs": _parse_refs(source_ref),
        "created_by": _parse_actor(created_by),
    }
    if idempotency_key:
        payload["idempotency_key"] = idempotency_key
    _handle_create(ctx, _store(ctx).create_promotion_intent, payload, as_json)


@builderops.command("create-docs-freshness-record", help="Create a DocsFreshnessRecord.")
@click.option("--summary", required=True)
@click.option("--doc-ref", required=True, help="JSON ref or shorthand ref_type:ref.")
@click.option("--owner", required=True)
@click.option("--review-cadence", required=True)
@click.option("--freshness-posture", required=True)
@click.option("--drift-status", default=None)
@click.option("--last-reviewed-at", required=True)
@click.option(
    "--last-verified-against",
    multiple=True,
    help="JSON ref or shorthand ref_type:ref.",
)
@click.option("--last-verified-at", default=None)
@click.option("--next-review-due-at", required=True)
@click.option("--stale-reason", multiple=True)
@click.option(
    "--freshness-evidence-ref",
    multiple=True,
    help="JSON ref or shorthand ref_type:ref.",
)
@click.option("--next-review-owner", default=None)
@click.option("--review-note", default=None)
@click.option("--source-ref", multiple=True, required=True, help="JSON ref or shorthand ref_type:ref.")
@click.option("--created-by", default=None, help="Actor JSON object or agent id.")
@click.option("--idempotency-key", default=None)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def create_docs_freshness_record(
    ctx: click.Context,
    summary: str,
    doc_ref: str,
    owner: str,
    review_cadence: str,
    freshness_posture: str,
    drift_status: str | None,
    last_reviewed_at: str,
    last_verified_against: tuple[str, ...],
    last_verified_at: str | None,
    next_review_due_at: str,
    stale_reason: tuple[str, ...],
    freshness_evidence_ref: tuple[str, ...],
    next_review_owner: str | None,
    review_note: str | None,
    source_ref: tuple[str, ...],
    created_by: str | None,
    idempotency_key: str | None,
    as_json: bool,
) -> None:
    payload = {
        "summary": summary,
        "doc_ref": _parse_ref(doc_ref),
        "owner": owner,
        "review_cadence": review_cadence,
        "freshness_posture": freshness_posture,
        "last_reviewed_at": last_reviewed_at,
        "next_review_due_at": next_review_due_at,
        "source_refs": _parse_refs(source_ref),
        "created_by": _parse_actor(created_by),
    }
    if drift_status:
        payload["drift_status"] = drift_status
    if last_verified_against:
        payload["last_verified_against"] = _parse_refs(last_verified_against)
    if last_verified_at:
        payload["last_verified_at"] = last_verified_at
    if stale_reason:
        payload["stale_reasons"] = list(stale_reason)
    if freshness_evidence_ref:
        payload["freshness_evidence_refs"] = _parse_refs(freshness_evidence_ref)
    if next_review_owner:
        payload["next_review_owner"] = next_review_owner
    if review_note:
        payload["review_notes"] = review_note
    if idempotency_key:
        payload["idempotency_key"] = idempotency_key
    _handle_create(ctx, _store(ctx).create_docs_freshness_record, payload, as_json)


@builderops.command("append-receipt", help="Append a BuilderOpsReceipt record.")
@click.option("--summary", required=True)
@click.option("--event-type", required=True)
@click.option("--actor", required=True, help="Actor JSON object or agent id.")
@click.option("--occurred-at", required=True)
@click.option("--target-ref", multiple=True, required=True, help="JSON ref or shorthand ref_type:ref.")
@click.option("--action", required=True)
@click.option("--receipt-body", required=True)
@click.option("--idempotency-key", required=True)
@click.option("--source-ref", multiple=True, required=True, help="JSON ref or shorthand ref_type:ref.")
@click.option("--created-by", default=None, help="Actor JSON object or agent id.")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def append_receipt(
    ctx: click.Context,
    summary: str,
    event_type: str,
    actor: str,
    occurred_at: str,
    target_ref: tuple[str, ...],
    action: str,
    receipt_body: str,
    idempotency_key: str,
    source_ref: tuple[str, ...],
    created_by: str | None,
    as_json: bool,
) -> None:
    parsed_actor = _parse_actor(actor)
    payload = {
        "summary": summary,
        "event_type": event_type,
        "actor": parsed_actor,
        "occurred_at": occurred_at,
        "target_refs": _parse_refs(target_ref),
        "action": action,
        "receipt_body": receipt_body,
        "idempotency_key": idempotency_key,
        "source_refs": _parse_refs(source_ref),
        "created_by": _parse_actor(created_by) if created_by else parsed_actor,
    }
    _handle_create(ctx, _store(ctx).append_receipt, payload, as_json)


@builderops.command("create-roadmap-execution-item", help="Create a RoadmapExecutionItem.")
@click.option("--summary", required=True)
@click.option("--roadmap-ref", required=True, help="JSON ref or shorthand ref_type:ref.")
@click.option("--theme", default=None)
@click.option("--capability", default=None)
@click.option("--execution-state", required=True)
@click.option("--status", default=None)
@click.option("--owner", required=True)
@click.option("--active-issue", multiple=True, help="JSON ref or shorthand ref_type:ref.")
@click.option("--blocker", multiple=True)
@click.option("--last-movement", default=None)
@click.option("--next-decision", required=True)
@click.option("--shipped-ref", multiple=True, help="JSON ref or shorthand ref_type:ref.")
@click.option("--source-ref", multiple=True, required=True, help="JSON ref or shorthand ref_type:ref.")
@click.option("--created-by", default=None, help="Actor JSON object or agent id.")
@click.option("--idempotency-key", default=None)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def create_roadmap_execution_item(
    ctx: click.Context,
    summary: str,
    roadmap_ref: str,
    theme: str | None,
    capability: str | None,
    execution_state: str,
    status: str | None,
    owner: str,
    active_issue: tuple[str, ...],
    blocker: tuple[str, ...],
    last_movement: str | None,
    next_decision: str,
    shipped_ref: tuple[str, ...],
    source_ref: tuple[str, ...],
    created_by: str | None,
    idempotency_key: str | None,
    as_json: bool,
) -> None:
    payload = {
        "summary": summary,
        "roadmap_ref": _parse_ref(roadmap_ref),
        "execution_state": execution_state,
        "owner": owner,
        "next_decision": next_decision,
        "source_refs": _parse_refs(source_ref),
        "created_by": _parse_actor(created_by),
    }
    if theme:
        payload["theme"] = theme
    if capability:
        payload["capability"] = capability
    if status:
        payload["status"] = status
    if active_issue:
        payload["active_issues"] = _parse_refs(active_issue)
    if blocker:
        payload["blockers"] = list(blocker)
    if last_movement:
        payload["last_movement"] = last_movement
    if shipped_ref:
        payload["shipped_refs"] = _parse_refs(shipped_ref)
    if idempotency_key:
        payload["idempotency_key"] = idempotency_key
    _handle_create(ctx, _store(ctx).create_roadmap_execution_item, payload, as_json)


@builderops.group(
    "retrospective-closure",
    help="Build observe-only retrospective terminal-outcome ledgers.",
)
def retrospective_closure() -> None:
    """Retrospective and reevaluation closure helpers."""


@retrospective_closure.command(
    "check",
    help="Report whether processed signals have terminal outcomes.",
)
@click.option(
    "--signals-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="JSON list of in-scope signals, or object with a signals field.",
)
@click.option(
    "--outcomes-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="JSON list of terminal outcomes, or object with an outcomes field.",
)
@click.option("--json", "as_json", is_flag=True)
def retrospective_closure_check(
    signals_file: Path,
    outcomes_file: Path,
    as_json: bool,
) -> None:
    signals_payload = _load_json_value_file(signals_file, field="signals-file")
    outcomes_payload = _load_json_value_file(outcomes_file, field="outcomes-file")
    signals = (
        signals_payload.get("signals", signals_payload)
        if isinstance(signals_payload, dict)
        else signals_payload
    )
    outcomes = (
        outcomes_payload.get("outcomes", outcomes_payload)
        if isinstance(outcomes_payload, dict)
        else outcomes_payload
    )
    if not isinstance(signals, list):
        raise click.BadParameter("signals-file must contain a list or a signals list")
    if not isinstance(outcomes, list):
        raise click.BadParameter("outcomes-file must contain a list or an outcomes list")
    try:
        payload = build_retrospective_closure_ledger(
            signals=signals,
            outcomes=outcomes,
        )
    except RetrospectiveClosureError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(payload, as_json)


@builderops.group(
    "evidence-bridge",
    help="Classify PR/CI/review evidence into observe-only reevaluation candidates.",
)
def evidence_bridge() -> None:
    """Evidence bridge helpers for continuous reevaluation."""


@evidence_bridge.command(
    "classify",
    help="Classify delivery evidence without mutating GitHub, Product, or runtime state.",
)
@click.option(
    "--evidence-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="JSON object with observed, unknown, and candidate evidence fields.",
)
@click.option("--json", "as_json", is_flag=True)
def evidence_bridge_classify(
    evidence_file: Path,
    as_json: bool,
) -> None:
    evidence = _load_json_value_file(evidence_file, field="evidence-file")
    if not isinstance(evidence, dict):
        raise click.BadParameter("evidence-file must contain a JSON object")
    try:
        payload = build_evidence_bridge_report(evidence)
    except EvidenceBridgeError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(payload, as_json)


@builderops.group(
    "completeness-report",
    help="Report learning and reevaluation signals without terminal outcomes.",
)
def completeness_report() -> None:
    """Observe-only completeness reporting for learning and reevaluation."""


@completeness_report.command(
    "check",
    help="Build an observe-only completeness report from BuilderOps records or fixtures.",
)
@click.option(
    "--records-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="JSON list of BuilderOps records, or object with records and learning_evaluation_candidates.",
)
@click.option(
    "--learning-log-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Optional docs/learning-log.md compatibility file to inspect.",
)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def completeness_report_check(
    ctx: click.Context,
    records_file: Path | None,
    learning_log_file: Path | None,
    as_json: bool,
) -> None:
    candidates: list[Mapping[str, Any]] = []
    if records_file is not None:
        payload = _load_json_value_file(records_file, field="records-file")
        if isinstance(payload, list):
            records = payload
            storage = {"available": True, "source": str(records_file), "record_count": len(records)}
        elif isinstance(payload, dict) and isinstance(payload.get("records"), list):
            records = payload["records"]
            candidates = _completeness_report_candidates(payload)
            storage = {"available": True, "source": str(records_file), "record_count": len(records)}
        else:
            raise click.BadParameter("records-file must contain a list or an object with records")
    else:
        db_path = ctx.obj.get("db_path") if ctx.obj else None
        if db_path is None:
            db_path = load_paths().db_path
        records, storage = load_records_from_db(Path(db_path))

    learning_log_text = (
        learning_log_file.read_text(encoding="utf-8")
        if learning_log_file is not None
        else None
    )
    payload = build_completeness_report(
        records=records,
        storage=storage,
        learning_log_text=learning_log_text,
        reevaluation_candidates=candidates,
    )
    _emit(payload, as_json)


def _completeness_report_candidates(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    candidates: list[Mapping[str, Any]] = []
    for key in ("learning_evaluation_candidates", "candidate", "candidates"):
        raw_candidates = payload.get(key, [])
        if not isinstance(raw_candidates, list):
            raise click.BadParameter(f"{key} must be a list")
        candidates.extend(raw_candidates)
    return candidates


@builderops.group(
    "ckm-reevaluation",
    help="Classify CKM/Kvasir projections as non-authoritative reevaluation input.",
)
def ckm_reevaluation() -> None:
    """Observe-only CKM reevaluation helpers."""


@ckm_reevaluation.command(
    "classify",
    help="Classify CKM projection findings without mutating Product, Runtime, or GitHub state.",
)
@click.option(
    "--projection-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="JSON object with projections and actions/candidate fields.",
)
@click.option("--json", "as_json", is_flag=True)
def ckm_reevaluation_classify(
    projection_file: Path,
    as_json: bool,
) -> None:
    payload = _load_json_value_file(projection_file, field="projection-file")
    if not isinstance(payload, dict):
        raise click.BadParameter("projection-file must contain a JSON object")
    try:
        report = build_ckm_reevaluation_report(payload)
    except CkmReevaluationError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(report, as_json)


@builderops.group(
    "pattern-routing",
    help="Classify repeated learning patterns into debt, fitness, issue, or discard routes.",
)
def pattern_routing() -> None:
    """Observe-only repeated-pattern routing helpers."""


@pattern_routing.command(
    "classify",
    help="Classify repeated Builder System patterns without mutating repo or GitHub state.",
)
@click.option(
    "--patterns-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="JSON object with a patterns list, or a JSON patterns list.",
)
@click.option("--json", "as_json", is_flag=True)
def pattern_routing_classify(
    patterns_file: Path,
    as_json: bool,
) -> None:
    payload = _load_json_value_file(patterns_file, field="patterns-file")
    if isinstance(payload, list):
        payload = {"patterns": payload}
    if not isinstance(payload, dict):
        raise click.BadParameter("patterns-file must contain a JSON object or list")
    try:
        report = build_pattern_routing_report(payload)
    except PatternRoutingError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(report, as_json)


@builderops.group(
    "ready-repair-batch",
    help="Plan or explicitly apply Ready repairs for epic child issues.",
)
def ready_repair_batch() -> None:
    """Batch readiness repair for epic runner child issues."""


@ready_repair_batch.command(
    "plan",
    help="Build a dry-run Ready repair report from an explicit child issue list.",
)
@click.option(
    "--children-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="JSON list of child issues, or object with an issues/children list.",
)
@click.option("--repo", default="RasmusTho/agentic-pkm-mvp", show_default=True)
@click.option(
    "--apply",
    "apply_repairs",
    is_flag=True,
    help="Execute proposed label/Project repairs for validator-gated ready candidates.",
)
@click.option("--json", "as_json", is_flag=True)
def ready_repair_batch_plan(
    children_file: Path,
    repo: str,
    apply_repairs: bool,
    as_json: bool,
) -> None:
    payload = _load_json_value_file(children_file, field="children-file")
    if isinstance(payload, list):
        issues = payload
    elif isinstance(payload, dict):
        issues = payload.get("issues", payload.get("children"))
    else:
        raise click.BadParameter("children-file must contain a list or object")
    if not isinstance(issues, list):
        raise click.BadParameter("children-file issues/children must be a list")
    try:
        report = build_ready_repair_batch(
            issues=issues,
            repo=repo,
            apply=apply_repairs,
        )
    except ReadyRepairBatchError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(report, as_json)


@builderops.group("vault", help="Operate the file-first Builder Ops Vault queue.")
def vault() -> None:
    """Markdown/YAML active work queue helpers."""


@vault.command("init", help="Create vault folders and AGENTS.md contract.")
@click.argument("root", type=click.Path(file_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def vault_init(root: Path, as_json: bool) -> None:
    _emit(init_vault(root), as_json)


@vault.command(
    "import-dispatcher",
    help="Plan or apply a one-time import from the dispatcher transition store.",
)
@click.argument("root", type=click.Path(file_okay=False, path_type=Path))
@click.option("--db-path", type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.option("--apply", "apply_import", is_flag=True, help="Write planned tickets.")
@click.option("--json", "as_json", is_flag=True)
def vault_import_dispatcher(
    root: Path,
    db_path: Path | None,
    apply_import: bool,
    as_json: bool,
) -> None:
    resolved_db = (db_path or load_dispatcher_paths().db_path).expanduser()
    if not resolved_db.is_file():
        raise click.ClickException(f"dispatcher database not found: {resolved_db}")
    store = DispatcherSqliteStore(resolved_db)
    try:
        payload = import_dispatcher_tasks(
            root,
            [task.to_dict() for task in store.list_tasks()],
            apply=apply_import,
        )
    except VaultQueueError as exc:
        raise click.ClickException(str(exc)) from exc
    payload["dispatcher_db"] = str(resolved_db)
    _emit(payload, as_json)


@vault.command("validate", help="Validate vault ticket and claim invariants.")
@click.argument("root", type=click.Path(file_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def vault_validate(root: Path, as_json: bool) -> None:
    payload = validate_vault(root)
    _emit(payload, as_json)
    if not payload["ok"]:
        raise click.ClickException("Builder Ops Vault validation failed")


@vault.command("next", help="Return the next Ready ticket without an active claim.")
@click.argument("root", type=click.Path(file_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def vault_next(root: Path, as_json: bool) -> None:
    try:
        ticket = next_ticket(root)
    except VaultQueueError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit({"ticket": ticket_payload(ticket) if ticket else None}, as_json)


@vault.command("claim", help="Claim a vault ticket using a transient claim file.")
@click.argument("root", type=click.Path(file_okay=False, path_type=Path))
@click.argument("ticket_ref")
@click.option("--agent", required=True)
@click.option("--session", default=None)
@click.option("--ttl-minutes", default=120, show_default=True, type=int)
@click.option("--takeover-stale", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def vault_claim(
    root: Path,
    ticket_ref: str,
    agent: str,
    session: str | None,
    ttl_minutes: int,
    takeover_stale: bool,
    as_json: bool,
) -> None:
    try:
        payload = claim_ticket(
            root,
            ticket_ref,
            agent=agent,
            session=session,
            ttl_minutes=ttl_minutes,
            takeover_stale=takeover_stale,
        )
    except VaultQueueError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(payload, as_json)


@vault.command("renew", help="Renew an active vault claim TTL.")
@click.argument("root", type=click.Path(file_okay=False, path_type=Path))
@click.argument("ticket_ref")
@click.option("--agent", required=True)
@click.option("--ttl-minutes", default=120, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
def vault_renew(
    root: Path,
    ticket_ref: str,
    agent: str,
    ttl_minutes: int,
    as_json: bool,
) -> None:
    try:
        payload = renew_ticket(
            root,
            ticket_ref,
            agent=agent,
            ttl_minutes=ttl_minutes,
        )
    except VaultQueueError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(payload, as_json)


@vault.command("move", help="Move a vault ticket to a status folder and update YAML.")
@click.argument("root", type=click.Path(file_okay=False, path_type=Path))
@click.argument("ticket_ref")
@click.argument("status")
@click.option("--actor", default="cli")
@click.option("--json", "as_json", is_flag=True)
def vault_move(root: Path, ticket_ref: str, status: str, actor: str, as_json: bool) -> None:
    try:
        payload = move_ticket(root, ticket_ref, status, actor=actor)
    except VaultQueueError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(payload, as_json)


@vault.command("note", help="Append a meaningful note receipt to a vault ticket.")
@click.argument("root", type=click.Path(file_okay=False, path_type=Path))
@click.argument("ticket_ref")
@click.argument("note")
@click.option("--actor", default="cli")
@click.option("--json", "as_json", is_flag=True)
def vault_note(root: Path, ticket_ref: str, note: str, actor: str, as_json: bool) -> None:
    try:
        payload = note_ticket(root, ticket_ref, note, actor=actor)
    except VaultQueueError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(payload, as_json)


@vault.command("release", help="Release a vault claim file.")
@click.argument("root", type=click.Path(file_okay=False, path_type=Path))
@click.argument("ticket_ref")
@click.option("--agent", required=True)
@click.option("--json", "as_json", is_flag=True)
def vault_release(root: Path, ticket_ref: str, agent: str, as_json: bool) -> None:
    try:
        payload = release_ticket(root, ticket_ref, agent=agent)
    except VaultQueueError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(payload, as_json)


@builderops.group("epic-run-state", help="Record local deliver-issue-set epic run state.")
def epic_run_state() -> None:
    """Local coordination evidence for deliver-issue-set runs."""


@epic_run_state.command(
    "record",
    help="Create or update an epic run-state file from explicit local evidence.",
)
@click.option("--epic-issue-number", required=True, type=int)
@click.option("--run-id", required=True)
@click.option(
    "--root",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Override epic run-state root. Defaults to runtime/builderops/epic-runs.",
)
@click.option("--update-json", default="{}", help="JSON object with run-state update fields.")
@click.option(
    "--update-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to a JSON object with run-state update fields.",
)
@click.option("--dry-run", is_flag=True, help="Preview the state without writing a file.")
@click.option("--json", "as_json", is_flag=True)
def record_epic_run_state(
    epic_issue_number: int,
    run_id: str,
    root: Path | None,
    update_json: str,
    update_file: Path | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    updates = _merge_json_objects(
        _load_json_object_file(update_file, field="update-file"),
        _parse_json_object(update_json, field="update-json"),
    )
    try:
        path = epic_run_state_path(run_id, root=root)
        state_exists = path.exists()
        if dry_run:
            if state_exists:
                base_state = load_epic_run_state(run_id, root=root)
                if base_state["epic_issue_number"] != epic_issue_number:
                    raise EpicRunStateError(
                        f"run_id {run_id!r} already belongs to epic "
                        f"{base_state['epic_issue_number']}"
                    )
            else:
                base_state = new_epic_run_state(epic_issue_number, run_id)
            state = apply_epic_run_update(base_state, **updates)
        elif state_exists:
            existing_state = load_epic_run_state(run_id, root=root)
            if existing_state["epic_issue_number"] != epic_issue_number:
                raise EpicRunStateError(
                    f"run_id {run_id!r} already belongs to epic "
                    f"{existing_state['epic_issue_number']}"
                )
            state = (
                update_epic_run_state(run_id, root=root, **updates)
                if updates
                else existing_state
            )
        else:
            state = create_epic_run_state(
                epic_issue_number,
                run_id,
                root=root,
                **updates,
            )
    except EpicRunStateError as exc:
        raise click.ClickException(str(exc)) from exc

    _emit(
        _epic_run_state_payload(
            dry_run=dry_run,
            path=path,
            state=state,
            state_exists=state_exists,
        ),
        as_json,
    )


@epic_run_state.command("show", help="Read an existing epic run-state file.")
@click.argument("run_id")
@click.option(
    "--root",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Override epic run-state root. Defaults to runtime/builderops/epic-runs.",
)
@click.option("--json", "as_json", is_flag=True)
def show_epic_run_state(run_id: str, root: Path | None, as_json: bool) -> None:
    try:
        _emit(load_epic_run_state(run_id, root=root), as_json)
    except (EpicRunStateError, FileNotFoundError) as exc:
        raise click.ClickException(str(exc)) from exc


@epic_run_state.command(
    "dispatch-plan",
    help="Dry-run runtime-neutral worker context packs for an epic run.",
)
@click.option("--epic-issue-number", required=True, type=int)
@click.option("--run-id", required=True)
@click.option(
    "--root",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Read existing epic run-state from this root when present; never writes.",
)
@click.option(
    "--candidates-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="JSON object with candidates and optional active_leases.",
)
@click.option("--max-parallel", default=2, show_default=True, type=int)
@click.option(
    "--runtime",
    "runtime_targets",
    multiple=True,
    help="Allowed worker runtime target. Repeat for Codex/Claude.",
)
@click.option("--json", "as_json", is_flag=True)
def dispatch_plan(
    epic_issue_number: int,
    run_id: str,
    root: Path | None,
    candidates_file: Path,
    max_parallel: int,
    runtime_targets: tuple[str, ...],
    as_json: bool,
) -> None:
    payload = _load_json_object_file(candidates_file, field="candidates-file")
    candidates = payload.get("candidates", [])
    active_leases = payload.get("active_leases", [])
    try:
        state = None
        if epic_run_state_path(run_id, root=root).exists():
            state = load_epic_run_state(run_id, root=root)
        plan = build_dispatch_plan(
            epic_issue_number=epic_issue_number,
            run_id=run_id,
            candidates=candidates,
            max_parallel=max_parallel,
            runtime_targets=runtime_targets or ("codex", "claude"),
            active_leases=active_leases,
            run_state=state,
        )
    except (EpicDispatchError, EpicRunStateError) as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(plan, as_json)


@epic_run_state.command(
    "lifecycle-plan",
    help="Dry-run claim/review/done lifecycle transition plan for an issue or PR.",
)
@click.option(
    "--transition",
    required=True,
    type=click.Choice(["claim", "review", "review-handoff", "done", "terminal"]),
)
@click.option(
    "--issue-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="JSON issue object, or an object with an issue field.",
)
@click.option(
    "--pr-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Optional JSON PR object, or an object with a pull_request/pr field.",
)
@click.option(
    "--checks-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Optional JSON list of checks, or an object with a checks field.",
)
@click.option("--actor", default=None, help="Optional GitHub login for claim assignment planning.")
@click.option(
    "--repo",
    default="OWNER/REPO",
    show_default=True,
    help="owner/repo for command text.",
)
@click.option("--json", "as_json", is_flag=True)
def lifecycle_plan(
    transition: str,
    issue_file: Path,
    pr_file: Path | None,
    checks_file: Path | None,
    actor: str | None,
    repo: str,
    as_json: bool,
) -> None:
    issue_payload = _load_json_value_file(issue_file, field="issue-file")
    pr_payload = _load_json_value_file(pr_file, field="pr-file")
    checks_payload = _load_json_value_file(checks_file, field="checks-file")

    issue = (
        issue_payload.get("issue", issue_payload)
        if isinstance(issue_payload, dict)
        else issue_payload
    )
    if isinstance(pr_payload, dict):
        pull_request = pr_payload.get("pull_request", pr_payload.get("pr", pr_payload))
    else:
        pull_request = pr_payload
    if isinstance(checks_payload, dict):
        checks = checks_payload.get("checks", checks_payload.get("check_runs", []))
    elif checks_payload is None:
        checks = []
    else:
        checks = checks_payload

    try:
        plan = build_lifecycle_transition_plan(
            transition=transition,
            issue=issue,
            pull_request=pull_request,
            checks=checks,
            actor=actor,
            repo=repo,
        )
    except EpicLifecyclePlanError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(plan, as_json)


@epic_run_state.group(
    "ledger",
    help="Render parent epic delivery ledger coordination evidence.",
)
def epic_delivery_ledger() -> None:
    """Parent epic ledger coordination evidence."""


@epic_delivery_ledger.command(
    "render",
    help="Render a parent epic delivery ledger without GitHub writes.",
)
@click.option("--epic-issue-number", required=True, type=int)
@click.option(
    "--children-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="JSON list of child entries, or an object with children.",
)
@click.option(
    "--live-truth-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Optional read-only live truth snapshot keyed by issue number.",
)
@click.option("--json", "as_json", is_flag=True)
def render_epic_delivery_ledger(
    epic_issue_number: int,
    children_file: Path,
    live_truth_file: Path | None,
    as_json: bool,
) -> None:
    children_payload = _load_json_value_file(children_file, field="children-file")
    live_truth_payload = _load_json_value_file(live_truth_file, field="live-truth-file")
    children = (
        children_payload.get("children", children_payload)
        if isinstance(children_payload, dict)
        else children_payload
    )
    if not isinstance(children, list):
        raise click.BadParameter("children-file must contain a list or object with children")
    live_truth = live_truth_payload if isinstance(live_truth_payload, dict) else None
    try:
        ledger = build_parent_epic_delivery_ledger(
            epic_issue_number=epic_issue_number,
            children=children,
            live_truth=live_truth,
        )
    except EpicDeliveryLedgerError as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        _emit(ledger, True)
    else:
        click.echo(ledger["markdown"], nl=False)


@epic_run_state.group(
    "ci-handoff",
    help="Record and resume-plan PR CI monitor handoffs.",
)
def ci_handoff() -> None:
    """PR CI wait handoff coordination evidence."""


@ci_handoff.command(
    "record",
    help="Record a PR as locally validated and waiting on CI.",
)
@click.option("--epic-issue-number", required=True, type=int)
@click.option("--run-id", required=True)
@click.option(
    "--root",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Override epic run-state root. Defaults to runtime/builderops/epic-runs.",
)
@click.option(
    "--pr-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="JSON PR object, or an object with a pull_request/pr field.",
)
@click.option(
    "--checks-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Optional JSON list of checks, or an object with a checks field.",
)
@click.option("--issue-number", default=None, type=int)
@click.option("--repo", default=None)
@click.option(
    "--validation-command",
    "validation_commands",
    multiple=True,
    required=True,
    help="Local validation command already run. Repeat for each command.",
)
@click.option("--review-state", required=True)
@click.option("--next-closure-action", required=True)
@click.option("--dry-run", is_flag=True, help="Preview the state without writing a file.")
@click.option("--json", "as_json", is_flag=True)
def record_ci_handoff(
    epic_issue_number: int,
    run_id: str,
    root: Path | None,
    pr_file: Path,
    checks_file: Path | None,
    issue_number: int | None,
    repo: str | None,
    validation_commands: tuple[str, ...],
    review_state: str,
    next_closure_action: str,
    dry_run: bool,
    as_json: bool,
) -> None:
    pr_payload = _load_json_value_file(pr_file, field="pr-file")
    pull_request = (
        pr_payload.get("pull_request", pr_payload.get("pr", pr_payload))
        if isinstance(pr_payload, dict)
        else pr_payload
    )
    if not isinstance(pull_request, Mapping):
        raise click.BadParameter("pr-file must contain a PR object")
    checks_payload = _load_json_value_file(checks_file, field="checks-file")
    if isinstance(checks_payload, dict):
        checks = checks_payload.get("checks", checks_payload.get("check_runs", []))
    elif checks_payload is None:
        checks = []
    else:
        checks = checks_payload

    try:
        path = epic_run_state_path(run_id, root=root)
        state_exists = path.exists()
        if state_exists:
            base_state = load_epic_run_state(run_id, root=root)
            if base_state["epic_issue_number"] != epic_issue_number:
                raise EpicRunStateError(
                    f"run_id {run_id!r} already belongs to epic "
                    f"{base_state['epic_issue_number']}"
                )
        else:
            base_state = new_epic_run_state(epic_issue_number, run_id)
        handoff = build_ci_pending_handoff(
            pr_number=_extract_pr_number(pull_request),
            head_sha=_extract_pr_head_sha(pull_request),
            local_validation=validation_commands,
            review_state=review_state,
            pending_checks=pending_check_summary(checks),
            next_closure_action=next_closure_action,
            issue_number=issue_number,
            repo=repo,
        )
        state = record_ci_pending_handoff(base_state, handoff)
        if not dry_run:
            if state_exists:
                state = update_epic_run_state(
                    run_id,
                    root=root,
                    ci_handoffs=[handoff],
                )
            else:
                state = create_epic_run_state(
                    epic_issue_number,
                    run_id,
                    root=root,
                    ci_handoffs=[handoff],
                )
    except (CiHandoffStateError, EpicRunStateError) as exc:
        raise click.ClickException(str(exc)) from exc

    _emit(
        {
            **_epic_run_state_payload(
                dry_run=dry_run,
                path=path,
                state=state,
                state_exists=state_exists,
            ),
            "handoff": handoff,
        },
        as_json,
    )


@ci_handoff.command(
    "resume-plan",
    help="Plan closure from a CI handoff and live PR/check evidence without writes.",
)
@click.option("--run-id", required=True)
@click.option(
    "--root",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Override epic run-state root. Defaults to runtime/builderops/epic-runs.",
)
@click.option("--pr-number", required=True, type=int)
@click.option(
    "--pr-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="JSON PR object, or an object with a pull_request/pr field.",
)
@click.option(
    "--checks-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="JSON list of checks, or an object with a checks field.",
)
@click.option("--json", "as_json", is_flag=True)
def resume_ci_handoff_plan(
    run_id: str,
    root: Path | None,
    pr_number: int,
    pr_file: Path,
    checks_file: Path,
    as_json: bool,
) -> None:
    pr_payload = _load_json_value_file(pr_file, field="pr-file")
    pull_request = (
        pr_payload.get("pull_request", pr_payload.get("pr", pr_payload))
        if isinstance(pr_payload, dict)
        else pr_payload
    )
    if not isinstance(pull_request, Mapping):
        raise click.BadParameter("pr-file must contain a PR object")
    checks_payload = _load_json_value_file(checks_file, field="checks-file")
    if isinstance(checks_payload, dict):
        checks = checks_payload.get("checks", checks_payload.get("check_runs", []))
    else:
        checks = checks_payload

    try:
        state = load_epic_run_state(run_id, root=root)
        handoff = find_ci_handoff(state, pr_number=pr_number)
        if handoff is None:
            raise CiHandoffStateError(f"no CI handoff found for PR #{pr_number}")
        plan = plan_ci_handoff_resume(
            handoff=handoff,
            live_pr=pull_request,
            checks=checks,
        )
    except (CiHandoffStateError, EpicRunStateError, FileNotFoundError) as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(plan, as_json)


@builderops.command("acquire-lease", help="Acquire or renew a BuilderOps record lease.")
@click.argument("record_id")
@click.option("--actor", required=True, help="Actor JSON object or agent id.")
@click.option("--ttl-seconds", default=5400, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def acquire_lease(
    ctx: click.Context,
    record_id: str,
    actor: str,
    ttl_seconds: int,
    as_json: bool,
) -> None:
    try:
        lease = _store(ctx).acquire_lease(
            record_id,
            actor=_parse_actor(actor),
            ttl_seconds=ttl_seconds,
        )
    except BuilderOpsValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(lease, as_json)


@builderops.command("release-lease", help="Release a BuilderOps record lease.")
@click.argument("lease_id")
@click.option("--actor", required=True, help="Actor JSON object or agent id.")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def release_lease(
    ctx: click.Context,
    lease_id: str,
    actor: str,
    as_json: bool,
) -> None:
    try:
        result = _store(ctx).release_lease(lease_id, actor=_parse_actor(actor))
    except BuilderOpsValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(result, as_json)


@builderops.command("transition", help="Transition a BuilderOps record state under a lease.")
@click.argument("record_id")
@click.option("--actor", required=True, help="Actor JSON object or agent id.")
@click.option("--lease-id", required=True)
@click.option("--idempotency-key", required=True)
@click.option("--source-ref", multiple=True, required=True, help="JSON ref or shorthand ref_type:ref.")
@click.option("--summary", required=True)
@click.option("--action", required=True)
@click.option("--receipt-body", required=True)
@click.option("--lifecycle-state", default=None)
@click.option("--promotion-status", default=None)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def transition(
    ctx: click.Context,
    record_id: str,
    actor: str,
    lease_id: str,
    idempotency_key: str,
    source_ref: tuple[str, ...],
    summary: str,
    action: str,
    receipt_body: str,
    lifecycle_state: str | None,
    promotion_status: str | None,
    as_json: bool,
) -> None:
    try:
        result = _store(ctx).transition_record_state(
            record_id,
            actor=_parse_actor(actor),
            lease_id=lease_id,
            idempotency_key=idempotency_key,
            source_refs=_parse_refs(source_ref),
            summary=summary,
            action=action,
            receipt_body=receipt_body,
            lifecycle_state=lifecycle_state,
            promotion_status=promotion_status,
        )
    except BuilderOpsValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(result, as_json)


@builderops.command("promotion-preview", help="Render a PromotionIntent proposal without side effects.")
@click.argument("record_id")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def promotion_preview(
    ctx: click.Context,
    record_id: str,
    as_json: bool,
) -> None:
    try:
        proposal = _gateway(ctx).render_proposal(record_id)
    except BuilderOpsValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(proposal, as_json)


@builderops.command("promotion-dry-run", help="Render a promotion proposal and append a dry-run receipt.")
@click.argument("record_id")
@click.option("--actor", required=True, help="Actor JSON object or agent id.")
@click.option("--idempotency-key", required=True)
@click.option("--source-ref", multiple=True, help="Optional receipt source ref override.")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def promotion_dry_run(
    ctx: click.Context,
    record_id: str,
    actor: str,
    idempotency_key: str,
    source_ref: tuple[str, ...],
    as_json: bool,
) -> None:
    try:
        result = _gateway(ctx).dry_run_promotion(
            record_id,
            actor=_parse_actor(actor),
            idempotency_key=idempotency_key,
            source_refs=_parse_refs(source_ref) if source_ref else None,
        )
    except BuilderOpsValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(result, as_json)


@builderops.command("promotion-transition", help="Transition a PromotionIntent through the gateway.")
@click.argument("record_id")
@click.option(
    "--decision",
    required=True,
    type=click.Choice(["accepted", "promoted", "rejected", "discarded"]),
)
@click.option("--actor", required=True, help="Actor JSON object or agent id.")
@click.option("--lease-id", required=True)
@click.option("--idempotency-key", required=True)
@click.option("--rationale", required=True)
@click.option("--source-ref", multiple=True, help="Optional transition source ref override.")
@click.option("--result-ref", multiple=True, help="Optional promoted target/result ref.")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def promotion_transition(
    ctx: click.Context,
    record_id: str,
    decision: str,
    actor: str,
    lease_id: str,
    idempotency_key: str,
    rationale: str,
    source_ref: tuple[str, ...],
    result_ref: tuple[str, ...],
    as_json: bool,
) -> None:
    try:
        result = _gateway(ctx).transition_intent(
            record_id,
            decision=decision,
            actor=_parse_actor(actor),
            lease_id=lease_id,
            idempotency_key=idempotency_key,
            rationale=rationale,
            source_refs=_parse_refs(source_ref) if source_ref else None,
            result_refs=_parse_refs(result_ref) if result_ref else None,
        )
    except BuilderOpsValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(result, as_json)


@builderops.command(
    "generate-projections",
    help="Generate non-authoritative BuilderOps Markdown projection files.",
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("docs/generated/builderops"),
    show_default=True,
)
@click.option(
    "--type",
    "projection_type",
    multiple=True,
    type=click.Choice(sorted(PROJECTION_SPECS)),
    help="Projection type to generate. Defaults to all projection types.",
)
@click.option("--generated-at", default=None, help="Override the generated timestamp.")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def generate_projections(
    ctx: click.Context,
    output_dir: Path,
    projection_type: tuple[str, ...],
    generated_at: str | None,
    as_json: bool,
) -> None:
    try:
        result = _projection_generator(ctx).write_projections(
            output_dir,
            projection_types=projection_type or None,
            generated_at=generated_at,
        )
    except BuilderOpsValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit_projection_results(result, as_json)


@builderops.command("list", help="List BuilderOps records.")
@click.option("--type", "object_type", default=None, help="Filter by BuilderOps object_type.")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def list_records(ctx: click.Context, object_type: str | None, as_json: bool) -> None:
    try:
        records = _store(ctx).list_records(object_type)
    except BuilderOpsValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(records, as_json)


@builderops.command("read", help="Read one BuilderOps record by id.")
@click.argument("record_id")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def read_record(ctx: click.Context, record_id: str, as_json: bool) -> None:
    record = _store(ctx).get_record(record_id)
    if record is None:
        raise click.ClickException(f"BuilderOps record not found: {record_id}")
    _emit(record, as_json)
