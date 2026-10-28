"""AUTOOPS-03 (#5332): discovery and read operations over owner-native seams.

Every test resolves its vault context through the real
``ActiveContextSelectionService.resolve_request_context`` seam against a
provisioned instance registry; nothing seeds an ambient vault selection.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.api.read_operation_owners import build_read_operation_adapter
from app.api.routes import active_context_selection as selection_routes
from app.instance.active_context_service import (
    ACTION_SELECTION_INSPECT,
    PERMISSION_SELECTION_READ,
    WRITE_CLASS_READ,
    ActiveContextSelectionService,
)
from app.instance.context_selection import ContextSelectionStore
from app.operations import OperationContext, OperationProvenance, OperationRequest, OperationStatus
from app.operations.read_operations import (
    DISCOVERY_OPERATION_ID,
    LIST_OPERATION_ID,
    READ_OPERATION_ID,
    READ_OWNERS,
    RELATED_OPERATION_ID,
    SEARCH_OPERATION_ID,

    RequestContextCarrier,
)
from app.retrieval.hybrid import get_store, reset_durable_rebuild_state
from tests._mvr03_principal_harness import provisioned_instance

ALPHA_ID = "8f6d2c1e-0000-4000-8000-00000000a1fa"
BETA_ID = "8f6d2c1e-0000-4000-8000-00000000be7a"
PROVENANCE = OperationProvenance(actor="operator", client="test-client", surface="direct")


@pytest.fixture(autouse=True)
def _isolated_globals(monkeypatch: pytest.MonkeyPatch):
    import app.vault.manager as vault_manager_module

    # The fixture seeds a synthetic cache, not the durable index. A retained
    # durable-generation lineage must not rebuild it from another test's store.
    reset_durable_rebuild_state()
    monkeypatch.setattr(vault_manager_module, "_GLOBAL_MANAGER", None)
    monkeypatch.setattr("app.retrieval.hybrid.embed_text", lambda text, language=None: [0.1, 0.1, 0.1])
    monkeypatch.setattr(
        "app.retrieval.hybrid.embed_docs", lambda texts: ([[0.1, 0.1, 0.1] for _ in texts], {})
    )
    yield
    get_store().set_documents([])
    reset_durable_rebuild_state()


@pytest.fixture()
def bound(tmp_path, monkeypatch):
    runtime, first, _extra, record = provisioned_instance(tmp_path, extra_roots=("two",))
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    selection_routes.reset_selection_store_for_tests()
    root = Path(runtime.registry.lookup(first.vault_binding_id).path)  # type: ignore[union-attr]
    (root / "alpha.md").write_text(
        f"---\nuuid: {ALPHA_ID}\nkind: note\ntags: [parity]\n---\n# Alpha\nMCP parity notes.\n",
        encoding="utf-8",
    )
    (root / "beta.md").write_text(
        f"---\nuuid: {BETA_ID}\nkind: note\ntags: [parity]\n---\n# Beta\nSee [[alpha]].\n",
        encoding="utf-8",
    )
    service = ActiveContextSelectionService(
        registry_store=runtime.registry,
        principal_record=record,
        selection_store=ContextSelectionStore(),
    )
    derived = service.derive("trusted_loopback")
    bearer, _ = service.create(derived=derived, binding_ids=[first.vault_binding_id])
    carrier = RequestContextCarrier(service, derived, bearer)
    context = carrier.resolve()
    get_store().set_documents(
        [
            {
                "doc_id": ALPHA_ID,
                "text": "MCP parity notes",
                "payload": {
                    "title": "Alpha",
                    "note_path": "alpha.md",
                    "domain": context.scope,
                    "vault_binding_id": first.vault_binding_id,
                },
            }
        ]
    )
    adapter = build_read_operation_adapter(runtime.registry)
    return adapter, carrier, context, root, first


def _request(operation_id: str, context, *, generation=None, **kwargs) -> OperationRequest:
    return OperationRequest(
        operation_id,
        f"req-{operation_id}",
        OperationContext(
            context.context_id,
            str(context.generation) if generation is None else generation,
        ),
        provenance=PROVENANCE,
        **kwargs,
    )


_TARGET = ({"artifact_id": ALPHA_ID},)


def _all_requests(context) -> dict[str, OperationRequest]:
    return {
        LIST_OPERATION_ID: _request(LIST_OPERATION_ID, context),
        READ_OPERATION_ID: _request(READ_OPERATION_ID, context, targets=_TARGET),
        SEARCH_OPERATION_ID: _request(SEARCH_OPERATION_ID, context, arguments={"query": "MCP parity"}),
        RELATED_OPERATION_ID: _request(RELATED_OPERATION_ID, context, targets=_TARGET),
    }


def test_read_operations_delegate_to_canonical_production_services(bound, monkeypatch) -> None:
    adapter, carrier, context, root, first = bound
    import app.api.read_operation_owners as owners
    import app.retrieval.capability as capability

    calls: list[tuple[str, object]] = []

    def spy(module, name, label, pick):
        original = getattr(module, name)

        def wrapper(*args, **kwargs):
            calls.append((label, pick(*args, **kwargs)))
            return original(*args, **kwargs)

        monkeypatch.setattr(module, name, wrapper)

    spy(owners, "_select_vault_notes", "list", lambda vault_root, **_: Path(vault_root))
    spy(owners, "_resolve_and_validate", "read", lambda locator, vault_root: (locator, Path(vault_root)))
    spy(capability, "retrieve", "search", lambda request: request.active_context)
    spy(owners, "_rank_related_notes", "related", lambda target, notes, **_: target["artifact_uuid"])
    seam_calls: list[dict] = []
    original_seam = ActiveContextSelectionService.resolve_request_context

    def seam(self, **kwargs):
        seam_calls.append(kwargs)
        return original_seam(self, **kwargs)

    monkeypatch.setattr(ActiveContextSelectionService, "resolve_request_context", seam)

    for operation_id, request in _all_requests(context).items():
        outcome = adapter.invoke(request, carrier)
        assert outcome.status is OperationStatus.SUCCEEDED, (operation_id, outcome.extensions)
        assert outcome.extensions["read_owner"] == READ_OWNERS[operation_id]
        assert outcome.items, operation_id

    resolved_root = root.resolve()
    assert calls == [
        ("list", resolved_root),
        ("read", ("alpha.md", resolved_root)),
        ("search", context),
        ("related", ALPHA_ID),
    ]
    # Vault context is resolved only by the owner-native request seam, as a read.
    assert len(seam_calls) == 4
    assert all(
        call["session_bearer"] == carrier.session_bearer
        and call["action"] == ACTION_SELECTION_INSPECT
        and call["write_class"] == WRITE_CLASS_READ
        and call["required_permission"] == PERMISSION_SELECTION_READ
        for call in seam_calls
    )
    discovery = adapter.invoke(_request(DISCOVERY_OPERATION_ID, context), None)
    assert discovery.status is OperationStatus.SUCCEEDED
    assert {item.resource_id for item in discovery.items} == {*READ_OWNERS, DISCOVERY_OPERATION_ID}


def test_read_results_preserve_identity_context_provenance_and_freshness(bound) -> None:
    adapter, carrier, context, _root, first = bound
    outcomes = {
        operation_id: adapter.invoke(request, carrier)
        for operation_id, request in _all_requests(context).items()
    }
    expected_context = {
        "context_id": context.context_id,
        "context_generation": context.generation,
        "vault_binding_id": first.vault_binding_id,
        "vault_id": context.source_bindings[0].vault_id,
    }
    for operation_id, outcome in outcomes.items():
        assert outcome.status is OperationStatus.SUCCEEDED, operation_id
        assert outcome.request_id == f"req-{operation_id}"
        assert outcome.provenance == PROVENANCE
        assert outcome.context.vault_generation == str(context.generation)
        assert outcome.extensions["resolved_context"]["generation"] == context.generation
        assert outcome.extensions["freshness"]["context_generation"] == context.generation
        for item in outcome.items:
            payload = item.payload
            assert item.resource_id == payload["stable_id"]
            assert payload["identity_state"] == "stable"
            assert payload["vault_context"] == expected_context
            assert payload["provenance"]["owner"] == READ_OWNERS[operation_id]
            assert payload["freshness"]["state"]
            assert not os.path.isabs(payload["current_locator"])

    listed = {item.resource_id: item.payload["current_locator"] for item in outcomes[LIST_OPERATION_ID].items}
    assert listed == {ALPHA_ID: "alpha.md", BETA_ID: "beta.md"}
    read_item = outcomes[READ_OPERATION_ID].items[0]
    assert (read_item.resource_id, read_item.payload["current_locator"]) == (ALPHA_ID, "alpha.md")
    assert read_item.resulting_version and "MCP parity" in read_item.payload["body"]
    assert outcomes[READ_OPERATION_ID].extensions["freshness"]["state"] == "source_read"
    search = outcomes[SEARCH_OPERATION_ID]
    assert [item.resource_id for item in search.items] == [ALPHA_ID]
    assert search.extensions["freshness"]["source"] == "retrieval.durable_index"
    assert search.extensions["freshness"]["indexed_documents_for_context"] == 1
    related = outcomes[RELATED_OPERATION_ID].items
    assert [item.resource_id for item in related] == [BETA_ID]
    assert related[0].payload["provenance"]["signals"]


def test_read_failures_are_typed_and_never_ambiguous_empty_success(bound, monkeypatch, tmp_path) -> None:
    adapter, carrier, context, _root, _first = bound
    search = _request(SEARCH_OPERATION_ID, context, arguments={"query": "MCP parity"})
    read = _request(READ_OPERATION_ID, context, targets=_TARGET)

    def state(outcome):
        return outcome.status, outcome.extensions["read_state"]

    # Missing context: no generation, no carrier, or no bearer.
    no_generation = OperationRequest(
        READ_OPERATION_ID, "r1", OperationContext(context.context_id), targets=_TARGET
    )
    assert state(adapter.invoke(no_generation, carrier)) == (OperationStatus.INVALID, "missing_context")
    assert state(adapter.invoke(read, None)) == (OperationStatus.INVALID, "missing_context")
    assert state(adapter.invoke(read, RequestContextCarrier(carrier.service, carrier.derived, None))) == (
        OperationStatus.INVALID, "missing_context")
    # An unknown bearer and a stale generation fail closed through the seam.
    assert state(adapter.invoke(read, RequestContextCarrier(carrier.service, carrier.derived, "unknown"))) == (
        OperationStatus.REJECTED, "context_unavailable")
    assert state(adapter.invoke(_request(READ_OPERATION_ID, context, generation="999", targets=_TARGET), carrier)) == (
        OperationStatus.CONFLICTED, "stale_context")

    # Unavailable index: empty for the bound vault, or failing outright.
    get_store().set_documents([])
    empty = adapter.invoke(search, carrier)
    assert state(empty) == (OperationStatus.DEGRADED_READ, "index_unavailable") and empty.items == ()
    import app.retrieval.capability as capability

    def broken(_request):
        raise RuntimeError("durable index unavailable")

    monkeypatch.setattr(capability, "retrieve", broken)
    assert state(adapter.invoke(search, carrier)) == (OperationStatus.DEGRADED_READ, "index_unavailable")

    # Inaccessible versus absent artifacts.
    locked = tmp_path / "locked.md"
    locked.write_text("secret", encoding="utf-8")
    locked.chmod(0)
    import app.api.read_operation_owners as owners

    monkeypatch.setattr(owners, "_resolve_and_validate", lambda locator, vault_root: locked)
    try:
        assert state(adapter.invoke(read, carrier)) == (OperationStatus.REJECTED, "artifact_inaccessible")
    finally:
        locked.chmod(0o600)
    absent = _request(READ_OPERATION_ID, context, targets=({"artifact_id": "no-such-artifact"},))
    assert state(adapter.invoke(absent, carrier)) == (OperationStatus.NOT_FOUND, "artifact_not_found")
    # A locator is never accepted in place of stable identity.
    by_path = _request(READ_OPERATION_ID, context, targets=({"locator": "alpha.md"},))
    assert state(adapter.invoke(by_path, carrier)) == (OperationStatus.INVALID, "invalid_arguments")
    assert state(adapter.invoke(_request("artifact.unknown", context), carrier)) == (
        OperationStatus.NOT_SUPPORTED, "capability_unavailable")
