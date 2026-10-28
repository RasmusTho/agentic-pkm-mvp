"""Dormant AUTOOPS-04 composition over the enumerated write owners.

No route, MCP tool, singleton, context bearer, policy authority, or receipt store
is installed here. A server composes these handlers with the execution kernel;
authenticated installation remains #5352 / MVR-05C work.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import os
from pathlib import Path
from typing import Any, Callable, Mapping, cast

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.events.schema import make_outbox_event
from app.governance.governed_write import (
    GovernedWriteAdapter,
    GovernedWriteGrant,
    InvalidDecisionTokenError,
)
from app.knowledge.contracts import WriteReceipt
from app.knowledge.errors import KnowledgeWriteConflict
from app.knowledge.write_ops import read_note_text_with_version, write_note_from_absolute
from app.orchestrator.executor import (
    MockPlanExecutor,
    StepContext,
    StepExecutionError,
    execute_plan_step,
)
from app.outbox.events import INDEX_OUTBOX_PATH
from app.panel.confirmation import (
    ConfirmRequest,
    PanelConfirmationService,
    SameTurnExecutionError,
    UnknownProposalError,
)
from app.planner.provider import build_vault_append_steps
from app.planner.schema import PlanMetadata
from app.services.outbox import append_jsonl_outbox_event
from app.services.artifact_identity import resolve_note_artifact_identity
from app.text.helpers import body_contains_frontmatter, split_frontmatter
from app.write_guard import DEFAULT_WRITE_GUARD, WritesBlockedError

from .contracts import (
    ConvergenceState,
    OperationContext,
    OperationConvergence,
    OperationRequest,
    OperationStatus,
    SourceEffectStatus,
)
from .execution_kernel import OwnerExecutionResult

CAPTURE_OPERATION_ID = "artifact.capture"
CREATE_OPERATION_ID = "artifact.create"
UPDATE_OPERATION_ID = "artifact.update"
PROPOSAL_APPLY_OPERATION_ID = "proposal.apply"
WRITE_OWNERS = {
    CAPTURE_OPERATION_ID: "companion.capture",
    CREATE_OPERATION_ID: "orchestrator.mcp.vault.append_note",
    UPDATE_OPERATION_ID: "knowledge.governed_body_edit",
    PROPOSAL_APPLY_OPERATION_ID: "panel.confirmation",
}


@dataclass(frozen=True)
class WriteOperationServerConfig:
    """Trusted, request-independent bindings for one direct composition.

    The note locator/identity pair comes from the state owner, never operation
    arguments. It pins a single existing note, rather than adding a registry or
    accepting arbitrary filesystem paths. Capture consumes an existing server
    Request and the server's existing capture-owner binding, retaining its
    compatibility seal, including pre-05C refusal. The interaction layer binds
    that owner; this execution module never imports or installs a route.
    """

    vault_root: Path
    context: OperationContext
    actor: str
    note_path: Path | None = None
    artifact_id: str | None = None
    capture_request: Request | None = None
    confirmation_service: PanelConfirmationService | None = None
    capture_owner: Callable[[Mapping[str, Any], Request], Any] | None = None


def build_write_operation_handlers(
    config: WriteOperationServerConfig,
) -> dict[str, Callable[[OperationRequest], OwnerExecutionResult]]:
    return {operation: lambda request: _execute(request, config) for operation in WRITE_OWNERS}


def _refuse(status: OperationStatus, reason: str) -> OwnerExecutionResult:
    return OwnerExecutionResult(status, warnings=(reason,))


def _execute(request: OperationRequest, config: WriteOperationServerConfig) -> OwnerExecutionResult:
    if request.operation_version != "ygg.operation.v1" or request.mode != "execute":
        return _refuse(OperationStatus.NOT_SUPPORTED, "only ygg.operation.v1 execute is supported")
    if (
        not config.actor
        or not config.context.active_context_ref
        or config.context.vault_generation is None
    ):
        return _refuse(OperationStatus.REJECTED, "server context and actor are required")
    if request.context != config.context:
        return _refuse(OperationStatus.CONFLICTED, "server-bound context generation differs")
    if request.provenance is not None and request.provenance.actor != config.actor:
        return _refuse(OperationStatus.REJECTED, "caller provenance differs from the server actor")
    if request.operation_id not in WRITE_OWNERS:
        return _refuse(OperationStatus.NOT_SUPPORTED, "write owner is not registered")
    try:
        if request.operation_id == CAPTURE_OPERATION_ID:
            return _capture(request, config)
        if request.operation_id == CREATE_OPERATION_ID:
            return _create(request, config)
        if request.operation_id == UPDATE_OPERATION_ID and "proposal_id" not in request.arguments:
            return _update_body(request, config)
        return _apply_proposal(request, config)
    except (WritesBlockedError, InvalidDecisionTokenError, SameTurnExecutionError):
        return _refuse(OperationStatus.REJECTED, "governed owner denied the mutation")
    except UnknownProposalError:
        return _refuse(OperationStatus.NOT_FOUND, "owner proposal is unavailable")
    except ValidationError:
        return _refuse(OperationStatus.INVALID, "owner schema rejected the arguments")
    except HTTPException as exc:
        if exc.status_code in {400, 422}:
            return _refuse(OperationStatus.INVALID, "owner validation refused the mutation")
        if exc.status_code in {401, 403, 409}:
            return _refuse(
                OperationStatus.REJECTED, "owner policy or compatibility seal refused the mutation"
            )
        # A capture 500 can follow a committed append and missing receipt.
        return OwnerExecutionResult.ambiguous()
    except KnowledgeWriteConflict as exc:
        if exc.receipt is not None and exc.receipt.outcome == "conflict_staged":
            return _refuse(
                OperationStatus.CONFLICTED, "source version conflicted; proposal staged by HKA"
            )
        return OwnerExecutionResult.ambiguous()
    except StepExecutionError as exc:
        if exc.error_type in {"invalid_tool_args", "invalid_tool"}:
            return _refuse(OperationStatus.INVALID, "EXE argument validation failed")
        if exc.error_type in {"policy_denied", "write_guard_denied"}:
            return _refuse(OperationStatus.REJECTED, "EXE policy denied the mutation")
        return OwnerExecutionResult.ambiguous()
    except Exception:
        # No fallback and no retry after entering a potentially effectful owner.
        return OwnerExecutionResult.ambiguous()


def _capture(request: OperationRequest, config: WriteOperationServerConfig) -> OwnerExecutionResult:
    if config.capture_request is None or config.capture_owner is None:
        return _refuse(OperationStatus.REJECTED, "server capture owner and request are required")
    if request.targets or request.expected_version is not None:
        return _refuse(OperationStatus.INVALID, "capture does not rewrite an existing target")
    # Require the trusted Request's existing target fence. Do not create or
    # downgrade a carrier from operation input to get around the pre-05C seal.
    sealed_root = getattr(config.capture_request.state, "compatibility_write_root", None)
    if sealed_root is None or Path(sealed_root).resolve() != config.vault_root.resolve():
        return _refuse(OperationStatus.REJECTED, "capture target is not server-sealed")
    # The trusted composition supplies existing capture validation and execution
    # together; no operation argument can choose or replace this owner.
    response = config.capture_owner(dict(request.arguments), config.capture_request)
    if isinstance(response, JSONResponse):
        return _refuse(OperationStatus.REJECTED, "capture context is unavailable")
    governed = response.governed_write or {}
    authority = governed.get("authority_receipt")
    if not isinstance(authority, dict) or not authority.get("receipt_id"):
        return OwnerExecutionResult.ambiguous()
    return _completed(request, source_receipt=response.model_dump(mode="json"), governed=governed)


def _create(request: OperationRequest, config: WriteOperationServerConfig) -> OwnerExecutionResult:
    # The existing MCP note schema is the only typed creation schema here.
    # Metadata is deliberately not accepted: artifact/trust schemas remain
    # with their semantic owners rather than this mechanical operation layer.
    args = dict(request.arguments)
    if (
        set(args) - {"kind", "title", "body"}
        or args.pop("kind", None) != "note"
        or request.targets
        or request.expected_version is not None
    ):
        return _refuse(OperationStatus.INVALID, "typed creation requires kind=note, title and body")
    if (
        not isinstance(args.get("title"), str)
        or not args["title"].strip()
        or not isinstance(args.get("body"), str)
    ):
        return _refuse(OperationStatus.INVALID, "note title and body must be strings")
    steps = build_vault_append_steps(
        step_id="create",
        description="Create a typed note",
        tool_args=args,
        reason="Explicit governed operation",
        agent_id=config.actor,
    )
    context = StepContext(
        plan_id=request.request_id,
        object_id=None,
        trace_id=request.request_id,
        metadata=PlanMetadata(
            goal="Create typed note", source_object_uuid=request.request_id, created_by=config.actor
        ),
        tool_settings={"mcp_vault_enable": True, "vault_root": config.vault_root},
        agent_id=config.actor,
    )
    executor = MockPlanExecutor()
    for step in steps:
        context.results[step.id] = execute_plan_step(executor, step, context)
    result = context.results["create"]["result"]
    authority = result.get("authority_receipt")
    if not isinstance(authority, Mapping) or not result.get("receipt_ref"):
        return OwnerExecutionResult.ambiguous()
    return _completed(
        request,
        source_receipt={
            "receipt_ref": result["receipt_ref"],
            "effect_id": result["effect_id"],
            "note_path": result["note_path"],
        },
        governed={"authority_receipt": authority, "decision_token": result.get("decision_token")},
    )


def _target(
    request: OperationRequest, config: WriteOperationServerConfig
) -> Path | OwnerExecutionResult:
    if (
        len(request.targets) != 1
        or not config.artifact_id
        or request.targets[0] != {"artifact_id": config.artifact_id}
        or config.note_path is None
    ):
        return _refuse(
            OperationStatus.INVALID, "exactly one server-bound stable target is required"
        )
    if not isinstance(request.expected_version, str) or not request.expected_version.strip():
        return _refuse(OperationStatus.CONFLICTED, "expected source version is required")
    path = config.note_path
    lexical = Path(os.path.abspath(path))
    try:
        lexical.relative_to(config.vault_root.resolve())
    except ValueError:
        return _refuse(OperationStatus.REJECTED, "note target is outside the server vault")
    if lexical.resolve() != lexical:
        return _refuse(OperationStatus.REJECTED, "aliased note targets are refused")
    if not lexical.is_file():
        return _refuse(OperationStatus.NOT_FOUND, "source note is unavailable")
    return lexical


def _source_snapshot(
    request: OperationRequest, config: WriteOperationServerConfig, path: Path
) -> str | OwnerExecutionResult:
    current, version = read_note_text_with_version(path)
    if version != request.expected_version:
        return _refuse(OperationStatus.CONFLICTED, "expected source version is stale")
    identity = resolve_note_artifact_identity(
        artifact_path=path,
        vault_root=config.vault_root,
        safe_note_path=path.relative_to(config.vault_root.resolve()).as_posix(),
        body=current,
        heal_missing_uuid=False,
    )
    if (
        not identity.owns_identity
        or identity.artifact_id != config.artifact_id
        or identity.artifact_kind != "human_note"
    ):
        return _refuse(
            OperationStatus.CONFLICTED, "source identity differs from the bound artifact"
        )
    return current


def _update_body(
    request: OperationRequest, config: WriteOperationServerConfig
) -> OwnerExecutionResult:
    path = _target(request, config)
    if isinstance(path, OwnerExecutionResult):
        return path
    body = request.arguments.get("body")
    if (
        set(request.arguments) != {"body"}
        or not isinstance(body, str)
        or body_contains_frontmatter(body)
    ):
        return _refuse(
            OperationStatus.INVALID,
            "body edit preserves frontmatter; metadata requires its owner proposal",
        )
    current = _source_snapshot(request, config, path)
    if isinstance(current, OwnerExecutionResult):
        return current
    frontmatter, old_body = split_frontmatter(current)
    if frontmatter is None:
        return _refuse(OperationStatus.INVALID, "source frontmatter boundary cannot be preserved")
    prefix = current[: len(current) - len(old_body)]
    if prefix and body and not prefix.endswith("\n"):
        # A metadata-only note may close at EOF. Keep its delimiter separate
        # from the replacement body without changing any frontmatter bytes.
        prefix += "\r\n" if "\r\n" in prefix and not prefix.endswith("\r") else "\n"
    content = prefix + body
    gov = GovernedWriteAdapter()
    resource = path.relative_to(config.vault_root.resolve()).as_posix()
    binding = {
        "action": "operation.artifact.update",
        "write_class": "vault_body_edit",
        "actor": config.actor,
        "resource": resource,
    }
    grant = gov.issue_decision_token(write_guard=DEFAULT_WRITE_GUARD, **binding)
    gov.validate_decision_token(decision_token=grant.decision_token, **binding)
    try:
        source = write_note_from_absolute(
            path,
            content,
            vault_root=config.vault_root,
            action=binding["action"],
            expected_version=str(request.expected_version),
            writer_identity=config.actor,
        )
    except KnowledgeWriteConflict as exc:
        if exc.receipt is None or exc.receipt.outcome != "conflict_staged":
            raise
        return _account_source(
            request,
            exc.receipt,
            gov,
            grant,
            outcome_status=OperationStatus.CONFLICTED,
            source_effect=SourceEffectStatus.NOT_APPLIED,
            effect_state="source_conflict_staged",
            warning="HKA staged the conflict; canonical source was not changed",
        )
    return _account_source(
        request,
        source,
        gov,
        grant,
        resulting_version=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def _apply_proposal(
    request: OperationRequest, config: WriteOperationServerConfig
) -> OwnerExecutionResult:
    path = _target(request, config)
    if isinstance(path, OwnerExecutionResult):
        return path
    if config.confirmation_service is None:
        return _refuse(OperationStatus.NOT_SUPPORTED, "Panel confirmation owner is unavailable")
    if set(request.arguments) != {"proposal_id"} or not isinstance(
        request.arguments["proposal_id"], str
    ):
        return _refuse(
            OperationStatus.INVALID, "metadata/proposal edits require an existing Panel proposal"
        )
    proposal = config.confirmation_service._proposals.get(request.arguments["proposal_id"])
    if proposal is None:
        return _refuse(OperationStatus.NOT_FOUND, "Panel proposal is unavailable")
    proposed_path = Path(proposal.intent_event.payload.note.path or "")
    if not proposed_path.is_absolute():
        proposed_path = config.vault_root / proposed_path
    if proposed_path != path or proposal.artifact_id != config.artifact_id:
        return _refuse(
            OperationStatus.REJECTED, "Panel proposal target differs from the bound note"
        )
    if any(
        action.id == "profile.apply_proposal" for action in proposal.intent_event.payload.actions
    ):
        return _refuse(
            OperationStatus.NOT_SUPPORTED, "profile writer is outside this operation binding"
        )
    snapshot = _source_snapshot(request, config, path)
    if isinstance(snapshot, OwnerExecutionResult):
        return snapshot
    gov = GovernedWriteAdapter()
    binding = {
        "action": "panel.confirm",
        "write_class": "vault_panel_apply",
        "actor": config.actor,
        "resource": path.relative_to(config.vault_root.resolve()).as_posix(),
    }
    grant = gov.issue_decision_token(write_guard=DEFAULT_WRITE_GUARD, **binding)
    gov.validate_decision_token(decision_token=grant.decision_token, **binding)
    accounted: OwnerExecutionResult | None = None

    def account_before_acknowledgement(source: WriteReceipt) -> None:
        nonlocal accounted
        accounted = _account_source(
            request,
            source,
            gov,
            grant,
            outcome_status=OperationStatus.NOT_ACKNOWLEDGED,
            effect_state="panel_source_applied_downstream_unverified",
            source_scope="panel_diagnostic",
            warning="Panel source receipt is known; the requested semantic effect still lacks its owner's receipt. Reconcile the queued intent; never retry it blindly.",
        )
        if accounted.status is OperationStatus.RECOVERY_REQUIRED:
            raise RuntimeError(
                "source accountability is not durable; withhold downstream acknowledgement"
            )

    response = config.confirmation_service.confirm(
        ConfirmRequest(
            proposal_id=request.arguments["proposal_id"],
            artifact_id=config.artifact_id or "",
            action="confirm",
            idempotency_key=request.request_id,
            expected_version=str(request.expected_version),
        ),
        vault_root=config.vault_root,
        source_receipt_sink=account_before_acknowledgement,
    )
    if accounted is not None:
        if response.status == "recovery_required":
            return replace(
                accounted,
                status=OperationStatus.RECOVERY_REQUIRED,
                warnings=accounted.warnings
                + ("Panel confirmation or downstream acknowledgement requires reconciliation",),
            )
        if response.status == "logged" and response.downstream_state == "not_required":
            receipt = dict(accounted.effect_receipt or {})
            receipt["write"] = {**receipt.get("write", {}), "effect_state": "panel_diagnostic_only"}
            return replace(accounted, status=OperationStatus.REJECTED, effect_receipt=receipt)
        # A diagnostic/source receipt and a queued semantic intent are not the
        # requested semantic owner's receipt. The overall operation stays pending.
        return accounted
    if response.source_receipt is not None and response.source_receipt.outcome == "conflict_staged":
        return _account_source(
            request,
            response.source_receipt,
            gov,
            grant,
            outcome_status=OperationStatus.CONFLICTED,
            source_effect=SourceEffectStatus.NOT_APPLIED,
            effect_state="source_conflict_staged",
            warning="HKA staged the conflict; canonical source was not changed",
        )
    status = {
        "conflicted": OperationStatus.CONFLICTED,
        "blocked": OperationStatus.REJECTED,
        "rejected": OperationStatus.REJECTED,
        "not_found": OperationStatus.NOT_FOUND,
    }.get(response.status, OperationStatus.RECOVERY_REQUIRED)
    return _refuse(status, "Panel has no operation-bound acknowledged source application")


def _account_source(
    request: OperationRequest,
    source: WriteReceipt,
    gov: GovernedWriteAdapter,
    grant: GovernedWriteGrant,
    **kwargs: Any,
) -> OwnerExecutionResult:
    try:
        authority = gov.record_authority_receipt(
            decision_token=grant.decision_token,
            mutation_receipt=cast(Any, source),
            state_owner="knowledge",
            trace_id=request.request_id,
            effect_id=request.request_id,
            outcome="failed" if source.outcome == "conflict_staged" else "applied",
        )
    except Exception:
        return _unreceipted_source(
            request,
            asdict(source),
            source_effect=kwargs.get("source_effect", SourceEffectStatus.COMMITTED),
        )
    governed = {
        "policy_decision": asdict(grant.policy_decision),
        "decision_token": asdict(grant.decision_token),
        "authority_receipt": asdict(authority),
    }
    return _record_and_complete(request, asdict(source), governed, **kwargs)


def _unreceipted_source(
    request: OperationRequest,
    source: Mapping[str, Any],
    *,
    source_effect: SourceEffectStatus = SourceEffectStatus.COMMITTED,
) -> OwnerExecutionResult:
    return OwnerExecutionResult(
        OperationStatus.RECOVERY_REQUIRED,
        effect_id=request.request_id,
        effect_receipt={
            "write": {
                "owner": WRITE_OWNERS[request.operation_id],
                "source_receipt": dict(source),
                "effect_state": "applied_receipt_pending",
            }
        },
        convergence=OperationConvergence(
            source_effect,
            store=ConvergenceState.REBUILD_REQUIRED,
            index=ConvergenceState.REBUILD_REQUIRED,
            link=ConvergenceState.REBUILD_REQUIRED,
        ),
        warnings=(
            "owner source result is known without an AuthorityReceipt; reconcile before retry",
        ),
    )


def _record_and_complete(
    request: OperationRequest, source: Mapping[str, Any], governed: Mapping[str, Any], **kwargs: Any
) -> OwnerExecutionResult:
    result = _completed(request, source_receipt=source, governed=governed, **kwargs)
    # Existing outbox accountability, not a second journal or AuthorityReceipt.
    try:
        event = make_outbox_event(
            event="governance.authority_receipt.recorded",
            source="operations.write",
            trace_id=request.request_id,
            payload=dict(result.effect_receipt or {}),
        )
        if not append_jsonl_outbox_event(
            Path(os.getenv("INDEX_OUTBOX_PATH") or INDEX_OUTBOX_PATH),
            event,
            default_source="operations.write",
        ):
            raise RuntimeError("AuthorityReceipt was not persisted")
    except Exception:
        return OwnerExecutionResult(
            OperationStatus.RECOVERY_REQUIRED,
            effect_id=result.effect_id,
            effect_receipt=result.effect_receipt,
            convergence=result.convergence,
            warnings=(
                "owner source result is known; AuthorityReceipt persistence requires reconciliation; never retry the source",
            ),
        )
    return result


def _completed(
    request: OperationRequest,
    *,
    source_receipt: Mapping[str, Any],
    governed: Mapping[str, Any],
    resulting_version: str | None = None,
    effect_state: str = "source_applied",
    outcome_status: OperationStatus = OperationStatus.CONVERGENCE_PENDING,
    source_effect: SourceEffectStatus = SourceEffectStatus.COMMITTED,
    source_scope: str = "requested_source",
    warning: str = "source receipt is known; Store/index/link require owner reconciliation from source",
) -> OwnerExecutionResult:
    authority = governed.get("authority_receipt", {})
    receipt_id = authority.get("receipt_id") if isinstance(authority, Mapping) else None
    if not receipt_id:
        return OwnerExecutionResult.ambiguous()
    projection = (
        ConvergenceState.REBUILD_REQUIRED
        if source_effect is SourceEffectStatus.COMMITTED
        else ConvergenceState.NOT_REQUIRED
    )
    return OwnerExecutionResult(
        outcome_status,
        items=tuple(
            {
                "artifact_id": target["artifact_id"],
                "status": outcome_status.value,
                "version": request.expected_version,
                "result_version": resulting_version,
            }
            for target in request.targets
        ),
        effect_id=request.request_id,
        effect_receipt={
            "receipt_id": receipt_id,
            "write": {
                "owner": WRITE_OWNERS[request.operation_id],
                "source_receipt": dict(source_receipt),
                **dict(governed),
                "input_version": request.expected_version,
                "resulting_version": resulting_version,
                "projection_repair": ["store", "index", "link"]
                if source_effect is SourceEffectStatus.COMMITTED
                else [],
                "effect_state": effect_state,
            },
        },
        convergence=OperationConvergence(
            source_effect,
            store=projection,
            index=projection,
            link=projection,
            extensions={
                "source_scope": source_scope,
                "requested_effect": "unverified" if source_scope == "panel_diagnostic" else "known",
            },
        ),
        warnings=(warning,),
    )
