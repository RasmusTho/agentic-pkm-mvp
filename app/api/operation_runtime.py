"""Host-owned production composition of the autonomous-operation owners.

Only scoped owners with a complete production authority path are installed.
An adapter's existence is not activation of its missing producer dependencies.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
import json
import os
from pathlib import Path, PurePosixPath
import sys
from time import time
from typing import Any, Callable, Iterator, Mapping

from fastapi import HTTPException, Request

from app.api.read_operation_owners import _locate_identity, build_read_operation_adapter
from app.api.operation_schemas import operation_transport_schemas
from app.api.routes import capture
from app.api.routes.active_context_selection import build_selection_service, get_selection_store
from app.auth import resolve_auth_subject
from app.governance.governed_write import DecisionToken, GovernedWriteAdapter, InvalidDecisionTokenError
from app.instance.active_context_service import (
    ACTION_SELECTION_INSPECT, PERMISSION_SELECTION_READ, WRITE_CLASS_READ,
)
from app.instance.context_bound_read import context_bound_read_window
from app.instance.context_bound_write import context_bound_write_window
from app.instance.context_selection import ContextSelectionError, ContextSelectionRecord
from app.instance.vault_registry import VaultRegistryStore
from app.operations.contracts import (
    CapabilityAvailability, CapabilityDiscovery, CapabilitySupport, OperationContext,
    OperationOutcome, OperationProvenance, OperationRequest, OperationStatus,
)
from app.operations.execution_kernel import JsonReceiptStore, OperationExecutionKernel, PolicyDecision, OwnerExecutionResult, OwnerHandler
from app.operations.archival_operations import ArchivalOperationServerConfig, build_archival_operation_handlers
from app.operations.placement_operations import (
    PlacementOperationServerConfig, build_placement_operation_handlers, reconcile_placement_operation,
)
from app.operations.batch_operations import SUPPORTED_BATCH_OPERATIONS
from app.knowledge.placement import KnowledgePlacementOwner
from app.knowledge.errors import KnowledgeCapabilityError, KnowledgeWriteConflict
from app.operations.read_operations import READ_OWNERS, RequestContextCarrier
from app.operations.write_operations import (
    CAPTURE_OPERATION_ID, UPDATE_OPERATION_ID, WriteOperationServerConfig,
    build_write_operation_handlers, reconcile_write_operation,
)
from app.knowledge.write_ops import read_note_text_with_version
from app.vault.paths import get_vault_capture_note_rel
from app.vault.active_context_v1 import ActiveContextSetV1
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
}


def _plain(value: Any) -> Any:
    """Detach journal-safe host data; no bearer is present in these records."""
    return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))


@dataclass
class ProductionOperationRuntime:
    kernel: OperationExecutionKernel
    carrier: RequestContextCarrier
    context: OperationContext
    actor: str
    registry: VaultRegistryStore
    unavailable: Mapping[str, str]
    operation_id: str
    selection_record: ContextSelectionRecord
    readback_config: WriteOperationServerConfig | None = None
    preconditions_reader: Callable[[], Mapping[str, Any]] | None = None
    selection_check: Callable[[], None] | None = None
    host_admission: Mapping[str, Any] | None = None
    reconcile_owner: OwnerHandler | None = None
    active_context: ActiveContextSetV1 | None = None

    @contextmanager
    def selection_window(self) -> Iterator[Callable[[], None]]:
        selected = self.selection_record
        with self.carrier.service.selection_store.read_effect_window(
            self.carrier.override_bearer or self.carrier.session_bearer or "",
            principal=selected.principal, instance_identity=selected.instance_identity,
            expected_record=selected,
        ) as require_current:
            self.selection_check = require_current
            try:
                require_current()
                yield require_current
            finally:
                self.selection_check = None

    def discovery(self) -> CapabilityDiscovery:
        installed = {*self.kernel.handlers, *READ_OWNERS, "operation.discovery"}
        batch_kinds = sorted(SUPPORTED_BATCH_OPERATIONS.intersection(self.kernel.handlers))
        unavailable = dict(self.unavailable)
        if batch_kinds:
            installed.add("operation.batch")
        else:
            unavailable["operation.batch"] = "qualified finite batch owner unavailable"
        schemas = operation_transport_schemas()
        return CapabilityDiscovery(tuple(
            CapabilityAvailability(
                name, CapabilitySupport.SUPPORTED if name in installed else CapabilitySupport.UNAVAILABLE,
                reason=None if name in installed else unavailable[name],
                extensions={"authority_class": "governed_effect" if name in EFFECTS or name in unavailable or name == "operation.batch" else "read_only",
                            "side_effect_class": "source_write" if name in EFFECTS or name in unavailable or name == "operation.batch" else "none",
                            "preview_support": name in installed and (name in EFFECTS or name == "operation.batch"),
                            "maturity": "active" if name in installed else "planned",
                            "output_schema": schemas["outcome"] if name != "operation.batch" else {"type": "object"},
                            "input_schema": (schemas["discovery"] if name == "operation.discovery" else
                                schemas["batch_preview"] if name == "operation.batch" else
                                {**schemas["command"], "properties": {**schemas["command"]["properties"],
                                    "operation_id": {"type": "string", "const": name}}}),
                            **({"supported_kinds": batch_kinds, "max_targets": 100,
                                "partial_success_policy": "independent"} if name == "operation.batch" else {})},
            ) for name in sorted(installed | set(unavailable))
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
            outcome = replace(adapter, discovery=self.discovery()).invoke(request, self.carrier)
            if request.operation_id == "operation.discovery":
                return replace(outcome, extensions={**outcome.extensions,
                    "transport_schemas": operation_transport_schemas()})
            return outcome
        if request.operation_id not in self.kernel.handlers:
            return OperationOutcome(request.request_id, OperationStatus.NOT_SUPPORTED,
                                    request.operation_id, self.context,
                                    warnings=(self.unavailable.get(request.operation_id, "operation unavailable"),))
        if request.operation_id != self.operation_id:
            raise HTTPException(403, "operation_binding_mismatch")
        selected = self.selection_record
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

    def preconditions(self, operation: OperationRequest) -> dict[str, Any]:
        """Observe native versions without executing or reserving an operation."""
        if (operation.context.active_context_ref, operation.context.vault_generation) != (
            self.context.active_context_ref, self.context.vault_generation
        ):
            raise HTTPException(409, "active_context_generation_stale")
        if operation.operation_id != self.operation_id:
            raise HTTPException(403, "operation_binding_mismatch")
        if self.preconditions_reader is None:
            return {"status": "unavailable", "operation_id": operation.operation_id,
                    "reason": self.unavailable.get(operation.operation_id, "operation preconditions unavailable")}
        selected = self.selection_record
        with self.carrier.service.selection_store.read_effect_window(
            self.carrier.override_bearer or self.carrier.session_bearer or "",
            principal=selected.principal, instance_identity=selected.instance_identity,
            expected_record=selected,
        ) as require_current:
            self.selection_check = require_current
            try:
                return {"status": "observed", "operation_id": operation.operation_id,
                        "context": self.context.to_dict(), **self.preconditions_reader()}
            finally:
                self.selection_check = None


def build_production_operation_runtime(
    request: Request, *, api_key: str | None, session_bearer: str | None,
    override_bearer: str | None, operation: OperationRequest | None = None,
    target_binding_id: str | None = None,
    original_admission: Mapping[str, Any] | None = None,
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
    # Capture before resolving: a replacement anywhere during composition or
    # before invocation must not fence a newer record around the old context.
    # Inspect releases the store lock before the resolver's existing lock order.
    selection_record = service.inspect(
        override_bearer if override_bearer is not None else session_bearer or "", derived=derived)
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
    preconditions_reader = None
    host_admission = None
    reconcile_owner = None
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
                if original_admission is None:
                    located = _locate_identity(artifact_id, roots)
                    if isinstance(located, str):
                        raise HTTPException(409, located)
                    if located.root.vault_binding_id != target_binding_id:
                        raise HTTPException(403, "target_binding_mismatch")
                    note_path = located.root.root / str(located.note["note_path"])
                    resource = note_path.relative_to(root).as_posix()
                else:
                    # Only the host-journaled original locator may reconstruct
                    # an owner for recovery after a move. Never locate the new
                    # path and silently rebind the old intent/token.
                    resource = str(original_admission["resource"])
                    relative = PurePosixPath(resource)
                    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                        raise HTTPException(409, "batch_admission_unavailable")
                    note_path = root / resource
            elif operation_id == CAPTURE_OPERATION_ID:
                resource = get_vault_capture_note_rel(root)
            else:
                resource = ".system/operations/archive"
        gov = GovernedWriteAdapter()
        binding = dict(action=action, write_class=write_class, actor=actor, resource=resource)
        admitted_intent = replace(operation, context=operation_context,
            provenance=OperationProvenance(actor, "http", "shared_http"))
        if original_admission is None:
            grant = gov.bind_context(gov.issue_decision_token(write_guard=DEFAULT_WRITE_GUARD, **binding),
                                     context=context, target_binding_id=target_binding_id)
            token = grant.decision_token
        else:
            if (operation_id not in {UPDATE_OPERATION_ID, "artifact.move", "artifact.rename"}
                or original_admission.get("context") != _plain(asdict(context))
                or original_admission.get("selection") != _plain(asdict(selection_record))
                or original_admission.get("intent") != _plain(admitted_intent.to_dict())
                or original_admission.get("target_binding_id") != target_binding_id):
                raise HTTPException(403, "original_batch_admission_required")
            # Restore exact original identity from the existing host-owned
            # journal. This does not call GOV's issuer or extend authority.
            token = DecisionToken(**dict(original_admission["token"]), active_context=context)
            gov.validate_decision_token(decision_token=token, **binding)
            gov.validate_context(token, context=context, target_binding_id=target_binding_id)
        if operation_id in {UPDATE_OPERATION_ID, "artifact.move", "artifact.rename"}:
            host_admission = {"context": _plain(asdict(context)),
                "selection": _plain(asdict(selection_record)), "resource": resource,
                "intent": _plain(admitted_intent.to_dict()), "target_binding_id": target_binding_id,
                "token": _plain({key: value for key, value in asdict(token).items() if key != "active_context"})}

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
            gov.validate_decision_token(decision_token=token, **binding)
            gov.validate_context(token, context=context, target_binding_id=target_binding_id)
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
        native_reconciler: OwnerHandler | None = (
            (lambda item: reconcile_write_operation(item, config))
            if operation_id == UPDATE_OPERATION_ID else None
        )
        if operation_id in {"artifact.move", "artifact.rename"}:
            placement_owner = KnowledgePlacementOwner(
                vault_root=root, context_ref=context.context_id, vault_generation=str(context.generation),
                actor=actor, active_context=context, target_binding_id=target_binding_id,
                registry_store=registry, context_is_current=lambda: validate_token(),
                authority_is_current=lambda _: validate_token(), filesystem="local-posix-v1",
            )
            placement_config = PlacementOperationServerConfig(
                placement_owner, operation_context, artifact_id or "", resource,
            )
            canonical = build_placement_operation_handlers(placement_config)
            native_reconciler = lambda item: reconcile_placement_operation(item, placement_config)
        elif operation_id in {"artifact.archive", "artifact.restore"}:
            canonical = build_archival_operation_handlers(replace(
                archive_configs[target_binding_id], effect_check=require_effect))

        def invoke_owner(item: OperationRequest) -> Any:
            # Revalidate after kernel/process-lock waits and hold the complete
            # MVR-05C window through native source and authority receipts.
            with context_bound_write_window(context, target_binding_id=target_binding_id,
                token=token, registry_store=registry,
                effect_check=require_effect, **binding):
                return canonical[operation_id](item)

        if native_reconciler is not None:
            def invoke_reconciliation(item: OperationRequest) -> OwnerExecutionResult:
                with context_bound_write_window(context, target_binding_id=target_binding_id,
                    token=token, registry_store=registry,
                    effect_check=require_effect, **binding):
                    assert native_reconciler is not None
                    return native_reconciler(item)
            reconcile_owner = invoke_reconciliation
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
        policy = lambda *_: PolicyDecision.allowed("governed-write.v1", token.token_id)

        def observe_preconditions() -> Mapping[str, Any]:
            from app.heimdal.local_archive import OperationTargetRefused, resolve_operation_restore_target

            try:
                with context_bound_read_window(context, registry_store=registry):
                    require_effect()
                    arguments = dict(operation.arguments)
                    expected: str | int | None = None
                    if operation_id == UPDATE_OPERATION_ID:
                        assert note_path is not None
                        expected = read_note_text_with_version(note_path)[1]
                    elif placement_owner is not None:
                        key = "destination" if operation_id == "artifact.move" else "name"
                        if set(arguments) != {key} or not isinstance(arguments[key], str):
                            raise ValueError("one placement destination intent is required")
                        destination = arguments[key]
                        if operation_id == "artifact.rename":
                            destination = str(PurePosixPath(resource).with_name(destination))
                        expected = placement_owner.source_generation(resource, artifact_id or "")
                        arguments["destination_generation"] = placement_owner.destination_generation(destination)
                    elif operation_id in {"artifact.archive", "artifact.restore"}:
                        if (len(operation.targets) != 1
                            or operation.targets[0].get("artifact_class") != "source"):
                            raise ValueError("one source artifact identity is required")
                        expected = resolve_operation_restore_target(
                            str(operation.targets[0]["artifact_id"]),
                            service_reader=archive_configs[target_binding_id].restore_service,
                        ).generation
                    require_effect()
                    return {"expected_version": expected, "arguments": arguments}
            except (KnowledgeCapabilityError, ValueError) as exc:
                raise HTTPException(422, "invalid_operation_preconditions") from exc
            except (KnowledgeWriteConflict, OperationTargetRefused, OSError) as exc:
                raise HTTPException(409, "operation_preconditions_unavailable") from exc

        preconditions_reader = observe_preconditions
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
        unavailable, operation_id, selection_record, readback_config,
        preconditions_reader=preconditions_reader, host_admission=host_admission,
        reconcile_owner=reconcile_owner, active_context=context)
    return runtime
