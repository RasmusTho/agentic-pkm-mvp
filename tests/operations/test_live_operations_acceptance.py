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


@pytest.mark.parametrize("channel", ["test", "dev"])
def test_channel_entrypoints_enforce_native_operations_admission(tmp_path, monkeypatch, channel):
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


def _receipt_fixture(tmp_path, channel="test"):
    """Receipt-validator data only, explicitly incapable of deployed PASS."""
    facts = identity(channel)
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
    from tests.operations._operations_acceptance_harness import LocalNative
    from app.api.routes.active_context_selection import get_selection_store
    instance = host(tmp_path, monkeypatch, channel=channel, freeze=False)
    clock = [time()]
    monkeypatch.setattr(caller, "time", lambda: clock[0])
    monkeypatch.setattr(caller, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(get_selection_store(), "_clock", lambda: clock[0])
    prior = None
    if channel == "dev":
        binding, rows, evidence = _receipt_fixture(tmp_path)
        # Both temporary channels share the same actual installed artifacts.
        now = time()
        prior = evidence / "receipt.json"
        write_private(prior, produce_receipt(binding, rows, evidence, started_at=now - 5, finished_at=now), create=True)
    with runtime_http(instance) as (url, calls, _):
        import httpx
        # No browser replacement: TEST stops with an honest partial report
        # when browser execution is absent in this non-browser lane.
        run = caller.OperationsJourney(LocalNative(instance), tmp_path / "assembled",
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
