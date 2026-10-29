"""Finite HTTP composition of the delivered coordinator and production owners.

All durable state belongs to the existing kernel journal. Original host
admission is retained inside its frozen selector, never returned as client
input or upgraded into current authority after selection loss.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from fastapi import HTTPException, Request

from app.api.operation_runtime import (
    EFFECTS, ProductionOperationRuntime, _plain, build_production_operation_runtime,
)
from app.governance.governed_write import DecisionToken
from app.instance.context_bound_read import context_bound_read_window
from app.operations.batch_operations import (
    MAX_BATCH_ITEMS, SUPPORTED_BATCH_OPERATIONS, BatchOperationCoordinator,
    BatchResult, BatchStateUnavailable,
)
from app.operations.contracts import OperationProvenance, OperationRequest
from app.operations.execution_kernel import OperationExecutionKernel, OwnerExecutionResult, PolicyDecision
from app.operations.write_operations import WriteOperationServerConfig, reconcile_write_operation

_PRODUCER = "production_operations_http.v1"
_READ_SCOPE = ("workspace", "scope", "sphere_memberships", "situated_identity", "instance_identity")


@dataclass
class ProductionBatchRuntime:
    base: ProductionOperationRuntime
    request: Request
    api_key: str | None
    session_bearer: str | None
    override_bearer: str | None

    @property
    def supported_kinds(self) -> frozenset[str]:
        return SUPPORTED_BATCH_OPERATIONS.intersection(self.base.kernel.handlers)

    def _coordinator(self, bindings: Mapping[str, ProductionOperationRuntime],
                     context: Any, admitted: bool) -> BatchOperationCoordinator:
        def bound(item: OperationRequest) -> ProductionOperationRuntime:
            runtime = bindings[item.request_id]
            assert runtime.host_admission is not None
            original = replace(item, delegation=None, batch_policy=None)
            if _plain(original.to_dict()) != runtime.host_admission["intent"]:
                raise BatchStateUnavailable("item differs from original host admission")
            return runtime

        def guarded(item: OperationRequest, call: Callable[[ProductionOperationRuntime], Any]) -> Any:
            runtime = bound(item)
            with runtime.selection_window():
                return call(runtime)

        def version(item: OperationRequest) -> bool:
            runtime = bound(item)
            assert runtime.active_context is not None
            with runtime.selection_window(), context_bound_read_window(
                runtime.active_context, registry_store=runtime.registry,
            ):
                return runtime.kernel.version_checker(item)

        def reconcile(item: OperationRequest) -> OwnerExecutionResult:
            def owner(runtime: ProductionOperationRuntime) -> OwnerExecutionResult:
                if runtime.reconcile_owner is None:
                    return OwnerExecutionResult.ambiguous()
                return runtime.reconcile_owner(item)
            return guarded(item, owner)

        kind = next(iter(bindings.values())).operation_id if bindings else ""
        kernel = OperationExecutionKernel(
            context_resolver=lambda selected: admitted and selected == context,
            policy_evaluator=lambda item, delegation: bound(item).kernel.policy_evaluator(item, delegation)
                if admitted else PolicyDecision.denied("governed-write.v1", "original batch admission unavailable"),
            handlers={kind: lambda item: guarded(item, lambda runtime: runtime.kernel.handlers[kind](item))}
                if admitted else {},
            receipt_store=self.base.kernel.receipt_store,
            version_checker=version if admitted else lambda _: False,
            token_validator=lambda item, decision: guarded(item,
                lambda runtime: runtime.kernel.token_validator(item, decision)) if admitted else False,
        )
        return BatchOperationCoordinator(kernel, reconcile_owner=reconcile if admitted else None)

    def _bind(self, item: OperationRequest, target: str,
              original: Mapping[str, Any] | None = None) -> ProductionOperationRuntime:
        runtime = build_production_operation_runtime(self.request, api_key=self.api_key,
            session_bearer=self.session_bearer, override_bearer=self.override_bearer,
            operation=item, target_binding_id=target, original_admission=original)
        # A factory may have waited or reentered resolution. All items must
        # still belong to the one ORIGINAL captured record and snapshot.
        if (runtime.selection_record != self.base.selection_record
            or runtime.active_context != self.base.active_context
            or runtime.host_admission is None
            or item.operation_id not in runtime.kernel.handlers):
            raise HTTPException(403, "original_batch_admission_required")
        runtime.kernel.receipt_store = self.base.kernel.receipt_store
        return runtime

    def preview(self, batch_id: str, requests: Sequence[OperationRequest], *,
                target_binding_id: str, limit: int = MAX_BATCH_ITEMS,
                partial_success_policy: str = "independent") -> dict[str, Any]:
        assert self.base.active_context is not None
        kind = requests[0].operation_id
        if kind not in self.supported_kinds:
            return {"status": "not_supported", "operation_id": kind,
                    "reason": self.base.unavailable.get(kind, "qualified finite batch owner unavailable")}
        if any((item.context.active_context_ref, item.context.vault_generation) != (
            self.base.context.active_context_ref, self.base.context.vault_generation,
        ) for item in requests):
            raise HTTPException(409, "active_context_generation_stale")
        if target_binding_id not in self.base.context.extensions["vault_binding_ids"]:
            raise HTTPException(403, "selected_target_required")
        context = replace(self.base.context, extensions={**self.base.context.extensions,
                                                        "target_binding_id": target_binding_id})
        items = tuple(replace(item, context=context,
            provenance=OperationProvenance(self.base.actor, "http", "shared_http")) for item in requests)
        try:
            stored = self.base.kernel.receipt_store.lookup("ygg.batch:" + batch_id)
        except Exception as exc:
            raise BatchStateUnavailable("existing batch journal unavailable") from exc
        if stored is not None:
            coordinator, frozen, admitted = self._retained(batch_id, stored.intent_digest)
            if (frozen["requests"] != _plain([item.to_dict() for item in items])
                or frozen["limit"] != limit or frozen["partial_success_policy"] != partial_success_policy
                or frozen["selector"]["target_binding_id"] != target_binding_id):
                raise HTTPException(409, "batch_identity_conflict")
            return self._response(coordinator.inspect(batch_id, expected_digest=stored.intent_digest),
                                  "original" if admitted else "refused", frozen)
        bindings: dict[str, ProductionOperationRuntime] = {}
        for item in items:
            runtime = self._bind(item, target_binding_id)
            with runtime.selection_window():
                decision = runtime.kernel.policy_evaluator(item, {})
                if not decision.admitted or not runtime.kernel.token_validator(item, decision):
                    raise HTTPException(403, "operation_authority_unavailable")
                if not runtime.kernel.version_checker(item):
                    raise HTTPException(409, "version_precondition_failed")
            bindings[item.request_id] = runtime
        selected = self.base.selection_record
        delegation = {
            "active_context_ref": context.active_context_ref, "vault_generation": context.vault_generation,
            "operation_ids": [kind], "allowed_effects": [kind], "policy_version": "governed-write.v1",
            "principal": self.base.actor, "client": "http", "surface": "shared_http",
            "receipt_ref": selected.selection_capability_digest, "authority_class": "governed_effect",
            "target_ids": [item.targets[0]["artifact_id"] for item in items], "max_targets": len(items),
            "expires_at": selected.expires_at, "revoked": False,
            "batch_policy": {"partial_success_policy": "independent"},
        }
        selector = {"producer": _PRODUCER, "actor": self.base.actor,
            "target_binding_id": target_binding_id,
            "context": _plain(asdict(self.base.active_context)),
            "selection": _plain(asdict(selected)),
            "admissions": {key: value.host_admission for key, value in bindings.items()}}
        coordinator = self._coordinator(bindings, context, True)
        with self.base.selection_window() as require_current:
            require_current()
            preview = coordinator.preview(batch_id=batch_id, requests=items,
                selector=selector, delegation=delegation, limit=limit,
                partial_success_policy=partial_success_policy)
        return self._response(coordinator.inspect(batch_id, expected_digest=preview.digest), "original")

    def _retained(self, batch_id: str, digest: str, *, for_effect: bool = False) -> tuple[BatchOperationCoordinator, Mapping[str, Any], bool]:
        assert self.base.active_context is not None
        reader = BatchOperationCoordinator(self.base.kernel)
        frozen = reader.frozen_intent(batch_id, expected_digest=digest)
        try:
            host = frozen["selector"]
            original_context = host["context"]
            current = _plain(asdict(self.base.active_context))
            target = host["target_binding_id"]
            if (host["producer"] != _PRODUCER or host["actor"] != self.base.actor
                or original_context["principal_context"]["principal_id"] != self.base.actor
                or any(current[key] != original_context[key] for key in _READ_SCOPE)
                or target not in self.base.context.extensions["vault_binding_ids"]):
                raise HTTPException(404, "batch_unavailable")
            items = tuple(OperationRequest.from_dict(raw) for raw in frozen["requests"])
            if (not 1 <= len(items) <= MAX_BATCH_ITEMS
                or set(host["admissions"]) != {item.request_id for item in items}
                or frozen["delegation"]["principal"] != self.base.actor
                or frozen["delegation"]["expires_at"] != host["selection"]["expires_at"]
                or frozen["delegation"]["expires_at"] != original_context["expires_at"]):
                raise ValueError("incomplete host admission")
            for item in items:
                admission = host["admissions"][item.request_id]
                resource = PurePosixPath(admission["resource"])
                action, write_class = EFFECTS[item.operation_id]
                if (item.operation_id not in {"artifact.update", "artifact.move", "artifact.rename"}
                    or admission["intent"] != _plain(item.to_dict())
                    or admission["context"] != original_context or admission["selection"] != host["selection"]
                    or admission["target_binding_id"] != target
                    or item.context.extensions["target_binding_id"] != target
                    or resource.is_absolute() or ".." in resource.parts or not resource.parts):
                    raise ValueError("foreign host admission")
                token = DecisionToken(**dict(admission["token"]))
                if not token.token_id or not token.decision_id:
                    raise ValueError("missing original decision")
                # Structural journal validation is separate from current GOV
                # admission. A live write veto cannot hide retained read/cancel
                # truth; the production factory revalidates GOV before effects.
                if (not token.valid or (token.action, token.write_class, token.actor, token.resource)
                    != (action, write_class, self.base.actor, str(resource))):
                    raise ValueError("original decision binding differs")
        except HTTPException:
            raise
        except Exception as exc:
            raise BatchStateUnavailable("original host-admitted batch state unavailable") from exc
        admitted = (current == original_context
                    and _plain(asdict(self.base.selection_record)) == host["selection"])
        bindings = {item.request_id: self._bind(item, target, host["admissions"][item.request_id])
                    for item in items} if admitted and for_effect else {}
        return self._coordinator(bindings, items[0].context, admitted), frozen, admitted

    def inspect(self, batch_id: str, *, expected_digest: str) -> dict[str, Any]:
        coordinator, frozen, admitted = self._retained(batch_id, expected_digest)
        result = coordinator.inspect(batch_id, expected_digest=expected_digest)
        return self._response(result, "original" if admitted else "refused", frozen)

    def cancel(self, batch_id: str, *, expected_digest: str) -> dict[str, Any]:
        coordinator, frozen, admitted = self._retained(batch_id, expected_digest)
        result = coordinator.cancel(batch_id, expected_digest=expected_digest)
        return self._response(result, "original" if admitted else "refused", frozen)

    def execute(self, batch_id: str, *, expected_digest: str) -> dict[str, Any]:
        coordinator, frozen, admitted = self._retained(batch_id, expected_digest, for_effect=True)
        result = coordinator.execute(batch_id, expected_digest=expected_digest)
        return self._response(result, "original" if admitted else "refused", frozen)

    def _response(self, result: BatchResult, admission: str,
                  frozen: Mapping[str, Any] | None = None) -> dict[str, Any]:
        items = [{"request_id": item.request_id, "artifact_id": item.artifact_id,
                  "state": item.state, "outcome": item.outcome.to_dict() if item.outcome else None}
                 for item in result.items]
        # A new, properly scoped read selection may inspect original body
        # receipts after WSP restart. This readback never reissues authority,
        # changes a kernel outcome, or acknowledges the batch as successful.
        if frozen is not None:
            original = frozen["selector"]
            assert self.base.active_context is not None
            with context_bound_read_window(self.base.active_context, registry_store=self.base.registry) as roots:
                root = next(value.root for value in roots if value.vault_binding_id == original["target_binding_id"])
                for item, raw in zip(items, frozen["requests"], strict=True):
                    if (raw["operation_id"] != "artifact.update" or item["outcome"] is None
                        or item["outcome"]["status"] not in {"recovery_required", "not_acknowledged"}):
                        continue
                    request = replace(OperationRequest.from_dict(raw), delegation=frozen["delegation"])
                    config = WriteOperationServerConfig(root, request.context, self.base.actor,
                        root / original["admissions"][request.request_id]["resource"],
                        request.targets[0]["artifact_id"])
                    proof = reconcile_write_operation(request, config)
                    if proof.effect_receipt is not None:
                        item["outcome"]["extensions"]["owner_readback"] = {
                            "status": proof.status.value, "effect_receipt": dict(proof.effect_receipt),
                            "convergence": proof.convergence.to_dict() if proof.convergence else None}
        return {**asdict(result.preview), "status": result.status, "counts": result.counts,
                "cancel_requested": result.cancel_requested, "items": items,
                "current_admission": admission}


def build_production_batch_runtime(request: Request, *, api_key: str | None,
    session_bearer: str | None, override_bearer: str | None) -> ProductionBatchRuntime:
    base = build_production_operation_runtime(request, api_key=api_key,
        session_bearer=session_bearer, override_bearer=override_bearer)
    return ProductionBatchRuntime(base, request, api_key, session_bearer, override_bearer)
