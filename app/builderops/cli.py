from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, cast

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
from app.builderops.ckm.models import CkmValidationError
from app.builderops.ckm.ingest_github import ingest_github
from app.builderops.ckm.ingest_repo import ingest_repo
from app.builderops.ckm.linkers import link_deterministic
from app.builderops.ckm.semantic import (
    SemanticAssociationError,
    _confirm_edge_from_cli,
    associate_unlinked_artifacts,
    reapply_confirmation_receipts,
)
from app.builderops.ckm.seed import SeedManifestError, seed_capabilities
from app.builderops.ckm.store import CkmStore
from app.builderops.config import BuilderOpsPaths, load_paths
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
from app.builderops.model_inquiry import ModelInquiryService
from app.builderops.model_inquiry_adapters import AdapterUnavailableError
from app.builderops.model_inquiry_runner import ModelInquiryRunner
from app.builderops.model_inquiry_promotion import (
    DEFAULT_LABELS,
    GhApiIssueClient,
    ModelInquiryPromotionError,
    ModelInquiryPromotionGateway,
)
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
    init_vault,
    release_ticket,
    validate_vault,
    vault_paths,
)


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
    paths = _effective_paths(ctx)
    paths.ensure()
    store = SqliteBuilderOpsStore(paths.db_path)
    store.initialize()
    return store


def _ckm_store(ctx: click.Context) -> CkmStore:
    return CkmStore.open_default(_effective_paths(ctx))


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


def _effective_paths(ctx: click.Context) -> BuilderOpsPaths:
    # ``ckm`` is reachable both nested under the ``builderops`` group (whose
    # callback populates ``ctx.obj["db_path"]`` via ``--db-path``) and
    # mounted directly at the standalone CLI root (which has no such
    # callback, so ``ctx.obj`` is None). Tolerate the missing dict rather
    # than raising an AttributeError.
    obj = ctx.obj or {}
    try:
        return load_paths(db_path_override=obj.get("db_path"))
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


@builderops.group("vault", help="Operate the file-first Builder Ops Vault queue.")
def vault() -> None:
    """Shared Markdown queue and advisory TTL-claim helpers."""


@vault.command("paths", help="Show shared vault and local operational paths.")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def vault_paths_command(ctx: click.Context, as_json: bool) -> None:
    paths = _effective_paths(ctx)
    _emit(vault_paths(paths), as_json)


@vault.command("init", help="Create shared Markdown queue directories only.")
@click.argument("root", type=click.Path(file_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def vault_init(root: Path, as_json: bool) -> None:
    try:
        payload = init_vault(root)
    except VaultQueueError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(payload, as_json)


@vault.command("validate", help="Validate shared-vault separation and ticket status integrity.")
@click.argument("root", type=click.Path(file_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def vault_validate(ctx: click.Context, root: Path, as_json: bool) -> None:
    paths = _effective_paths(ctx)
    payload = validate_vault(root, paths)
    _emit(payload, as_json)
    if not payload["ok"]:
        raise click.ClickException("Builder Ops Vault validation failed")


@vault.command("claim", help="Write a shared advisory TTL claim for a Ready ticket.")
@click.argument("root", type=click.Path(file_okay=False, path_type=Path))
@click.argument("ticket_ref")
@click.option("--agent", required=True)
@click.option("--ttl-minutes", default=120, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
def vault_claim(root: Path, ticket_ref: str, agent: str, ttl_minutes: int, as_json: bool) -> None:
    try:
        payload = claim_ticket(root, ticket_ref, agent=agent, ttl_minutes=ttl_minutes)
    except VaultQueueError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(payload, as_json)


@vault.command("release", help="Release this agent's shared advisory ticket claims.")
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


@builderops.group("ckm", help="Operate the projection-only Capability Knowledge Model.")
@click.pass_context
def ckm(ctx: click.Context) -> None:
    """CKM commands operate only on additive BuilderOps state.

    ``ckm`` is mounted both under ``builderops`` (whose callback already
    populates ``ctx.obj`` with a dict) and directly at the standalone CLI
    root (which does not). ``ensure_object`` is a no-op when ``ctx.obj`` is
    already a truthy dict inherited from the ``builderops`` parent, and
    creates an empty dict when reached from the root, so every current and
    future ``ckm`` subcommand can safely assume ``ctx.obj`` is a dict rather
    than needing to know which mount point it was reached through.
    """

    ctx.ensure_object(dict)


@ckm.command("seed", help="Seed reviewed SBS and capability-contract taxonomy into the CEG.")
@click.pass_context
def ckm_seed(ctx: click.Context) -> None:
    store = _ckm_store(ctx)
    try:
        store.ensure_schema()
        result = seed_capabilities(store)
    except SeedManifestError as exc:
        # Manifest validation runs entirely before any write, so this never
        # leaves partial store state.
        raise click.ClickException(str(exc)) from exc
    except (sqlite3.Error, CkmValidationError) as exc:
        # A write-path failure (e.g. a concurrent writer holding the
        # BuilderOps sqlite file) can leave the CEG partially seeded, since
        # each manifest entry upserts in its own transaction rather than one
        # transaction spanning the whole run. Surface a clear operator
        # message instead of a raw traceback; re-running `ckm seed` is safe
        # because seeding is idempotent (INV-CKM-7) and will pick up
        # wherever it left off.
        raise click.ClickException(
            f"ckm seed failed while writing to the store: {exc}. "
            "Seeding is idempotent; re-run `ckm seed` to resume from where it stopped."
        ) from exc
    click.echo(f"seeded {result['seeded']} capabilities, {result['changed']} changed")


@ckm.command("ingest", help="Ingest repository and GitHub delivery artifacts into the CEG.")
@click.option("--source", type=click.Choice(["repo", "github", "all"]), required=True)
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=Path.cwd)
@click.option("--git-limit", type=click.IntRange(1, 5000), default=500, show_default=True)
@click.pass_context
def ckm_ingest(ctx: click.Context, source: str, repo_root: Path, git_limit: int) -> None:
    try:
        store = _ckm_store(ctx)
        result: dict[str, Any] = {}
        if source in {"repo", "all"}:
            result["repo"] = ingest_repo(store, repo_root, git_limit=git_limit)
        if source in {"github", "all"}:
            result["github"] = ingest_github(store)
    except (OSError, ValueError, sqlite3.Error, subprocess.CalledProcessError) as exc:
        raise click.ClickException(f"ckm ingestion failed: {exc}") from exc
    if source == "github" and result["github"]["status"] != "ok":
        click.echo(result["github"]["status"])
        return
    segments: list[str] = []
    for name, data in result.get("repo", {}).items():
        segments.append(f"{name}: {data['artifacts']} artifacts (+{data['changed']})")
    github = result.get("github")
    if github:
        if github["status"] != "ok":
            segments.append(github["status"])
        else:
            segments.extend(
                f"github {name}: {data['artifacts']} artifacts (+{data['changed']})"
                for name, data in (("issues", github["issues"]), ("pull_requests", github["pull_requests"]))
            )
    click.echo("; ".join(segments))


@ckm.command("link", help="Create confirmed deterministic CKM evidence edges.")
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=Path.cwd)
@click.pass_context
def ckm_link(ctx: click.Context, repo_root: Path) -> None:
    try:
        store = _ckm_store(ctx)
        result = link_deterministic(store, repo_root)
        confirmations_reapplied = reapply_confirmation_receipts(store)
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise click.ClickException(f"ckm linking failed: {exc}") from exc
    click.echo(
        "; ".join(
            [f"{name}: {result[name]} new" for name in ("matrix", "spec", "adr", "test_code", "github_ref")]
            + [
                f"confirmations reapplied: {confirmations_reapplied}",
                f"unlinked artifacts: {result['unlinked_artifacts']}",
            ]
        )
    )


@ckm.command("associate", help="Propose fenced inferred edges for unlinked CKM artifacts.")
@click.option("--limit", type=click.IntRange(1, 1000), default=200, show_default=True)
@click.option(
    "--confidence-floor", type=click.FloatRange(0.0, 1.0), default=0.6, show_default=True
)
@click.pass_context
def ckm_associate(ctx: click.Context, limit: int, confidence_floor: float) -> None:
    try:
        result = associate_unlinked_artifacts(
            _ckm_store(ctx), limit=limit, confidence_floor=confidence_floor
        )
    except (SemanticAssociationError, CkmValidationError, sqlite3.Error) as exc:
        raise click.ClickException(f"ckm semantic association failed: {exc}") from exc
    if result.status != "ok":
        click.echo(result.status)
        return
    provider_model = (
        f"; model={result.provider}:{result.model}" if result.provider and result.model else ""
    )
    click.echo(
        f"proposed {result.proposed} candidate edges; discarded {result.discarded} below floor; "
        f"{result.no_match} no-match{provider_model}"
    )


@ckm.command("confirm-edge", help="Confirm one inferred candidate edge with a durable receipt.")
@click.argument("edge_id")
@click.pass_context
def ckm_confirm_edge(ctx: click.Context, edge_id: str) -> None:
    try:
        receipt = _confirm_edge_from_cli(_ckm_store(ctx), edge_id)
    except (CkmValidationError, sqlite3.Error) as exc:
        raise click.ClickException(f"ckm edge confirmation failed: {exc}") from exc
    click.echo(f"edge {edge_id} confirmed; receipt builderops://receipts/{receipt['id']}")


@builderops.group("inquiry", help="Persist and inspect pre-ticket model inquiry artifacts.")
def inquiry() -> None:
    """File-first inquiry start, trace, and restart planning."""


@inquiry.command("start", help="Persist an immutable inquiry question before model execution.")
@click.option(
    "--question-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--workflow", required=True)
@click.option("--inquiry-id", default=None)
@click.option("--source-ref", multiple=True)
@click.option("--created-by", default=None)
@click.option("--json", "as_json", is_flag=True)
def inquiry_start(
    question_file: Path,
    workflow: str,
    inquiry_id: str | None,
    source_ref: tuple[str, ...],
    created_by: str | None,
    as_json: bool,
) -> None:
    try:
        question = question_file.read_text(encoding="utf-8")
        refs = (
            _parse_refs(source_ref)
            if source_ref
            else [{"ref_type": "file", "ref": str(question_file.resolve())}]
        )
        payload = ModelInquiryService.from_env().start(
            question=question,
            workflow=workflow,
            inquiry_id=inquiry_id,
            source_refs=refs,
            created_by=_parse_actor(created_by),
        )
    except (OSError, UnicodeError, BuilderOpsValidationError) as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(payload, as_json)


@inquiry.command("trace", help="Return a deterministic trace over committed inquiry artifacts.")
@click.argument("inquiry_id")
@click.option("--include-delivery", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def inquiry_trace(inquiry_id: str, include_delivery: bool, as_json: bool) -> None:
    try:
        payload = ModelInquiryService.from_env().trace(
            inquiry_id,
            include_delivery=include_delivery,
        )
    except BuilderOpsValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(payload, as_json)


@inquiry.command("evaluate", help="Persist canonical issue-readiness evidence and receipt.")
@click.argument("inquiry_id")
@click.option("--created-by", default=None)
@click.option("--json", "as_json", is_flag=True)
def inquiry_evaluate(
    inquiry_id: str,
    created_by: str | None,
    as_json: bool,
) -> None:
    try:
        service = ModelInquiryService.from_env()
        gateway = ModelInquiryPromotionGateway(service)
        payload = gateway.evaluate(inquiry_id, actor=_parse_actor(created_by))
        payload["human_readable_report"] = str(
            service.write_human_readable_report(inquiry_id)
        )
    except BuilderOpsValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(payload, as_json)


@inquiry.command("promote", help="Explicitly promote an issue-ready inquiry through GitHub REST.")
@click.argument("inquiry_id")
@click.option("--create-issue", is_flag=True, help="Authorize one REST Issue authority crossing.")
@click.option("--repository", default=None, help="GitHub owner/name; defaults to environment.")
@click.option("--label", "labels", multiple=True)
@click.option("--created-by", default=None)
@click.option("--json", "as_json", is_flag=True)
def inquiry_promote(
    inquiry_id: str,
    create_issue: bool,
    repository: str | None,
    labels: tuple[str, ...],
    created_by: str | None,
    as_json: bool,
) -> None:
    if not create_issue:
        raise click.ClickException("--create-issue is required for explicit authority crossing")
    repository = repository or os.environ.get("BUILDEROPS_GITHUB_REPOSITORY") or os.environ.get(
        "GITHUB_REPOSITORY"
    )
    if not repository:
        raise click.ClickException(
            "--repository or BUILDEROPS_GITHUB_REPOSITORY is required"
        )
    try:
        service = ModelInquiryService.from_env()
        gateway = ModelInquiryPromotionGateway(
            service,
            repository=repository,
            client=GhApiIssueClient(repository),
        )
        payload = gateway.promote(
            inquiry_id,
            labels=labels or DEFAULT_LABELS,
            actor=_parse_actor(created_by),
        )
    except (BuilderOpsValidationError, ModelInquiryPromotionError) as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(payload, as_json)


@inquiry.command("link-delivery", help="Append one PR, verification, or owner-doc trace ref.")
@click.argument("inquiry_id")
@click.option("--delivery-ref", required=True, help="JSON ref or ref_type:ref shorthand.")
@click.option("--created-by", default=None)
@click.option("--json", "as_json", is_flag=True)
def inquiry_link_delivery(
    inquiry_id: str,
    delivery_ref: str,
    created_by: str | None,
    as_json: bool,
) -> None:
    try:
        service = ModelInquiryService.from_env()
        trace = service.trace(inquiry_id)
        payload = service.commit_delivery_reference(
            inquiry_id,
            delivery_ref=_parse_ref(delivery_ref),
            source_refs=list(trace["source_refs"]),
            actor=_parse_actor(created_by),
        )
    except BuilderOpsValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(payload, as_json)


@inquiry.command("resume", help="Plan restart continuation without executing a provider.")
@click.argument("inquiry_id")
@click.option("--json", "as_json", is_flag=True)
def inquiry_resume(inquiry_id: str, as_json: bool) -> None:
    try:
        payload = ModelInquiryService.from_env().resume(inquiry_id)
    except BuilderOpsValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(payload, as_json)


@inquiry.command("run", help="Plan or execute bounded artifact-first model turns.")
@click.argument("inquiry_id")
@click.option("--dry-run", is_flag=True, help="Return a deterministic plan without mutations.")
@click.option("--max-rounds", default=3, show_default=True, type=click.IntRange(1, 20))
@click.option("--json", "as_json", is_flag=True)
def inquiry_run(inquiry_id: str, dry_run: bool, max_rounds: int, as_json: bool) -> None:
    try:
        service = ModelInquiryService.from_env()
        payload = ModelInquiryRunner(service).run(
            inquiry_id,
            max_rounds=max_rounds,
            dry_run=dry_run,
        )
    except (AdapterUnavailableError, BuilderOpsValidationError) as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(payload, as_json)


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
    records: list[Any]
    candidates: list[Mapping[str, Any]] = []
    if records_file is not None:
        payload = _load_json_value_file(records_file, field="records-file")
        if isinstance(payload, list):
            records = payload
            storage = {"available": True, "source": str(records_file), "record_count": len(records)}
        elif isinstance(payload, dict) and isinstance(payload.get("records"), list):
            records = cast(list[Any], payload["records"])
            candidates = _completeness_report_candidates(payload)
            storage = {"available": True, "source": str(records_file), "record_count": len(records)}
        else:
            raise click.BadParameter("records-file must contain a list or an object with records")
    else:
        db_path = ctx.obj.get("db_path") if ctx.obj else None
        if db_path is None:
            db_path = load_paths().db_path
        loaded_records, storage = load_records_from_db(Path(db_path))
        records = list(loaded_records or [])

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
    issues: Any
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
            checks=cast(Iterable[Mapping[str, Any]], checks or []),
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
            pending_checks=pending_check_summary(cast(Iterable[Mapping[str, Any]], checks or [])),
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
            checks=cast(Iterable[Mapping[str, Any]], checks or []),
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
