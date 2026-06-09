from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from app.builderops.config import load_paths
from app.builderops.models import BuilderOpsValidationError, normalize_actor
from app.builderops.promotion_gateway import BuilderOpsPromotionGateway
from app.builderops.projections import (
    PROJECTION_SPECS,
    BuilderOpsProjectionGenerator,
)
from app.builderops.store import SqliteBuilderOpsStore


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


def _handle_create(ctx: click.Context, create_fn, payload: dict[str, Any], as_json: bool) -> None:
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
