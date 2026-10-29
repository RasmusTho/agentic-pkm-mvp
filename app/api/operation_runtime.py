"""Host-owned production composition of the autonomous-operation owners.

Only scoped owners with a complete production authority path are installed.
An adapter's existence is not activation of its missing producer dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
import sys
from time import time
from typing import Any, Callable, Mapping

from fastapi import HTTPException, Request

from app.api.read_operation_owners import _locate_identity, build_read_operation_adapter
from app.api.routes import capture
from app.api.routes.active_context_selection import build_selection_service, get_selection_store
from app.auth import resolve_auth_subject
from app.governance.governed_write import GovernedWriteAdapter, InvalidDecisionTokenError
from app.instance.active_context_service import (
    ACTION_SELECTION_INSPECT, PERMISSION_SELECTION_READ, WRITE_CLASS_READ,
)
from app.instance.context_bound_read import context_bound_read_window
from app.instance.context_bound_write import context_bound_write_window
from app.instance.context_selection import ContextSelectionError
from app.instance.vault_registry import VaultRegistryStore
from app.operations.contracts import (
    CapabilityAvailability, CapabilityDiscovery, CapabilitySupport, OperationContext,
    OperationOutcome, OperationProvenance, OperationRequest, OperationStatus,
)
from app.operations.execution_kernel import JsonReceiptStore, OperationExecutionKernel, PolicyDecision, OwnerExecutionResult
from app.operations.archival_operations import ArchivalOperationServerConfig, build_archival_operation_handlers
from app.operations.placement_operations import PlacementOperationServerConfig, build_placement_operation_handlers
from app.knowledge.placement import KnowledgePlacementOwner
from app.operations.read_operations import READ_OWNERS, RequestContextCarrier
from app.operations.write_operations import (
    CAPTURE_OPERATION_ID, UPDATE_OPERATION_ID, WriteOperationServerConfig,
    build_write_operation_handlers, reconcile_write_operation,
)
from app.knowledge.write_ops import read_note_text_with_version
from app.vault.paths import get_vault_capture_note_rel
from app.write_guard import DEFAULT_WRITE_GUARD

EFFECTS = {
    CAPTURE_OPERATION_ID: ("companion.capture.append", "vault_capture_append"),
    UPDATE_OPERATION_ID: ("operation.artifact.update", "vault_body_edit"),
    "artifact.move": ("operation.artifact.move", "vault_placement"),
    "artifact.rename": ("operation.artifact.rename", "vault_placement"),
    "artifact.archive": ("operation.artifact.archive", "source_archival"),
    "artifact.restore": ("operation.artifact.restore", "source_archival"),
}
UNAVAILABLE = {
    "artifact.create": "scoped EXE creation producer unavailable",
    "proposal.apply": "scoped Panel approval producer unavailable",
    "artifact.classify": "semantic approval owner unavailable",
    "artifact.tags.add": "semantic approval owner unavailable",
    "artifact.tags.remove": "semantic approval owner unavailable",
    "collection.reorder": "semantic approval owner unavailable",
    "operation.batch": "batch supervision unavailable",
}


@dataclass
class ProductionOperationRuntime:
    kernel: OperationExecutionKernel
    carrier: RequestContextCarrier
    context: OperationContext
    actor: str
    registry: VaultRegistryStore
    unavailable: Mapping[str, str]
    operation_id: str
    readback_config: WriteOperationServerConfig | None = None
    selection_check: Callable[[], None] | None = None

    def discovery(self) -> CapabilityDiscovery:
        installed = {*self.kernel.handlers, *READ_OWNERS, "operation.discovery"}
        return CapabilityDiscovery(tuple(
            CapabilityAvailability(
                name, CapabilitySupport.SUPPORTED if name in installed else CapabilitySupport.UNAVAILABLE,
                reason=None if name in installed else self.unavailable[name],
                extensions={"authority_class": "governed_effect" if name in EFFECTS or name in self.unavailable else "read_only"},
            ) for name in sorted(installed | set(self.unavailable))
        ))

    def invoke(self, operation: OperationRequest) -> OperationOutcome:
        if (operation.context.active_context_ref, operation.context.vault_generation) != (
            self.context.active_context_ref, self.context.vault_generation
        ):
            return OperationOutcome(operation.request_id, OperationStatus.CONFLICTED,
                                    operation.operation_id, operation.context,
                                    warnings=("active context generation is stale",))
        request = replace(operation, context=self.context,
                          provenance=OperationProvenance(self.actor, "http", "shared_http"))
        if request.operation_id in READ_OWNERS or request.operation_id == "operation.discovery":
            adapter = build_read_operation_adapter(self.registry)
            return replace(adapter, discovery=self.discovery()).invoke(request, self.carrier)
        if request.operation_id not in self.kernel.handlers:
            return OperationOutcome(request.request_id, OperationStatus.NOT_SUPPORTED,
                                    request.operation_id, self.context,
                                    warnings=(self.unavailable.get(request.operation_id, "operation unavailable"),))
        if request.operation_id != self.operation_id:
            raise HTTPException(403, "operation_binding_mismatch")
        selected = self.carrier.service.inspect(
            self.carrier.override_bearer or self.carrier.session_bearer or "", derived=self.carrier.derived
        )
        delegation = {
            "active_context_ref": self.context.active_context_ref,
            "vault_generation": self.context.vault_generation,
            "operation_ids": [request.operation_id], "allowed_effects": [request.operation_id],
            "policy_version": "governed-write.v1", "principal": self.actor,
            "client": "http", "surface": "shared_http",
            "receipt_ref": selected.selection_capability_digest,
            "authority_class": "governed_effect",
            "target_ids": [target["artifact_id"] for target in request.targets],
            "max_targets": 1, "expires_at": selected.expires_at, "revoked": False,
        }
        with self.carrier.service.selection_store.read_effect_window(
            self.carrier.override_bearer or self.carrier.session_bearer or "",
            principal=selected.principal, instance_identity=selected.instance_identity,
            expected_record=selected,
        ) as require_current:
            self.selection_check = require_current
            try:
                outcome = self.kernel.execute(request, delegation, bind_owner_delegation=True)
                if (outcome.status is OperationStatus.RECOVERY_REQUIRED
                    and self.readback_config is not None
                    and self.readback_config.active_context is not None):
                    # Read the exact durable native receipt without retrying a
                    # source effect or replacing the original admission.
                    with context_bound_read_window(self.readback_config.active_context,
                                                   registry_store=self.registry):
                        proof = reconcile_write_operation(replace(request, delegation=delegation), self.readback_config)
                    if proof.effect_receipt is not None:
                        outcome = replace(outcome, convergence=proof.convergence,
                            extensions={**outcome.extensions, "owner_readback": {
                                "effect_receipt_ref": proof.effect_receipt.get("receipt_id"),
                                "status": proof.status.value,
                            }})
                return outcome
            finally:
                self.selection_check = None

    def receipt(self, request_id: str) -> OperationOutcome:
        with context_bound_read_window(self.carrier.resolve(), registry_store=self.registry):
            stored = self.kernel.receipt_store.lookup(request_id)
            if (stored is None or stored.outcome.provenance is None
                or stored.outcome.provenance.actor != self.actor
                or tuple(stored.outcome.context.extensions.get("vault_binding_ids", ()))
                    != tuple(self.context.extensions["vault_binding_ids"])):
                raise HTTPException(404, "operation_receipt_unavailable")
            return stored.outcome


def build_production_operation_runtime(
    request: Request, *, api_key: str | None, session_bearer: str | None,
    override_bearer: str | None, operation: OperationRequest | None = None,
    target_binding_id: str | None = None,
) -> ProductionOperationRuntime:
    """Resolve authenticated selection, owners, GOV and the existing durable journal.

    No client can supply this factory's stores, policy, owner ports or receipts.
    Unsupported dependencies remain absent from the kernel's handler map.
    """
    subject = resolve_auth_subject(request, api_key)
    if not (session_bearer or override_bearer):
        raise HTTPException(401, "reselection_required")
    service = build_selection_service(get_selection_store())
    derived = service.derive(subject, presented_credential=api_key)
    carrier = RequestContextCarrier(service, derived, session_bearer, override_bearer)
    operation_id = operation.operation_id if operation else "operation.discovery"
    action, write_class = EFFECTS.get(operation_id, (ACTION_SELECTION_INSPECT, WRITE_CLASS_READ))
    context = service.resolve_request_context(
        derived=derived, session_bearer=session_bearer, override_bearer=override_bearer,
        action=action, write_class=write_class,
        required_permission="write" if operation_id in EFFECTS else PERMISSION_SELECTION_READ,
    ).snapshot
    context.require_effect_capable()
    operation_context = OperationContext(context.context_id, str(context.generation), {
        "vault_binding_ids": list(context.binding_ids),
        "target_binding_id": target_binding_id,
    })
    registry = VaultRegistryStore(Path(os.environ["INSTANCE_VAULT_REGISTRY_PATH"]))
    journal = JsonReceiptStore(registry.path.parent / "operation-receipts.json")
    actor = context.principal_context.principal_id
    unavailable = dict(UNAVAILABLE)
    with context_bound_read_window(context, registry_store=registry):
        initialized = any(registry.load().registrations[binding].extensions.get("status") == "initialized"
                          for binding in context.binding_ids)
    if not initialized:
        unavailable.update({name: "initialized selected target unavailable" for name in EFFECTS})
    if not (sys.platform == "darwin" or sys.platform.startswith("linux")):
        unavailable.update({name: "local POSIX placement unavailable" for name in ("artifact.move", "artifact.rename")})
    archive_configs: dict[str, ArchivalOperationServerConfig] = {}
    try:
        from app.config.environment import active_environment
        from app.ops.heimdal_cold_volume import load_channel_archive_metadata, require_archive_volume_ready
        from app.heimdal.local_archive import resolve_retention_window_days
        from app.heimdal import raw_read_gate, raw_store
        from app.heimdal.local_archive import OPERATION_RESTORE_SERVICE
        config_root = Path(os.environ["PKM_CONFIG_ROOT"])
        if not config_root.is_absolute():
            raise ValueError("explicit archive host configuration required")
        if OPERATION_RESTORE_SERVICE not in raw_read_gate.resolve_read_allowlist():
            raise ValueError("fixed operation reader unavailable")
        raw_store.resolve_raw_store_key()
        channel = active_environment()
        require_archive_volume_ready(load_channel_archive_metadata(config_root=config_root, channel=channel), expected_channel=channel)
        with context_bound_read_window(context, registry_store=registry) as roots:
            for selected_root in roots:
                if registry.load().registrations[selected_root.vault_binding_id].extensions.get("status") != "initialized":
                    continue
                try:
                    resolve_retention_window_days(selected_root.root)
                except Exception:
                    continue
                archive_configs[selected_root.vault_binding_id] = ArchivalOperationServerConfig(
                    config_root, channel, selected_root.root)
    except Exception:
        archive_configs.clear()
    if not archive_configs or (operation_id in {"artifact.archive", "artifact.restore"}
                               and target_binding_id not in archive_configs):
        unavailable.update({name: "qualified archive volume/retention/fixed reader/key unavailable" for name in ("artifact.archive", "artifact.restore")})
    handlers = {}
    readback_config = None
    valid_token = lambda *_: False
    version_current = lambda _: False
    policy = lambda *_: PolicyDecision.denied("governed-write.v1", "effect owner unavailable")
    if operation is not None and operation_id in EFFECTS and operation_id not in unavailable:
        if target_binding_id not in context.binding_ids:
            raise HTTPException(403, "selected_target_required")
        with context_bound_read_window(context, registry_store=registry) as roots:
            root = next(item.root for item in roots if item.vault_binding_id == target_binding_id)
            registration = registry.load().registrations[target_binding_id]
            if registration.extensions.get("status") != "initialized":
                raise HTTPException(409, "initialized_target_required")
            note_path = None
            artifact_id = None
            if operation_id in {UPDATE_OPERATION_ID, "artifact.move", "artifact.rename"}:
                if len(operation.targets) != 1:
                    raise HTTPException(422, "one_artifact_identity_required")
                artifact_id = str(operation.targets[0]["artifact_id"])
                located = _locate_identity(artifact_id, roots)
                if isinstance(located, str):
                    raise HTTPException(409, located)
                if located.root.vault_binding_id != target_binding_id:
                    raise HTTPException(403, "target_binding_mismatch")
                note_path = located.root.root / str(located.note["note_path"])
                resource = note_path.relative_to(root).as_posix()
            elif operation_id == CAPTURE_OPERATION_ID:
                resource = get_vault_capture_note_rel(root)
            else:
                resource = ".system/operations/archive"
        gov = GovernedWriteAdapter()
        binding = dict(action=action, write_class=write_class, actor=actor, resource=resource)
        grant = gov.bind_context(gov.issue_decision_token(write_guard=DEFAULT_WRITE_GUARD, **binding),
                                 context=context, target_binding_id=target_binding_id)

        def validate_token(*_: Any) -> bool:
            # Policy/health ports can wait or reenter. End with only the
            # captured record, immutable token/context and deadline checks.
            DEFAULT_WRITE_GUARD.assert_writes_allowed(action)
            if operation_id in {"artifact.archive", "artifact.restore"}:
                from app.heimdal.raw_read_gate import resolve_read_allowlist
                from app.heimdal.local_archive import OPERATION_RESTORE_SERVICE
                if OPERATION_RESTORE_SERVICE not in resolve_read_allowlist():
                    raise InvalidDecisionTokenError("fixed archive reader no longer admitted")
            if runtime.selection_check is None:
                return False
            runtime.selection_check()
            gov.validate_decision_token(decision_token=grant.decision_token, **binding)
            gov.validate_context(grant.decision_token, context=context, target_binding_id=target_binding_id)
            if context.expires_at is None or context.expires_at <= time():
                raise InvalidDecisionTokenError("operation authority expired at native effect")
            return True

        def require_effect() -> None:
            try:
                valid = validate_token()
            except ContextSelectionError as exc:
                raise InvalidDecisionTokenError("operation selection changed at native effect") from exc
            if not valid:
                raise InvalidDecisionTokenError("operation native effect authority unavailable")

        def capture_owner(arguments: Mapping[str, Any], incoming: Request) -> Any:
            return capture._capture_to_inbox(
                capture.CaptureRequest.model_validate({**arguments, "target_binding_id": target_binding_id}),
                incoming, context, effect_check=require_effect,
            )

        request.state.compatibility_write_root = root
        request.state.trace_id = operation.request_id
        config = WriteOperationServerConfig(
            root, operation_context, actor, note_path, artifact_id, request,
            capture_owner=capture_owner, active_context=context,
            target_binding_id=target_binding_id,
        )
        canonical = build_write_operation_handlers(config)
        if operation_id == UPDATE_OPERATION_ID:
            readback_config = config
        placement_owner = None
        if operation_id in {"artifact.move", "artifact.rename"}:
            placement_owner = KnowledgePlacementOwner(
                vault_root=root, context_ref=context.context_id, vault_generation=str(context.generation),
                actor=actor, active_context=context, target_binding_id=target_binding_id,
                registry_store=registry, context_is_current=lambda: validate_token(),
                authority_is_current=lambda _: validate_token(), filesystem="local-posix-v1",
            )
            canonical = build_placement_operation_handlers(PlacementOperationServerConfig(
                placement_owner, operation_context, artifact_id or "", resource,
            ))
        elif operation_id in {"artifact.archive", "artifact.restore"}:
            canonical = build_archival_operation_handlers(replace(
                archive_configs[target_binding_id], effect_check=require_effect))

        def invoke_owner(item: OperationRequest) -> Any:
            # Revalidate after kernel/process-lock waits and hold the complete
            # MVR-05C window through native source and authority receipts.
            with context_bound_write_window(context, target_binding_id=target_binding_id,
                token=grant.decision_token, registry_store=registry,
                effect_check=require_effect, **binding):
                return canonical[operation_id](item)

        handlers = {name: invoke_owner for name in EFFECTS if name not in unavailable}
        valid_token = validate_token
        def check_version(item: OperationRequest) -> bool:
            if item.operation_id != operation_id:
                return False
            if operation_id == CAPTURE_OPERATION_ID:
                return item.expected_version is None
            if placement_owner is not None:
                return placement_owner.source_generation(resource, artifact_id or "") == item.expected_version
            if operation_id in {"artifact.archive", "artifact.restore"}:
                return type(item.expected_version) is int and item.expected_version >= 0
            return note_path is not None and read_note_text_with_version(note_path)[1] == item.expected_version

        version_current = check_version
        policy = lambda *_: PolicyDecision.allowed("governed-write.v1", grant.decision_token.token_id)
    elif operation is None or operation_id in READ_OWNERS or operation_id == "operation.discovery":
        def scoped_owner(item: OperationRequest) -> OwnerExecutionResult:
            # Lazy request binding is host composition, never a client-selected
            # owner port. A read kernel still refuses before this function; a
            # trusted direct invocation obtains fresh write admission as well.
            runtime = build_production_operation_runtime(
                request, api_key=api_key, session_bearer=session_bearer,
                override_bearer=override_bearer, operation=item,
                target_binding_id=target_binding_id,
            )
            result = runtime.invoke(item)
            return OwnerExecutionResult(result.status, warnings=result.warnings)

        handlers = {name: scoped_owner for name in EFFECTS if name not in unavailable}
    kernel = OperationExecutionKernel(
        context_resolver=lambda item: item == operation_context,
        policy_evaluator=policy, handlers=handlers, receipt_store=journal,
        version_checker=version_current, token_validator=valid_token,
    )
    runtime = ProductionOperationRuntime(kernel, carrier, operation_context, actor, registry,
                                        unavailable, operation_id, readback_config)
    return runtime
