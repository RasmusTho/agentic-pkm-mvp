"""Real operator CLI → native owners → baked preparation → real API admission.

Only physical Docker/volume ports and the test clock are substituted. The older
operations harness's manual source assembly/RAW timestamp edits are never used.
These isolated source tests are not live native acceptance evidence.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import io
import json
import secrets
import subprocess
import sys
from types import SimpleNamespace

from click.testing import CliRunner
from fastapi.testclient import TestClient
import pytest

from app.api.app import app
from app.cli import cli
from app.instance.local_operator_principal import AuthPosture
from app.instance.runtime import open_default_vault_service, open_local_operator_principal_store
from app.operations.execution_kernel import JsonReceiptStore
from app.ops import native_operations_fixture as preparation
from app.ops.native_operations_acceptance_runner import NativeChannel
from app.ops.operations_acceptance import CONTEXT_FILE, PROFILE, OperationsAcceptanceRefusal, file_hash
from tests._mvr_default_vault_harness import new_runtime, activate
from tests._mvr03_principal_harness import run_principal_cutover
from tests.api._vault_test_helpers import bind_initialized_vault
from tests.operations._operations_acceptance_harness import NativeFixturePorts, OPERATION, ROOT

pytestmark = pytest.mark.usefixtures("product_model_access_gateway")


def environment(tmp_path, monkeypatch, *, channel="dev"):
    runtime = new_runtime(tmp_path, channel=channel)
    root = tmp_path / "synthetic-vault"
    root.mkdir()
    manager = bind_initialized_vault(monkeypatch, root, store_dir=tmp_path, channel=channel)
    registration = runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    activate(runtime, registration, tmp_path)
    run_principal_cutover(runtime, channel_id=channel, posture=AuthPosture(
        configured_credentials=0, credential=None, loopback_listener_proven=True, companion_proxy_configured=False))
    runtime.complete_initialization(registration.vault_binding_id, vault_id=manager.context.active_vault_id,
                                    local_instance_id=registration.local_instance_id)
    open_default_vault_service(runtime.registry.path).set(registration.vault_binding_id)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.registry.path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "false")
    facts = SimpleNamespace(identity={"channel": channel}, runtime=runtime)
    native = NativeFixturePorts(facts, tmp_path, monkeypatch)
    original_port = native.runner.command
    source_hash = preparation.file_hash
    # Physical /app mount translation only; hashes still read actual bytes.
    monkeypatch.setattr(preparation, "file_hash", lambda path, **kwargs:
        source_hash(ROOT / path.relative_to("/app"), **kwargs) if path.is_relative_to("/app") else source_hash(path, **kwargs))
    monkeypatch.setenv("VCS_REF", native.sha)
    calls = []
    def docker(argv, *, payload=None, cwd=None):
        if "app.ops.native_operations_fixture" not in argv:
            return original_port(argv, payload=payload, cwd=cwd)
        assert argv == ["docker", "exec", "-i", native.api_id, "python", "-m", "app.ops.native_operations_fixture"]
        calls.append(payload)
        output = io.StringIO()
        with monkeypatch.context() as patch:
            patch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
            with redirect_stdout(output):
                code = preparation.main()
        if code:
            raise OperationsAcceptanceRefusal("native_preparation_port_refused")
        return output.getvalue()
    monkeypatch.setattr(native.runner, "command", docker)
    principal = open_local_operator_principal_store(runtime.registry.path).require()
    result = SimpleNamespace(runtime=runtime, root=root, binding_id=registration.vault_binding_id,
        principal_id=principal.local_operator_role_id, instance_identity=runtime.registry.load().app_install_id,
        native=native, calls=calls, manager=manager)
    if channel == "test":
        archive_authority(result, tmp_path, monkeypatch)
    else:
        monkeypatch.delenv("PKM_CONFIG_ROOT", raising=False)
    return result


def archive_authority(host, tmp_path, monkeypatch):
    from app.heimdal import consent_ledger, local_archive, raw_store, raw_liveness, raw_read_gate
    from app.heimdal.settings_notes import write_settings_note, SettingsNote, SETTINGS
    from app.ops import heimdal_cold_volume as volume
    raw_store.reset_memory_raw_store()
    raw_liveness.reset_memory_deletion_receipts()
    raw_read_gate.reset_memory_raw_read_receipts()
    consent_ledger.reset_memory_consent_ledger()
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", secrets.token_bytes(32).hex())
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", local_archive.OPERATION_RESTORE_SERVICE)
    config = tmp_path / "archive-config"
    config.mkdir()
    monkeypatch.setenv("PKM_CONFIG_ROOT", str(config))
    cold = tmp_path / "cold-volume"
    cold.mkdir()
    metadata = SimpleNamespace(mountpoint=cold, archive_id="synthetic-operations", channel="test")
    def ready(*args, **kwargs):
        return volume._issue_archive_volume_ready(metadata.archive_id, cold, _issuer=volume._ARCHIVE_VOLUME_READY_ISSUER)
    for module in (volume, local_archive):
        monkeypatch.setattr(module, "load_channel_archive_metadata", lambda **kwargs: metadata)
        monkeypatch.setattr(module, "require_archive_volume_ready", ready)
    write_settings_note(host.root, SettingsNote(spec=SETTINGS, values={"retention_window_days": 30}))
    host.grant = consent_ledger.grant_consent(grant_ref=PROFILE + ":" + OPERATION, basis="self_record",
        scope=PROFILE + ":" + OPERATION, granted_by=host.principal_id,
        payload={"instance_identity": host.instance_identity, "vault_binding_id": host.binding_id})
    host.clock = SimpleNamespace(now=datetime.now(timezone.utc))
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return host.clock.now.astimezone(tz) if tz else host.clock.now.replace(tzinfo=None)
    # A normal insert observes this clock. Later eligibility observes its real
    # original timestamp against a later test time; no record/backend is edited.
    monkeypatch.setattr(raw_store, "datetime", Clock)
    monkeypatch.setattr(preparation, "datetime", Clock)


def invoke(host, *, stage=False, **overrides):
    values = {"binding-id": host.binding_id, "principal-id": host.principal_id,
              "instance-id": host.instance_identity, **overrides}
    argv = ["prepare-fixture", host.native.channel, OPERATION]
    for name, value in values.items():
        argv += ["--" + name, value]
    argv += ["--confirm-synthetic-setup"]
    if stage:
        argv += ["--stage-raw"]
    output = io.StringIO()
    with redirect_stdout(output):
        code = host.native.runner.main(argv)
    return SimpleNamespace(exit_code=code, output=output.getvalue())


def prepared(tmp_path, monkeypatch, channel):
    host = environment(tmp_path, monkeypatch, channel=channel)
    if channel == "test":
        staged = invoke(host, stage=True)
        assert staged.exit_code == 0, staged.output
        assert json.loads(staged.output)["status"] == "convergence_pending"
        host.clock.now += timedelta(days=8)
    result = invoke(host)
    assert result.exit_code == 0, result.output
    host.preparation = json.loads(result.output)
    return host


@pytest.mark.parametrize("channel", ["test", "dev"])
def test_operator_preparation_uses_original_operation_and_existing_authority(tmp_path, monkeypatch, channel):
    from app.api.native_operations_acceptance import source_templates
    from app.vault.paths import get_vault_capture_note_rel
    host = prepared(tmp_path, monkeypatch, channel)
    assert host.preparation["status"] == "succeeded"
    assert host.calls[-1]["identity"]["operation_id"] == OPERATION
    assert host.calls[-1]["identity"]["native_receipt_sha256"]
    snapshot = host.runtime.registry.load()
    registration = snapshot.registrations[host.binding_id]
    assert registration.extensions[PROFILE] == {"operation_id": OPERATION}
    assert snapshot.last_active_vault_ref == registration.ref
    assert snapshot.app_install_id == host.instance_identity
    assert open_local_operator_principal_store(host.runtime.registry.path).require().local_operator_role_id == host.principal_id
    sources = source_templates(OPERATION)
    sources["capture"]["path"] = get_vault_capture_note_rel(host.root)
    for source in sources.values():
        assert file_hash(host.root / source["path"]) == source["seed_sha256"]
    receipts = [item["payload"] for item in host.preparation["items"] if "authority_receipt" in item["payload"]]
    assert len(receipts) == len(sources)
    assert all(row["authority_receipt"]["actor"] == host.principal_id for row in receipts)
    assert not (host.runtime.registry.path.parent / CONTEXT_FILE).exists()
    # This ordinary producer has no explicit bindingRevision extension. Its
    # real owner transitions must complete without bypassing stale protection.
    assert "bindingRevision" not in registration.extensions


@pytest.mark.parametrize("channel", ["test", "dev"])
def test_prepared_fixture_qualifies_real_native_operations_admission(tmp_path, monkeypatch, channel):
    from app.api.routes import active_context_selection
    from app.ops.operations_acceptance import load_context
    host = prepared(tmp_path, monkeypatch, channel)
    native = NativeChannel(channel, OPERATION)
    result = native.admit()
    assert result["binding_id"] == host.binding_id
    assert result["principal_id"] == host.principal_id
    active_context_selection.reset_selection_store_for_tests()
    with TestClient(app) as client:
        selected = client.post("/api/companion/active-context/selection", json={"vault_binding_ids": [host.binding_id]})
        assert selected.status_code == 201, selected.text
        frozen = client.post("/api/operations/acceptance/admission", json={},
            headers={"X-Active-Context-Session": selected.json()["context_selection_id"]})
        assert frozen.status_code == 200, frozen.text
    context = load_context(host.runtime.registry.path, required=True)
    assert len(context["slots"]) == (15 if channel == "test" else 1)
    assert bool(context["fixture"]["raw_source"]) == (channel == "test")


@pytest.mark.parametrize("fault", ["principal", "instance", "binding", "intent", "candidate", "operation",
    "foreign_source", "symlink", "profile", "consent", "archive", "reader", "key", "retention", "too_young",
    "read_only_role", "writes_disabled"])
def test_preparation_refuses_unqualified_inputs_without_dependent_effects(tmp_path, monkeypatch, fault):
    from app.heimdal import consent_ledger, raw_store
    from app.heimdal.settings_notes import write_settings_note, SettingsNote, SETTINGS
    from app.instance.runtime import local_operator_storage_capability
    from app.ops import heimdal_cold_volume as volume
    host = environment(tmp_path, monkeypatch, channel="test")
    if fault == "principal":
        result = invoke(host, stage=True, **{"principal-id": "unissued"})
    elif fault == "instance":
        result = invoke(host, stage=True, **{"instance-id": "unissued"})
    elif fault == "binding":
        result = invoke(host, stage=True, **{"binding-id": "unissued"})
    elif fault == "intent":
        result = CliRunner().invoke(cli, ["ops", "prepare-operations-fixture", "test", OPERATION,
            "--binding-id", host.binding_id, "--principal-id", host.principal_id, "--instance-id", host.instance_identity])
    else:
        if fault == "candidate":
            host.native.api_command = ["python", "foreign.py"]
        elif fault == "operation":
            host.native.journal.write(OPERATION, "failed")
        elif fault == "foreign_source":
            (host.root / "personal.md").write_text("Preserve this unrelated user note.")
        elif fault == "symlink":
            (host.root / "foreign").symlink_to(tmp_path)
        elif fault == "profile":
            row = host.runtime.registry.lookup(host.binding_id)
            host.runtime.registry.update_registration(replace(row, extensions={**row.extensions, PROFILE: {"operation_id": "foreign"}}),
                _capability=local_operator_storage_capability())
        elif fault == "consent":
            consent_ledger.revoke_consent(grant_ref=host.grant.grant_ref, revoked_by=host.principal_id)
        elif fault == "archive":
            def unavailable(*args, **kwargs):
                raise RuntimeError("unavailable physical volume")
            monkeypatch.setattr(volume, "require_archive_volume_ready", unavailable)
        elif fault == "reader":
            monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", "foreign-reader")
        elif fault == "key":
            monkeypatch.delenv("HEIMDAL_RAW_STORE_KEY")
        elif fault == "retention":
            write_settings_note(host.root, SettingsNote(spec=SETTINGS, values={"retention_window_days": 7}))
        elif fault == "too_young":
            assert invoke(host, stage=True).exit_code == 0
        elif fault in {"read_only_role", "writes_disabled"}:
            path = host.root / "settings/local.md"
            settings = host.manager.markdown_store
            doc = settings.read(path)
            values = {**doc.frontmatter, "machineRole": "readOnlySatellite" if fault == "read_only_role" else "testNode",
                      "allowWritesToVault": fault == "read_only_role"}
            settings.write_frontmatter(path, values, body=doc.body)
        before = {p.relative_to(host.root).as_posix(): p.read_bytes() for p in host.root.rglob("*") if p.is_file()}
        result = invoke(host, stage=fault != "too_young")
        after = {p.relative_to(host.root).as_posix(): p.read_bytes() for p in host.root.rglob("*") if p.is_file()}
        assert before == after
    assert result.exit_code != 0
    assert not (host.root / "Notes").exists()
    if fault != "too_young":
        assert raw_store.all_raw_records() == []


def test_partial_preparation_preserves_original_receipts_and_no_replay(tmp_path, monkeypatch):
    import app.knowledge.write_ops as writes
    host = environment(tmp_path, monkeypatch)
    original = writes.write_note_relative
    calls = []
    def lost_ack(*args, **kwargs):
        receipt = original(*args, **kwargs)
        calls.append(receipt)
        if len(calls) == 2:
            raise OSError("physical publication acknowledgement lost")
        return receipt
    monkeypatch.setattr(writes, "write_note_relative", lost_ack)
    assert invoke(host).exit_code != 0
    store = JsonReceiptStore(host.runtime.registry.path.parent / "operation-receipts.json")
    original_receipt = store.lookup(preparation.PREPARATION_REQUEST).outcome.to_dict()
    assert original_receipt["status"] == "recovery_required"
    assert len(original_receipt["items"]) == 1
    files = {str(p): p.read_bytes() for p in host.root.rglob("*.md")}
    assert invoke(host).exit_code != 0
    assert len(calls) == 2
    assert original_receipt == store.lookup(preparation.PREPARATION_REQUEST).outcome.to_dict()
    assert files == {str(p): p.read_bytes() for p in host.root.rglob("*.md")}


def test_preparation_does_not_replenish_acceptance_authority(tmp_path, monkeypatch):
    from app.api.routes import active_context_selection
    host = prepared(tmp_path, monkeypatch, "dev")
    NativeChannel("dev", OPERATION).admit()
    active_context_selection.reset_selection_store_for_tests()
    client = TestClient(app)
    selected = client.post("/api/companion/active-context/selection", json={"vault_binding_ids": [host.binding_id]})
    assert selected.status_code == 201
    headers = {"X-Active-Context-Session": selected.json()["context_selection_id"]}
    frozen = client.post("/api/operations/acceptance/admission", json={}, headers=headers)
    assert frozen.status_code == 200, frozen.text
    binding = frozen.json()
    selection = binding["selection"]
    command = {**binding["slots"][0]["intent"], "request_id": "acceptance:" + OPERATION + ":dev-smoke",
        "active_context_ref": selection["context_id"], "vault_generation": str(selection["generation"]),
        "target_binding_id": host.binding_id}
    applied = client.post("/api/operations", json=command, headers=headers)
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] in {"succeeded", "convergence_pending"}
    store = JsonReceiptStore(host.runtime.registry.path.parent / "operation-receipts.json")
    consumed = "ygg.acceptance:" + OPERATION + ":dev-smoke"
    record = store.lookup(consumed).outcome.to_dict()
    context_file = host.runtime.registry.path.parent / CONTEXT_FILE
    original_context = context_file.read_bytes()
    assert invoke(host).exit_code == 0  # Original receipt observation only.
    original_files = {str(p): p.read_bytes() for p in host.root.rglob("*.md")}
    changed = dict(host.calls[-1])
    changed["identity"] = {**changed["identity"], "operation_id": "65600000-0000-4000-8000-000000000002"}
    with pytest.raises(OperationsAcceptanceRefusal, match="original_preparation_binding_changed"):
        preparation.prepare_fixture(changed, registry_path=host.runtime.registry.path)
    assert store.lookup(consumed).outcome.to_dict() == record
    assert original_files == {str(p): p.read_bytes() for p in host.root.rglob("*.md")}
    fresh = client.post("/api/companion/active-context/selection", json={"vault_binding_ids": [host.binding_id]})
    assert fresh.status_code == 201
    refused = client.post("/api/operations/acceptance/admission", json={},
        headers={"X-Active-Context-Session": fresh.json()["context_selection_id"]})
    assert refused.status_code != 200
    assert store.lookup(consumed).outcome.to_dict() == record
    assert context_file.read_bytes() == original_context
    client.close()


def test_runner_and_api_qualification_never_provision_missing_fixture(tmp_path, monkeypatch):
    from app.api.routes import active_context_selection
    host = environment(tmp_path, monkeypatch)
    before = {str(p): p.read_bytes() for p in host.root.rglob("*.md")}
    with pytest.raises(OperationsAcceptanceRefusal, match="canonical_isolated_fixture_missing"):
        NativeChannel("dev", OPERATION).admit()
    active_context_selection.reset_selection_store_for_tests()
    with TestClient(app) as client:
        selected = client.post("/api/companion/active-context/selection", json={"vault_binding_ids": [host.binding_id]})
        assert selected.status_code == 201
        response = client.post("/api/operations/acceptance/admission", json={},
            headers={"X-Active-Context-Session": selected.json()["context_selection_id"]})
        assert response.status_code == 409
    assert not host.calls
    assert before == {str(p): p.read_bytes() for p in host.root.rglob("*.md")}


def test_raw_staging_retains_real_time_receipt_and_waits_for_owner_eligibility(tmp_path, monkeypatch):
    from app.api.native_operations_acceptance import raw_fixture_bytes
    from app.heimdal import raw_store, local_archive
    host = environment(tmp_path, monkeypatch, channel="test")
    staged = invoke(host, stage=True)
    assert staged.exit_code == 0, staged.output
    original = json.loads(staged.output)
    record = raw_store.get_raw_record_by_content_identity(raw_store.compute_raw_content_identity(raw_fixture_bytes(OPERATION)))
    assert record.ingested_at == host.clock.now
    assert local_archive.archive_eligible(record, now=host.clock.now, retention_window_days=30) is False
    assert json.loads(invoke(host, stage=True).output) == original
    assert len(raw_store.all_raw_records()) == 1
    assert invoke(host).exit_code != 0
    host.clock.now += timedelta(days=8)
    assert local_archive.archive_eligible(record, now=host.clock.now, retention_window_days=30)
    assert invoke(host).exit_code == 0
    assert raw_store.get_raw_record_by_content_identity(record.content_identity).ingested_at == record.ingested_at


def test_create_once_competing_writer_is_preserved_and_never_acknowledged_applied(tmp_path, monkeypatch):
    import app.knowledge.write_ops as writes
    from app.api.native_operations_acceptance import source_templates
    host = environment(tmp_path, monkeypatch)
    original = writes.write_note_relative
    winner = source_templates(OPERATION)["read"]
    foreign = "A concurrent normal writer owns this note.\n"
    calls = []
    def competing_writer(path, content, **kwargs):
        calls.append(path)
        # Inject the real competing source producer after preparation's own
        # inventory preflight, before its real create-once writer is invoked.
        original(path, foreign, **kwargs)
        return original(path, content, **kwargs)
    monkeypatch.setattr(writes, "write_note_relative", competing_writer)
    assert invoke(host).exit_code != 0
    assert (host.root / winner["path"]).read_text() == foreign
    store = JsonReceiptStore(host.runtime.registry.path.parent / "operation-receipts.json")
    receipt = store.lookup(preparation.PREPARATION_REQUEST).outcome.to_dict()
    assert receipt["status"] == "recovery_required"
    assert receipt["items"][0]["status"] == "conflicted"
    assert receipt["items"][0]["payload"]["mutation_receipt"]["outcome"] == "already_exists"
    assert receipt["items"][0]["payload"]["authority_receipt"]["outcome"] == "failed"
    assert PROFILE not in host.runtime.registry.lookup(host.binding_id).extensions
    assert invoke(host).exit_code != 0
    assert calls == [winner["path"]]
    assert store.lookup(preparation.PREPARATION_REQUEST).outcome.to_dict() == receipt


def test_raw_stage_lost_ack_retains_original_unknown_and_never_inserts_again(tmp_path, monkeypatch):
    from app.heimdal import raw_store
    host = environment(tmp_path, monkeypatch, channel="test")
    original = raw_store.insert_raw_record
    calls = []
    def lost_ack(**kwargs):
        record, created = original(**kwargs)
        calls.append(record.id)
        assert created
        raise OSError("normal insert committed but acknowledgement was lost")
    monkeypatch.setattr(raw_store, "insert_raw_record", lost_ack)
    assert invoke(host, stage=True).exit_code != 0
    store = JsonReceiptStore(host.runtime.registry.path.parent / "operation-receipts.json")
    pending = store.lookup(preparation.RAW_STAGE_REQUEST).outcome.to_dict()
    assert pending["convergence"]["source_effect"] == "unknown"
    assert invoke(host, stage=True).exit_code != 0
    host.clock.now += timedelta(days=8)
    assert invoke(host).exit_code != 0
    assert len(calls) == len(raw_store.all_raw_records()) == 1
    assert store.lookup(preparation.RAW_STAGE_REQUEST).outcome.to_dict() == pending
    assert not (host.root / "Notes").exists()


def test_native_command_imports_without_full_product_cli_dependencies():
    script = '''
import builtins,runpy,sys
original=builtins.__import__
def restricted(name,*args,**kwargs):
 if name.split('.')[0] in {'click','httpx','fastapi','watchfiles'}:
  raise ImportError('full Product CLI dependency is unavailable in native runtime')
 return original(name,*args,**kwargs)
builtins.__import__=restricted
sys.argv=['app.ops.native_operations_acceptance_runner','prepare-fixture','--help']
runpy.run_module('app.ops.native_operations_acceptance_runner',run_name='__main__')
'''
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "--confirm-synthetic-setup" in result.stdout and "--stage-raw" in result.stdout
    alias = CliRunner().invoke(cli, ["ops", "prepare-operations-fixture", "--help"])
    assert alias.exit_code == 0 and "--confirm-synthetic-setup" in alias.output


def test_create_only_briefing_preserves_a_competing_normal_writer(tmp_path, monkeypatch):
    from app.briefing import compose, trigger
    from app.knowledge.write_ops import write_note_relative
    host = environment(tmp_path, monkeypatch)
    monkeypatch.setattr(trigger, "BRIEFING_ENABLED", True)
    original = compose.compose_briefing
    target = compose.briefing_note_path(vault_context=host.manager.context, for_date=trigger._local_now(None).date())
    foreign = "A concurrent normal writer owns today's target.\n"
    calls = []
    def competing_writer(**kwargs):
        calls.append(True)
        write_note_relative(target.relative_to(host.root).as_posix(), foreign, vault_root=host.root, create_once=True)
        return original(**kwargs)
    monkeypatch.setattr(compose, "compose_briefing", competing_writer)
    assert invoke(host).exit_code != 0
    assert target.read_text() == foreign
    store = JsonReceiptStore(host.runtime.registry.path.parent / "operation-receipts.json")
    pending = store.lookup(preparation.PREPARATION_REQUEST).outcome.to_dict()
    assert pending["status"] == "recovery_required"
    assert pending["items"][-1]["status"] == "conflicted"
    assert pending["items"][-1]["payload"]["mutation_receipt"]["outcome"] == "already_exists"
    assert PROFILE not in host.runtime.registry.lookup(host.binding_id).extensions
    assert invoke(host).exit_code != 0
    assert target.read_text() == foreign and len(calls) == 1
    assert pending == store.lookup(preparation.PREPARATION_REQUEST).outcome.to_dict()


@pytest.mark.parametrize("drift", ["native_operation", "running_candidate", "principal_authority", "binding_authority"])
def test_raw_maturation_never_rebinds_original_candidate_or_authority(tmp_path, monkeypatch, drift):
    from app.instance.runtime import local_operator_storage_capability
    from app.heimdal import raw_store
    host = environment(tmp_path, monkeypatch, channel="test")
    assert invoke(host, stage=True).exit_code == 0
    store = JsonReceiptStore(host.runtime.registry.path.parent / "operation-receipts.json")
    original = store.lookup(preparation.RAW_STAGE_REQUEST).outcome.to_dict()
    host.clock.now += timedelta(days=8)
    if drift == "native_operation":
        host.native.commit("65600000-0000-4000-8000-000000000099")
    elif drift == "running_candidate":
        # The native request stays original; actual Docker's running SHA drifts.
        host.native.sha = "9" * 40
    elif drift == "principal_authority":
        # Normal owner advances the same role's auth record; no new principal
        # or credential is created, and the old staging authority is not rebased.
        open_local_operator_principal_store(host.runtime.registry.path).rotate_credential(
            credential=None, _capability=local_operator_storage_capability())
    else:
        # Ordinary remember advances the fallback binding revision. The existing
        # authority owner determines that change; setup cannot reset it.
        from app.vault.manager import VaultManager
        VaultManager().select_vault(host.root, remember=True)
    assert invoke(host).exit_code != 0
    assert store.lookup(preparation.RAW_STAGE_REQUEST).outcome.to_dict() == original
    assert store.lookup(preparation.PREPARATION_REQUEST) is None
    assert len(raw_store.all_raw_records()) == 1
    assert not (host.root / "Notes").exists()


def test_preparation_never_heals_identity_removed_during_validation(tmp_path, monkeypatch):
    from app.vault.manager import VaultManager
    host = environment(tmp_path, monkeypatch)
    original = VaultManager.validate_vault
    changed = []
    def identity_removed(self, root, **kwargs):
        assert kwargs == {"heal_identity": False}
        path = root / "settings/vault.md"
        doc = self.markdown_store.read(path)
        frontmatter = dict(doc.frontmatter)
        frontmatter.pop("vaultId")
        self.markdown_store.write_frontmatter(path, frontmatter, body=doc.body)
        changed.append(path.read_bytes())
        return original(self, root, **kwargs)
    monkeypatch.setattr(VaultManager, "validate_vault", identity_removed)
    assert invoke(host).exit_code != 0
    assert (host.root / "settings/vault.md").read_bytes() == changed[0]
    assert not (host.root / "Notes").exists()
    assert PROFILE not in host.runtime.registry.lookup(host.binding_id).extensions


def test_preparation_rechecks_local_permission_at_canonical_source_seam(tmp_path, monkeypatch):
    from app.governance.governed_write import GovernedWriteAdapter
    host = environment(tmp_path, monkeypatch)
    original = GovernedWriteAdapter.validate_decision_token
    def permission_revoked(self, **kwargs):
        result = original(self, **kwargs)
        path = host.root / "settings/local.md"
        settings = host.manager.markdown_store
        doc = settings.read(path)
        settings.write_frontmatter(path, {**doc.frontmatter, "allowWritesToVault": False}, body=doc.body)
        return result
    monkeypatch.setattr(GovernedWriteAdapter, "validate_decision_token", permission_revoked)
    assert invoke(host).exit_code != 0
    assert not list((host.root / "Notes").glob("*.md"))
    store = JsonReceiptStore(host.runtime.registry.path.parent / "operation-receipts.json")
    pending = store.lookup(preparation.PREPARATION_REQUEST).outcome.to_dict()
    assert pending["status"] == "recovery_required" and pending["items"] == []
    assert PROFILE not in host.runtime.registry.lookup(host.binding_id).extensions


def test_raw_staging_rechecks_local_permission_before_normal_insert(tmp_path, monkeypatch):
    from app.heimdal import raw_store
    host = environment(tmp_path, monkeypatch, channel="test")
    original = raw_store.encrypt_raw_bytes
    def permission_revoked(*args, **kwargs):
        encrypted = original(*args, **kwargs)
        path = host.root / "settings/local.md"
        settings = host.manager.markdown_store
        doc = settings.read(path)
        settings.write_frontmatter(path, {**doc.frontmatter, "allowWritesToVault": False}, body=doc.body)
        return encrypted
    monkeypatch.setattr(raw_store, "encrypt_raw_bytes", permission_revoked)
    assert invoke(host, stage=True).exit_code != 0
    assert raw_store.all_raw_records() == []
    store = JsonReceiptStore(host.runtime.registry.path.parent / "operation-receipts.json")
    assert store.lookup(preparation.RAW_STAGE_REQUEST).outcome.status == "recovery_required"


def test_briefing_create_only_rechecks_local_permission_after_cached_snapshot(tmp_path, monkeypatch):
    from app.briefing import compose, trigger
    host = environment(tmp_path, monkeypatch)
    monkeypatch.setattr(trigger, "BRIEFING_ENABLED", True)
    original = compose.write_note_relative
    target = compose.briefing_note_path(vault_context=host.manager.context, for_date=trigger._local_now(None).date())
    def permission_revoked(*args, **kwargs):
        path = host.root / "settings/local.md"
        settings = host.manager.markdown_store
        doc = settings.read(path)
        settings.write_frontmatter(path, {**doc.frontmatter, "allowWritesToVault": False}, body=doc.body)
        return original(*args, **kwargs)
    monkeypatch.setattr(compose, "write_note_relative", permission_revoked)
    assert invoke(host).exit_code != 0
    assert not target.exists()
    store = JsonReceiptStore(host.runtime.registry.path.parent / "operation-receipts.json")
    pending = store.lookup(preparation.PREPARATION_REQUEST).outcome.to_dict()
    assert pending["status"] == "recovery_required" and pending["extensions"]["pending_effect"] == "briefing"
    assert PROFILE not in host.runtime.registry.lookup(host.binding_id).extensions
