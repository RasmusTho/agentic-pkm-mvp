"""Batch probes reuse the existing real semantic/WSP/human-approval composition."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from app.governance.governed_write import GovernedWriteAdapter
from app.knowledge.semantic import KnowledgeSemanticOwner, TAGS_ADD
from app.knowledge.write_ops import read_note_text_with_version
from app.operations import JsonReceiptStore
from app.operations.batch_operations import BatchOperationCoordinator
from app.operations.semantic_operations import reconcile_semantic_operation


class Interrupted(BaseException):
    pass


def requests_for(bound, count=3, operation=TAGS_ADD):
    requests = []
    paths = []
    for index in range(count):
        identity = str(uuid4())
        path = bound.owner.root / f"Notes/batch-{index}.md"
        path.write_text(f"---\nuuid: {identity}\nartifact_class: human_knowledge\ntags: []\n---\nHuman body {index}.\n")
        request = replace(bound.request(operation, {"tags": ["reviewed"]}),
                          targets=({"artifact_id": identity},),
                          expected_version=read_note_text_with_version(path)[1])
        resource = path.relative_to(bound.owner.root).as_posix()
        gov = GovernedWriteAdapter()
        grant = gov.issue_human_decision_token(action=f"operation.{operation}",
                                             write_class="vault_semantic_edit", actor=bound.owner.actor,
                                             resource=resource)
        grant = gov.bind_context(grant, context=bound.owner.active_context,
                                 target_binding_id=bound.owner.target_binding_id)
        bound.approvals[request.request_id] = ({
            "operation": operation, "artifact_id": identity,
            "expected_version": request.expected_version, "changes": {"tags": ["reviewed"]},
            "resource": resource, "context_ref": bound.config.context.active_context_ref,
            "vault_generation": bound.config.context.vault_generation,
        }, grant)
        requests.append(request)
        paths.append(path)
    return requests, paths


def delegation_for(requests, *, principal="owner"):
    first = requests[0]
    return {
        "active_context_ref": first.context.active_context_ref,
        "vault_generation": first.context.vault_generation,
        "operation_ids": [first.operation_id], "allowed_effects": [first.operation_id],
        "policy_version": "policy-1", "principal": principal, "client": "test", "surface": "test",
        "receipt_ref": "delegation-batch", "authority_class": "governed_effect",
        "target_ids": [request.targets[0]["artifact_id"] for request in requests],
        "max_targets": len(requests), "expires_at": 4102444800, "revoked": False,
    }


def coordinator(bound, *, restart=False):
    if restart:
        owner = bound.owner
        bound.config = replace(bound.config, owner=KnowledgeSemanticOwner(
            vault_root=owner.root, active_context=owner.active_context,
            target_binding_id=owner.target_binding_id, registry_store=owner.registry_store,
            authorize_semantic=owner.authorize_semantic,
            semantic_authority_window=owner.semantic_authority_window,
            receipt_path=owner.receipt_path,
        ))
    return BatchOperationCoordinator(bound.kernel(store=JsonReceiptStore(
        bound.owner.receipt_path.parent / "batch-kernel.json")),
        reconcile_owner=lambda request: reconcile_semantic_operation(request, bound.config))


def preview(batch, requests, *, batch_id="batch-1"):
    return batch.preview(batch_id=batch_id, requests=requests,
                         selector={"kind": "explicit", "ids": [r.targets[0]["artifact_id"] for r in requests]},
                         delegation=delegation_for(requests), limit=len(requests))


def execute(batch, frozen):
    return batch.execute(frozen.batch_id, expected_digest=frozen.digest)


def source_tags(path: Path):
    import yaml

    return yaml.safe_load(path.read_text().split("---", 2)[1])["tags"]


def native_receipt(item):
    return item.outcome.receipt.extensions["write"]
