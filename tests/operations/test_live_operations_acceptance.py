"""Pre-merge proof of the guarded runner, never deployed feature acceptance."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys
from time import time

import pytest

from app.api.native_operations_acceptance import native_probe
from app.ops.operations_acceptance import (
    CONTEXT_FILE, FAMILIES, OperationsAcceptanceRefusal, digest, file_hash, inventory,
    load_context, produce_receipt, read_private, write_private,
)
from tests.operations._operations_acceptance_harness import host, journey, identity, OPERATION, sdk_python
from tests.operations._surface_harness import runtime_http

pytestmark = pytest.mark.usefixtures("product_model_access_gateway")


def test_native_read_leases_preserve_frozen_authority_and_original_evidence(tmp_path, monkeypatch):
    instance = host(tmp_path, monkeypatch, freeze=False)
    prepared = read_private(instance.runtime.registry.path.parent / CONTEXT_FILE)
    original_hash = prepared["fixture"]["registry_sha256"]
    frozen = instance.client.post("/api/operations/acceptance/admission", json={}, headers=instance.headers)
    assert frozen.status_code == 200, frozen.text
    first = frozen.json()
    # Another real runtime composition advances native mechanical leases.
    again = instance.client.post("/api/operations/acceptance/admission", json={}, headers=instance.headers)
    assert again.status_code == 200 and again.json() == first
    retained = read_private(instance.runtime.registry.path.parent / CONTEXT_FILE)
    snapshot, authority = instance.runtime.registry.read_qualification_state()
    assert retained["fixture"]["registry_sha256"] == original_hash
    assert file_hash(instance.runtime.registry.path) != original_hash
    assert authority == prepared["fixture"]["registry_authority_sha256"]
    assert snapshot.extensions["bindingEffectLeases"][instance.binding_id]["generation"] >= 2
    assert len(retained["slots"]) == 15
    assert "registry_checkpoint" not in retained
    # Keep the real configured-backend doctor and independent selected-source
    # coverage. No DATABASE_URL or optional legacy-PG scan is needed for memory.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    observed = native_probe(instance.runtime.registry.path)
    assert observed["native_doctor"]["checked"]
    assert observed["source_store_index_links"]["status"] == "healthy"


@pytest.mark.parametrize("case", ["instance", "unknown-extension", "binding-extension", "principal", "body", "formatting", "lease-malformed", "transaction", "fingerprint-missing"])
def test_frozen_native_authority_drift_refuses_real_effect_without_rebasing(tmp_path, monkeypatch, case):
    import json
    from app.instance.runtime import open_local_operator_principal_store
    from tests.operations.live_operations_acceptance import OperationsJourney
    from tests.operations._operations_acceptance_harness import LocalNative
    instance = host(tmp_path, monkeypatch)
    registry = instance.runtime.registry
    context_path = registry.path.parent / CONTEXT_FILE
    original_context = context_path.read_bytes()
    before = {str(path): file_hash(path) for path in instance.root.rglob("*.md")}
    run = OperationsJourney(LocalNative(instance), tmp_path / "unused")
    run.binding = instance.binding
    command = run.command("edit")
    if case == "fingerprint-missing":
        context = read_private(context_path)
        del context["fixture"]["registry_authority_sha256"]
        write_private(context_path, context)
    elif case == "transaction":
        registry.transaction_path.write_bytes(b"Unqualified interrupted native transaction.\n")
    elif case == "principal":
        principal = open_local_operator_principal_store(registry.path)
        payload = json.loads(principal.path.read_bytes())
        payload["updated_at"] += 1  # Valid, same principal identity/revision.
        principal.path.write_bytes(principal._serialize(payload))
        assert principal.require().revision == payload["revision"]
    elif case in {"body", "formatting", "lease-malformed"}:
        payload = registry.path.read_bytes()
        if case == "body":
            payload += b"Unqualified body drift.\n"
        elif case == "formatting":
            payload = payload.replace(b"\nrevision: ", b"\nrevision:  ", 1)
        else:
            from app.instance.vault_registry import _split_rendered, _render_markdown_settings
            frontmatter, body = _split_rendered(payload.decode(), registry.path)
            frontmatter["bindingEffectLeases"][instance.binding_id]["generation"] = "unqualified"
            payload = _render_markdown_settings(frontmatter, body).encode()
        registry.path.write_bytes(payload)
    else:
        with registry._locked():
            snapshot = registry._read_current_locked(recover=False)
            if case == "instance":
                changed = replace(snapshot, app_install_id=snapshot.app_install_id + "-drift")
            elif case == "unknown-extension":
                changed = replace(snapshot, extensions={**snapshot.extensions, "unrecognizedFutureAuthority": {"changed": True}})
            else:
                registration = snapshot.registrations[instance.binding_id]
                rows = {**snapshot.registrations, instance.binding_id:
                        replace(registration, extensions={**registration.extensions, "unrecognizedFutureBinding": True})}
                changed = replace(snapshot, registrations=rows)
            assert changed.revision == snapshot.revision
            registry._write_locked(changed)
    current_context = context_path.read_bytes()
    with pytest.raises(OperationsAcceptanceRefusal):
        native_probe(registry.path)
    raw_before_effect = registry.path.read_bytes()
    refused = instance.client.post("/api/operations", json=command, headers=instance.headers)
    assert refused.status_code in {401, 403, 409} or refused.json().get("status") in {"rejected", "invalid", "conflicted"}, refused.text
    assert before == {str(path): file_hash(path) for path in instance.root.rglob("*.md")}
    assert context_path.read_bytes() == current_context
    if case != "fingerprint-missing":
        assert current_context == original_context
    if case in {"body", "formatting", "lease-malformed", "transaction"}:
        assert registry.path.read_bytes() == raw_before_effect  # No native heal/normalization.
    if case == "transaction":
        assert registry.transaction_path.read_bytes() == b"Unqualified interrupted native transaction.\n"


def test_native_lease_divergence_keeps_existing_effect_fence(tmp_path, monkeypatch):
    from tests.operations.live_operations_acceptance import OperationsJourney
    from tests.operations._operations_acceptance_harness import LocalNative
    instance = host(tmp_path, monkeypatch)
    registry = instance.runtime.registry
    _, original_authority = registry.read_qualification_state()
    with registry._locked():
        snapshot = registry._read_current_locked(recover=False)
        extensions = deepcopy(snapshot.extensions)
        extensions["bindingEffectLeases"][instance.binding_id]["generation"] += 1
        registry._write_locked(replace(snapshot, extensions=extensions))
    # Mechanical shape is valid; the existing owner still detects a mismatch
    # with its physical state before entering any actual source effect.
    assert registry.read_qualification_state()[1] == original_authority
    run = OperationsJourney(LocalNative(instance), tmp_path / "unused")
    run.binding = instance.binding
    before = {str(path): file_hash(path) for path in instance.root.rglob("*.md")}
    refused = instance.client.post("/api/operations", json=run.command("edit"), headers=instance.headers)
    assert refused.status_code == 403 and refused.json()["detail"] == "operation_authority_unavailable", refused.text
    assert before == {str(path): file_hash(path) for path in instance.root.rglob("*.md")}


@pytest.mark.parametrize("case", ["note", "directory-link"])
def test_added_source_between_preparation_and_freeze_is_refused(tmp_path, monkeypatch, case):
    instance = host(tmp_path, monkeypatch, freeze=False)
    if case == "note":
        (instance.root / "Notes/intervening.md").write_text("Unqualified intervening source.\n")
    else:
        (instance.root / "intervening-alias").symlink_to(instance.root / "Notes", target_is_directory=True)
    def snapshot():
        return {str(path): "link:" + str(path.readlink()) if path.is_symlink() else file_hash(path)
                for path in instance.root.rglob("*") if path.is_file() or path.is_symlink()}
    before = snapshot()
    frozen = instance.client.post("/api/operations/acceptance/admission", json={}, headers=instance.headers)
    assert frozen.status_code == 409 and frozen.json()["detail"] == "fixture_changed_before_freeze"
    original = read_private(instance.runtime.registry.path.parent / CONTEXT_FILE)
    assert original["selection"] is None and original["slots"] is None
    assert before == snapshot()


@pytest.mark.parametrize("case", ["layout", "briefing", "layout-selection"])
def test_frozen_passive_facts_are_rechecked_before_effect_and_probe(tmp_path, monkeypatch, case):
    from app.briefing.compose import briefing_note_path
    from app.briefing.trigger import _local_now
    from app.vault.layout import load_layout
    from app.vault.manager import VaultContext
    from app.operations.execution_kernel import JsonReceiptStore
    instance = host(tmp_path, monkeypatch)
    original = read_private(instance.runtime.registry.path.parent / CONTEXT_FILE)
    layout = load_layout(instance.root).note_path
    briefing = briefing_note_path(
        vault_context=VaultContext(status="selected", active_vault_path=str(instance.root)),
        for_date=_local_now(None).date())
    if case == "layout-selection":
        alternate = layout.parent / "alternate-layout.md"
        alternate.write_bytes(layout.read_bytes())
        monkeypatch.setenv("VAULT_LAYOUT_NOTE_REL", alternate.relative_to(instance.root).as_posix())
    else:
        target = layout if case == "layout" else briefing
        target.write_text(target.read_text() + "Changed frozen passive prestate.\n")
    before = {str(path): file_hash(path) for path in instance.root.rglob("*") if path.is_file()}
    slot = next(row for row in original["slots"] if row["id"] == "edit")
    command = {**slot["intent"], "request_id": "post-freeze-passive-" + case,
        "active_context_ref": instance.selection["context"]["context_id"],
        "vault_generation": str(instance.selection["context"]["generation"]),
        "target_binding_id": instance.binding_id}
    response = instance.client.post("/api/operations", json=command, headers=instance.headers)
    assert response.status_code == 200 and response.json()["status"] == "rejected", response.text
    store = JsonReceiptStore(instance.runtime.registry.path.parent / "operation-receipts.json")
    assert store.lookup("ygg.acceptance:" + OPERATION + ":edit") is None
    with pytest.raises(OperationsAcceptanceRefusal, match="frozen_source_configuration_changed"):
        native_probe(instance.runtime.registry.path)
    assert before == {str(path): file_hash(path) for path in instance.root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("case", ["missing", "malformed", "undeclared", "layout-missing", "layout-malformed"])
def test_native_preparation_requires_owner_validated_passive_navigation(tmp_path, monkeypatch, case):
    from app.api.native_operations_acceptance import prepare_native_context
    from app.briefing.compose import briefing_note_path, load_briefing
    from app.briefing.trigger import BRIEFING_ENABLED, _local_now
    from app.vault.layout import load_layout
    from app.vault.manager import VaultContext
    assert BRIEFING_ENABLED
    instance = host(tmp_path, monkeypatch, freeze=False, prepare=False)
    context = VaultContext(status="selected", active_vault_path=str(instance.root))
    today = _local_now(None).date()
    target = briefing_note_path(vault_context=context, for_date=today)
    assert load_briefing(vault_context=context, for_date=today) is not None
    if case == "missing":
        target.unlink()
        reason = "native_navigation_first_contact_not_passive"
    elif case == "malformed":
        target.write_text(target.read_text() + "Unstructured extra body.\n")
        reason = "native_navigation_briefing_unqualified"
    elif case == "undeclared":
        (instance.root / "Notes/undeclared.md").write_text("Undeclared human source.\n")
        reason = "undeclared_fixture_source"
    else:
        layout = load_layout(instance.root).note_path
        if case == "layout-missing":
            layout.unlink()
        else:
            layout.write_bytes(b"\xffMalformed native layout encoding.\n")
        reason = "canonical_fixture_layout_unqualified"
    before = {str(path): file_hash(path) for path in instance.root.rglob("*") if path.is_file()}
    with pytest.raises(OperationsAcceptanceRefusal, match=reason):
        prepare_native_context(instance.identity, registry_path=instance.runtime.registry.path)
    assert before == {str(path): file_hash(path) for path in instance.root.rglob("*") if path.is_file()}
    assert not (instance.runtime.registry.path.parent / CONTEXT_FILE).exists()


@pytest.mark.parametrize("channel", ["test", "dev"])
def test_channel_entrypoints_enforce_native_operations_admission(tmp_path, monkeypatch, capsys, channel):
    from tests.operations.live_operations_acceptance import main
    from app.api.native_operations_acceptance import prepare_native_context
    instance = host(tmp_path, monkeypatch, channel=channel, freeze=False)
    binding = instance.initial
    before = {str(path): file_hash(path) for path in instance.root.rglob("*.md")}
    source = instance.sources["edit"]
    from app.knowledge.write_ops import read_note_text_with_version
    command = {"operation_id": "artifact.update", "request_id": "before-native-freeze", "arguments": {"body": "Not admitted.\n"},
        "active_context_ref": instance.selection["context"]["context_id"], "vault_generation": str(instance.selection["context"]["generation"]),
        "target_binding_id": instance.binding_id, "targets": [{"artifact_id": source["artifact_id"]}],
        "expected_version": read_note_text_with_version(instance.root / source["path"])[1]}
    refused = instance.client.post("/api/operations", json=command, headers=instance.headers)
    assert refused.status_code == 200 and refused.json()["status"] == "rejected", refused.text
    assert before == {str(path): file_hash(path) for path in instance.root.rglob("*.md")}
    assert instance.client.post("/api/operations/acceptance/admission", json={"approved": True}, headers=instance.headers).status_code == 422
    assert instance.client.post("/api/operations/acceptance/admission", json={}).status_code == 401
    frozen = instance.client.post("/api/operations/acceptance/admission", json={}, headers=instance.headers)
    assert frozen.status_code == 200, frozen.text
    assert frozen.json()["fixture_sha256"] == binding["fixture_sha256"]
    assert frozen.json()["selection"]["principal_id"] != frozen.json()["selection"]["instance_identity"]
    assert all("expected_version" in slot["intent"] for slot in frozen.json()["slots"])
    native = instance.runtime.registry.path.parent / CONTEXT_FILE
    original = read_private(native)
    assert original["fixture"]["files"] == instance.fixture_files
    from app.briefing.compose import briefing_note_path
    from app.briefing.trigger import _local_now
    from app.vault.manager import VaultContext
    briefing = briefing_note_path(
        vault_context=VaultContext(status="selected", active_vault_path=str(instance.root)),
        for_date=_local_now(None).date())
    assert original["fixture"]["files"][briefing.relative_to(instance.root).as_posix()] == file_hash(briefing)
    from app.vault.layout import load_layout
    layout = load_layout(instance.root).note_path
    assert original["fixture"]["files"][layout.relative_to(instance.root).as_posix()] == file_hash(layout)
    assert len(original["slots"]) == (15 if channel == "test" else 1)
    for mutate in (lambda x: x["identity"].update(channel="prod"),
                   lambda x: x["identity"]["sidecar"].update(source_sha="0" * 40),
                   lambda x: x.update(expires_at=0)):
        invalid = deepcopy(original)
        mutate(invalid)
        write_private(native, invalid)
        with pytest.raises(OperationsAcceptanceRefusal):
            load_context(instance.runtime.registry.path, required=True)
    write_private(native, original)
    # Actual assembled CLI parsing/runtime gate; no native/deploy port may be
    # reached for a foreign or incomplete candidate invocation.
    import tests.operations.live_operations_acceptance as caller
    monkeypatch.setattr(caller, "SDK_PYTHON", Path(sys.executable))
    from types import SimpleNamespace
    from app.ops.postgres_deploy import DeployJournal
    from app.ops.postgres_deploy_linux import LinuxConfig
    journal_directory = tmp_path / "native-journal"
    journal_directory.mkdir(mode=0o700)
    write_private(journal_directory / (channel + ".request.json"), {}, create=True)
    journal = DeployJournal(journal_directory, channel)
    monkeypatch.setattr(LinuxConfig, "load", lambda *args, **kwargs: SimpleNamespace(journal=journal, root=tmp_path))
    monkeypatch.setattr(caller, "EVIDENCE_DIRECTORY", tmp_path / "cli-results")
    class NoNetwork:
        def __init__(self, *args, **kwargs):
            pass
        def request(self, *args, **kwargs):
            pytest.fail("unqualified native operation reached Product network")
        def close(self):
            pass
    monkeypatch.setattr(caller.httpx, "Client", NoNetwork)
    if channel == "dev":
        b, rows, evidence = _receipt_fixture(tmp_path)
        now = time()
        proof = evidence / "receipt.json"
        write_private(proof, produce_receipt(b, rows, evidence, started_at=now - 5, finished_at=now), create=True)
        argv = [channel, OPERATION, "--test-receipt", str(proof)]
    else:
        argv = [channel, OPERATION]
    assert main(argv) == 1
    assert journal.read() is None
    capsys.readouterr()
    alias = tmp_path / "other-sdk-runtime" / "bin" / "python"
    alias.parent.mkdir(parents=True)
    alias.symlink_to(sys.executable)
    assert alias.resolve() == Path(sys.executable).resolve()
    monkeypatch.setattr(caller, "SDK_PYTHON", alias)
    monkeypatch.setattr(LinuxConfig, "load", lambda *args, **kwargs: pytest.fail("wrong SDK runtime reached native facts"))
    assert main(argv) == 1
    assert '"reason": "qualified_external_runtime_required"' in capsys.readouterr().out
    assert before == {str(path): file_hash(path) for path in instance.root.rglob("*.md")}
    # A declared synthetic label cannot create a missing native principal.
    from app.instance.runtime import local_operator_principal_path
    principal_path = local_operator_principal_path(instance.runtime.registry.path)
    principal_path.unlink()
    with pytest.raises(Exception):
        prepare_native_context(identity(channel), registry_path=instance.runtime.registry.path)
    assert not principal_path.exists()


def test_real_sdk_profiles_and_operation_parity_are_observed(tmp_path, monkeypatch):
    instance = host(tmp_path, monkeypatch)
    # Ambient proxies must not receive fixed loopback requests or carriers.
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    import os
    from app.operations.execution_kernel import JsonReceiptStore
    original_link = os.link
    publications = []
    def publish(source, destination, *args, **kwargs):
        role = {"operations-acceptance-moved.md": "move", "operations-acceptance-renamed.md": "rename"}.get(str(destination))
        if source == "original" and role:
            reservation = JsonReceiptStore(instance.runtime.registry.path.parent / "operation-receipts.json").lookup(
                "ygg.acceptance:" + OPERATION + ":" + role)
            assert reservation is not None, "native placement published before durable acceptance reservation"
            publications.append(role)
        return original_link(source, destination, *args, **kwargs)
    monkeypatch.setattr(os, "link", publish)
    with runtime_http(instance) as (url, calls, _):
        run = journey(instance, tmp_path / "original-sdk", url)
        run.profiles_and_operations()
        families = run.observations["qualified_families"]["proof"]["families"]
        assert set(families) == set(FAMILIES)
        assert all(row["status"] == "succeeded" for row in families.values() if row["support"] == "supported")
        assert all(row["status"] == "not_supported" and row["native_reason"] for row in families.values() if row["support"] != "supported")
        assert run.observations["operation_receipt_parity"]["proof"]["receipts"]
        assert sum(method == "POST" and path == "/api/operations" for method, path in calls) >= 4
        assert not any(path.startswith("/api/capture") for _, path in calls)
        for path in run.directory.iterdir():
            assert run.bearer.encode() not in path.read_bytes()
        # Installed distribution and SDK resources, independently of core
        # image contents or PYTHONPATH, are part of the observed binding.
        assert instance.identity["sidecar"]["distribution"] == "mimer-mcp-sidecar"
        assert instance.identity["sidecar"]["sdk_files"]
        assert instance.identity["sidecar"]["runtime"]["executable"] == sdk_python()
        assert publications == ["move", "rename"]


@pytest.mark.parametrize("case", ["missing", "unknown", "expired", "replaced", "wrong-principal", "wrong-instance",
    "read-only", "forged-delegation", "empty-override", "stale-override", "no-metadata", "forged-headers", "stale-cas"])
def test_authority_and_stale_cases_refuse_without_effects(tmp_path, monkeypatch, case):
    from app.api.routes.active_context_selection import get_selection_store
    from tests.operations.live_operations_acceptance import OperationsJourney
    from tests.operations._operations_acceptance_harness import LocalNative
    instance = host(tmp_path, monkeypatch)
    run = OperationsJourney(LocalNative(instance), tmp_path / "unused")
    run.binding = instance.binding
    command = run.command("edit")
    headers = dict(instance.headers)
    raw = headers["X-Active-Context-Session"]
    override = "private-unissued-override-marker"
    store = get_selection_store()
    record = store._records[raw]
    if case in {"missing", "no-metadata"}:
        headers = {}
    elif case == "unknown":
        headers["X-Active-Context-Session"] = "unissued-selection"
    elif case == "expired":
        store._records[raw] = replace(record, expires_at=0)
    elif case == "replaced":
        replaced = instance.client.put("/api/companion/active-context/selection", json={"vault_binding_ids": [instance.binding_id]}, headers=headers)
        assert replaced.status_code == 200
    elif case == "wrong-principal":
        store._records[raw] = replace(record, principal=replace(record.principal, principal_id="another-existing-principal"))
    elif case == "wrong-instance":
        store._records[raw] = replace(record, instance_identity="another-instance")
    elif case == "read-only":
        headers["X-Active-Context-Session"] = record.context_id
    elif case == "forged-delegation":
        command["arguments"]["delegation"] = {"authority_class": "governed_effect"}
    elif case in {"empty-override", "stale-override"}:
        headers["X-Active-Context-Override"] = "" if case == "empty-override" else override
    elif case == "forged-headers":
        headers = {"Principal": "forged", "X-API-Key": "forged", "X-Forwarded-For": "203.0.113.7"}
    else:
        command["expected_version"] = "stale"
    before = {str(path): file_hash(path) for path in instance.root.rglob("*.md")}
    response = instance.client.post("/api/operations", json=command, headers=headers)
    assert response.status_code in {401, 403, 422} or response.json()["status"] in {"rejected", "conflicted", "invalid"}, response.text
    assert before == {str(path): file_hash(path) for path in instance.root.rglob("*.md")}
    assert raw not in response.text and override not in response.text


def test_recovery_preserves_original_receipts_without_replay(tmp_path, monkeypatch):
    from app.api.routes.active_context_selection import get_selection_store
    instance = host(tmp_path, monkeypatch)
    with runtime_http(instance) as (url, calls, _):
        run = journey(instance, tmp_path / "recovery", url)
        run.profiles_and_operations()
        issued = instance.client.post("/api/companion/active-context/selection", json={"vault_binding_ids": [instance.binding_id]}).json()
        raw = issued["context_selection_id"]
        store = get_selection_store()
        store._records[raw] = replace(store._records[raw], expires_at=0)
        run.expired_bearer, run.expired_selection = raw, {"expires_at": 0, "observed_at": time()}
        run.recovery_and_refusals()
        assert run.observations["dropped_acknowledgement"]["proof"]["source_posts"] == 1
        assert run.observations["client_restart"]["proof"]["source_replays"] == 0
        assert run.observations["partial_batch"]["proof"]["partial"]["counts"]["completed"] == 1
        assert run.observations["backend_wsp_restart"]["status"] == "blocked"
        probe = native_probe(instance.runtime.registry.path)
        assert probe["source_store_index_links"]["status"] == "pending"
        assert probe["receipts"]
        for path in run.directory.iterdir():
            assert run.bearer.encode() not in path.read_bytes() and raw.encode() not in path.read_bytes()


def _receipt_fixture(tmp_path, channel="test", *, facts=None):
    """Receipt-validator data only, explicitly incapable of deployed PASS."""
    facts = deepcopy(facts) if facts is not None else identity(channel)
    facts["channel"] = channel
    binding = {"identity": facts, "principal_id": "existing-principal", "instance_identity": "existing-instance",
        "binding_id": "existing-binding", "fixture_sha256": "f" * 64, "native_context_sha256": "e" * 64,
        "source_inventory": {}, "selection": {"context_id": "ctx", "generation": 1}, "slots": []}
    observations = []
    directory = tmp_path / channel
    directory.mkdir(mode=0o700)
    trace = directory / "browser-actions.json"
    write_private(trace, {"kind": "receipt-validator-data"}, create=True)
    committed = {"status": "convergence_pending", "convergence": {"source_effect": "committed"}, "receipt": {"status": "committed"}}
    parity = {key: committed for key in ("sdk", "http", "native")}
    for name in inventory(channel):
        proof = {"checked": True, "status": "healthy", "validator_fixture": True}
        if name == "native_invariants":
            proof.update(consumed_slots=15 if channel == "test" else 1,
                         maximum_slots=15 if channel == "test" else 1, identity_unique=True, source_count=15)
        if name == "native_admission":
            proof["native"] = binding
        if name == "sdk_profiles":
            proof.update(v1=facts["sidecar"]["v1_contract"], v2={"items": ["validator-data"]}, tools=["validator-data"])
        if name == "qualified_families":
            proof["families"] = {kind: {"support": "supported", "status": "succeeded"}
                                 for kind in FAMILIES}
        if name == "operation_receipt_parity":
            proof["receipts"] = {kind: parity for kind in ("capture", "edit", "move", "rename", "archive", "restore")}
        if name == "authority_refusals":
            proof.update(cases={str(i): {"status": "refused"} for i in range(12)}, source_hashes={"seed": "a"}, after_source_hashes={"seed": "a"})
        if name == "hostile_collision_cas":
            proof.update(cases={kind: {} for kind in ("traversal", "absolute", "protected", "collision", "stale_cas")},
                         source_hashes={"seed": "a"}, after_source_hashes={"seed": "a"})
        if name == "concurrent_refusal":
            proof["outcomes"] = [committed, {"status": "conflicted"}]
        if name == "partial_batch":
            proof.update(partial={"counts": {"completed": 1}, "items": []}, retained={"items": []}, cancelled={"items": []},
                         successful_batch={"counts": {"completed": 2}})
        if name in {"dropped_acknowledgement", "client_restart"}:
            proof.update(source_posts=1, source_replays=0, pre_sha256="a", post_sha256="b", original=committed)
        if name == "projection_lag":
            proof["lagged_count"] = 1
        if name == "backend_wsp_restart":
            proof["separate_native_authority"] = True
        if name.startswith("browser_"):
            proof["observed"] = ["receipt-validator-data"]
        path = directory / (name + ".json")
        write_private(path, proof, create=True)
        artifacts = {path.name: file_hash(path)}
        if name.startswith("browser_"):
            artifacts[trace.name] = file_hash(trace)
        observations.append({"id": name, "status": "passed", "producer": "original_observer", "proof": proof,
            "binding_sha256": digest(binding), "artifacts": artifacts, "observed_at": time()})
    return binding, observations, directory


def test_acceptance_receipt_binds_complete_observed_inventory(tmp_path, monkeypatch):
    binding, observations, directory = _receipt_fixture(tmp_path)
    now = time()
    receipt = produce_receipt(binding, observations, directory, started_at=now - 5, finished_at=now)
    assert receipt["status"] == "PREMERGE_PASS" and receipt["execution_kind"] == "premerge"
    for status in ("missing", "blocked", "failed", "skipped", "xfailed", "excluded"):
        rows = deepcopy(observations)
        if status == "missing":
            rows.pop()
        else:
            rows[2]["status"] = status
        with pytest.raises(OperationsAcceptanceRefusal):
            produce_receipt(binding, rows, directory, started_at=now - 5, finished_at=now)
    for key in ("source_sha", "image_digest", "channel", "resource_tree", "native_receipt_sha256", "sidecar"):
        foreign = deepcopy(binding)
        foreign["identity"][key] = "foreign"
        with pytest.raises(OperationsAcceptanceRefusal):
            produce_receipt(foreign, observations, directory, started_at=now - 5, finished_at=now)
    relabeled = deepcopy(binding)
    relabeled["identity"]["execution_kind"] = "deployed"
    with pytest.raises(OperationsAcceptanceRefusal):
        produce_receipt(relabeled, observations, directory, started_at=now - 5, finished_at=now)
    artifact = directory / next(iter(observations[0]["artifacts"]))
    artifact.write_text("replacement success report")
    with pytest.raises(OperationsAcceptanceRefusal):
        produce_receipt(binding, observations, directory, started_at=now - 5, finished_at=now)


@pytest.mark.parametrize("channel", ["test", "dev"])
def test_qualified_channel_commands_cover_test_and_dev(tmp_path, monkeypatch, channel):
    # Full public orchestration over original Product outcomes. Native host
    # process/network/output ports alone use a canonical temporary fixture.
    import tests.operations.live_operations_acceptance as caller
    from tests.operations._operations_acceptance_harness import NativeFixturePorts
    from app.api.routes.active_context_selection import get_selection_store
    instance = host(tmp_path, monkeypatch, channel=channel, freeze=False, prepare=False)
    ports = NativeFixturePorts(instance, tmp_path, monkeypatch)
    native = caller.NativeChannel(channel, OPERATION)
    original = native.admit()
    instance.identity = original["identity"]
    clock = [time()]
    monkeypatch.setattr(caller, "time", lambda: clock[0])
    monkeypatch.setattr(caller, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(get_selection_store(), "_clock", lambda: clock[0])
    prior = None
    if channel == "dev":
        binding, rows, evidence = _receipt_fixture(tmp_path, facts=instance.identity)
        # Both temporary channels share the same actual installed artifacts.
        now = time()
        prior = evidence / "receipt.json"
        write_private(prior, produce_receipt(binding, rows, evidence, started_at=now - 5, finished_at=now), create=True)
    with runtime_http(instance) as (url, calls, _):
        import httpx
        # No browser replacement: TEST stops with an honest partial report
        # when browser execution is absent in this non-browser lane.
        run = caller.OperationsJourney(native, tmp_path / "assembled",
            client=httpx.Client(base_url=url, timeout=60), browser=lambda _: None)
        run.api_url = url
        result = run.run(test_receipt_path=prior)
        assert result["status"] == "BLOCKED"
        assert result["binding"]["identity"]["channel"] == channel
        assert result["required_scenarios"] == list(inventory(channel))
        assert run.observations["sdk_profiles"]["status"] == "passed"
        assert sum(method == "POST" and path == "/api/operations" for method, path in calls) >= 1
        if channel == "test":
            assert run.observations["backend_wsp_restart"]["status"] == "blocked"
            assert run.observations["browser_discovery"]["status"] == "blocked"
        else:
            assert run.observations["dev_operation_receipt"]["proof"]["sdk"] == run.observations["dev_operation_receipt"]["proof"]["native"]
        # A separately owned temporary native successor completes before the
        # preceding observation. Both the old object and a newly constructed
        # public runner must recover the exact original without prepare/replay.
        source_hashes = {str(path): file_hash(path) for path in instance.root.rglob("*.md")}
        native_context = file_hash(instance.runtime.registry.path.parent / CONTEXT_FILE)
        observed_calls, prepares = len(calls), ports.prepares
        successor = ports.successor()
        assert native.observe()["binding"] == run.binding
        assert native.observe_restart()["restart_binding"]["operation_id"] == successor
        fresh = caller.NativeChannel(channel, OPERATION)
        recovered = caller.OperationsJourney(fresh, run.directory, client=httpx.Client(base_url=url, timeout=60)).run(test_receipt_path=prior)
        assert recovered == result and fresh.restart_binding["operation_id"] == successor
        assert ports.prepares == prepares and len(calls) == observed_calls
        assert native_context == file_hash(instance.runtime.registry.path.parent / CONTEXT_FILE)
        assert source_hashes == {str(path): file_hash(path) for path in instance.root.rglob("*.md")}
        for attribute, invalid in (("api_command", ["python", "-c", "import time;time.sleep(3600)"]),
                                   ("api_workdir", "/tmp"), ("ui_workdir", "/app")):
            original_value = getattr(ports, attribute)
            setattr(ports, attribute, invalid)
            with pytest.raises(OperationsAcceptanceRefusal, match="actual_native_program_or_image_mismatch"):
                native.observe_restart()
            with pytest.raises(OperationsAcceptanceRefusal, match="actual_native_program_or_image_mismatch"):
                caller.NativeChannel(channel, OPERATION).admit()
            setattr(ports, attribute, original_value)
            assert ports.prepares == prepares and len(calls) == observed_calls
        from uuid import uuid4
        ports.commit(str(uuid4()))
        with pytest.raises(OperationsAcceptanceRefusal, match="current_committed_full_native_operation_required"):
            caller.NativeChannel(channel, OPERATION).admit()
        assert ports.prepares == prepares and len(calls) == observed_calls
