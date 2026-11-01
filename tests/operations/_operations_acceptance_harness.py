"""Canonical temporary Product fixture, explicitly pre-merge evidence."""
from __future__ import annotations

from dataclasses import replace
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import secrets
from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.app import app
from app.api.native_operations_acceptance import prepare_native_context, source_templates, native_probe
from app.api.routes import active_context_selection, capture
from app.instance.local_operator_principal import AuthPosture
from app.instance.runtime import open_default_vault_service
from app.instance.vault_registry import AppLocalSettingsStore
from app.ops.operations_acceptance import PROFILE, SELECTION_HASH, OperationsAcceptanceRefusal, file_hash
from tests._mvr_default_vault_harness import new_runtime, activate
from tests._mvr03_principal_harness import run_principal_cutover
from tests.api._vault_test_helpers import bind_initialized_vault
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY

OPERATION = "64790000-0000-4000-8000-000000000001"
ROOT = Path(__file__).resolve().parents[2]


def sdk_python():
    try:
        importlib.metadata.distribution("mimer-mcp-sidecar")
        return sys.executable
    except importlib.metadata.PackageNotFoundError:
        python = ROOT / ".codex-tmp/issue-6479/sdk-runtime/bin/python"
        assert python.is_file(), "Install the separate sidecar distribution for real SDK proof"
        return str(python)


def identity(channel="test"):
    from app.ops.native_operations_acceptance_runner import PACKAGE_PROBE
    package = json.loads(subprocess.check_output([sdk_python(), "-I", "-c", PACKAGE_PROBE], text=True))
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip()
    package["source_sha"] = revision
    return {"profile": PROFILE, "selection_hash": SELECTION_HASH, "source_sha": revision,
        "image_digest": "sha256:" + "a" * 64, "resource_tree": tree, "channel": channel,
        "operation_id": OPERATION, "execution_kind": "premerge", "activation_scope": "full",
        "api_container_id": "1" * 64, "ui_container_id": "2" * 64,
        "api_image_id": "sha256:" + "3" * 64, "ui_image_id": "sha256:" + "4" * 64,
        "native_receipt_sha256": "5" * 64, "sidecar": package,
        "producer_hashes": {"tests/operations/live_operations_acceptance.py": file_hash(ROOT / "tests/operations/live_operations_acceptance.py")},
        "resource_hashes": {"app/api/native_operations_acceptance.py": file_hash(ROOT / "app/api/native_operations_acceptance.py")}}


def host(tmp_path, monkeypatch, *, channel="test", freeze=True, prepare=True):
    from app.briefing import trigger as briefing_trigger
    # Anchor the synthetic journey's implicit briefing date before initialization.
    fixture_now = briefing_trigger._local_now(None)
    monkeypatch.setattr(briefing_trigger, "datetime", SimpleNamespace(
        now=lambda *, tz: fixture_now.astimezone(tz)))
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
    current = runtime.registry.lookup(registration.vault_binding_id)
    runtime.registry.update_registration(replace(current, extensions={**current.extensions, PROFILE: {"operation_id": OPERATION}}),
                                          _capability=STORAGE_MUTATION_CAPABILITY)
    open_default_vault_service(runtime.registry.path).set(registration.vault_binding_id)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.registry.path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    # The initializer deliberately uses remember=False. A fresh API/SDK
    # process must restore the same selection from actual registry history,
    # so use the ordinary authority-aware picker producer before admission.
    manager.app_local_store = AppLocalSettingsStore()
    selected_context = manager.select_vault(root, remember=True)
    assert selected_context.status == "selected"
    assert runtime.registry.load().last_active_vault_ref == current.ref
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "false")
    monkeypatch.setattr(capture, "_offer_question_registration_proposal", lambda **_: None)
    sources = source_templates(OPERATION)
    from app.vault.paths import get_vault_capture_note_rel
    sources["capture"]["path"] = get_vault_capture_note_rel(root)
    for source in sources.values():
        path = root / source["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source["text"])
    if channel == "test":
        qualify_raw_fixture(runtime, root, registration.vault_binding_id, tmp_path, monkeypatch)
    else:
        monkeypatch.delenv("PKM_CONFIG_ROOT", raising=False)
    # Construct the ordinary derived first-contact prestate before native
    # qualification. The runner must only observe it, never generate it.
    from app.briefing.compose import compose_briefing
    from app.briefing.trigger import BRIEFING_ENABLED, _local_now
    from app.write_guard import WriteGuard
    if BRIEFING_ENABLED:
        compose_briefing(vault_context=selected_context, for_date=_local_now(None).date(),
                        write_guard=WriteGuard(lambda: {"state": "healthy"}))
    active_context_selection.reset_selection_store_for_tests()
    client = TestClient(app)
    selected = client.post("/api/companion/active-context/selection", json={"vault_binding_ids": [registration.vault_binding_id]})
    assert selected.status_code == 201, selected.text
    selection = selected.json()
    headers = {"X-Active-Context-Session": selection["context_selection_id"]}
    facts = identity(channel)
    fixture_files = {path.relative_to(root).as_posix(): file_hash(path)
                     for path in sorted(root.rglob("*")) if path.is_file()}
    try:
        public = prepare_native_context(facts, registry_path=runtime.registry.path) if prepare else None
    except OperationsAcceptanceRefusal as exc:
        # Retain actual temporary prestate in original failure evidence:
        # synthetic relative paths and hashes only, never contents/carriers.
        exc.add_note("Temporary fixture file inventory: " + json.dumps(fixture_files, sort_keys=True))
        raise
    result = SimpleNamespace(runtime=runtime, root=root, binding_id=registration.vault_binding_id,
        artifact_id=sources["read"]["artifact_id"], note=root / sources["read"]["path"],
        client=client, selection=selection, headers=headers, sources=sources, identity=facts, initial=public,
        fixture_files=fixture_files)
    if freeze:
        frozen = client.post("/api/operations/acceptance/admission", json={}, headers=headers)
        assert frozen.status_code == 200, frozen.text
        result.binding = frozen.json()
    seed_derived(result)
    return result


def qualify_raw_fixture(runtime, root, binding_id, tmp_path, monkeypatch):
    """Real encrypted raw/GAF fixture; only physical-volume ports are doubled."""
    from datetime import datetime, timedelta, timezone
    from app.api.native_operations_acceptance import raw_fixture_bytes
    from app.heimdal import raw_store, raw_read_gate, consent_ledger, local_archive, raw_liveness
    from app.heimdal.settings_notes import write_settings_note, SettingsNote, SETTINGS
    from app.instance.runtime import open_local_operator_principal_store
    from app.ops import heimdal_cold_volume as volume
    from app.write_guard import WriteGuard
    raw_store.reset_memory_raw_store()
    raw_read_gate.reset_memory_raw_read_receipts()
    consent_ledger.reset_memory_consent_ledger()
    raw_liveness.reset_memory_deletion_receipts()
    key = secrets.token_bytes(32)
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", key.hex())
    monkeypatch.setenv("HEIMDAL_RAW_READ_ALLOWLIST", local_archive.OPERATION_RESTORE_SERVICE)
    configuration = tmp_path / "native-config"
    configuration.mkdir()
    monkeypatch.setenv("PKM_CONFIG_ROOT", str(configuration))
    cold = tmp_path / "cold-volume"
    cold.mkdir()
    metadata = SimpleNamespace(mountpoint=cold, archive_id="synthetic-operations", channel="test")
    def ready(*args, **kwargs):
        return volume._issue_archive_volume_ready(metadata.archive_id, cold, _issuer=volume._ARCHIVE_VOLUME_READY_ISSUER)
    monkeypatch.setattr(volume, "load_channel_archive_metadata", lambda **kwargs: metadata)
    monkeypatch.setattr(volume, "require_archive_volume_ready", ready)
    monkeypatch.setattr(local_archive, "load_channel_archive_metadata", lambda **kwargs: metadata)
    monkeypatch.setattr(local_archive, "require_archive_volume_ready", ready)
    write_settings_note(root, SettingsNote(spec=SETTINGS, values={"retention_window_days": 30}),
                        write_guard=WriteGuard(lambda: {"state": "healthy"}))
    principal = open_local_operator_principal_store(runtime.registry.path).require().local_operator_role_id
    grant = consent_ledger.grant_consent(grant_ref=PROFILE + ":" + OPERATION, basis="self_record",
        scope=PROFILE + ":" + OPERATION, granted_by=principal,
        payload={"instance_identity": runtime.registry.load().app_install_id, "vault_binding_id": binding_id})
    plaintext = raw_fixture_bytes(OPERATION)
    ciphertext, nonce = raw_store.encrypt_raw_bytes(plaintext, key=key)
    record, created = raw_store.insert_raw_record(content_identity=raw_store.compute_raw_content_identity(plaintext),
        capture_chain=[PROFILE, "heimdal"], sensor={"sensor_id": PROFILE, "operation_id": OPERATION},
        consent={"grant_ref": grant.grant_ref}, ciphertext=ciphertext, nonce=nonce,
        key_ref="temporary-test-key", key=key, source_path="synthetic-operations-fixture")
    assert created
    # Real selector eligibility over a temporary memory fixture; no live
    # clock, retention policy or raw identity is changed by the runner.
    backend = raw_store._MEMORY_STORE
    with backend._lock:
        aged = replace(record, ingested_at=datetime.now(timezone.utc) - timedelta(days=8))
        backend._rows = [aged if row.id == record.id else row for row in backend._rows]
        backend._by_identity[aged.content_identity] = aged


def seed_derived(host):
    """Fixture seeding into real derived stores; never called by live runner."""
    from app.components.llm.fabric import get_embeddings_client, LLMTaskIntent
    from app.index.artifact_metadata import build_indexed_unit_payload
    from app.stores import get_object_store, get_vector_index
    from app.retrieval.hybrid import get_store
    embedder = get_embeddings_client(LLMTaskIntent(task_kind="embed", determinism_required=False))
    documents = []
    for source in host.sources.values():
        path = host.root / source["path"]
        text = path.read_text().split("---", 2)[-1].strip()
        payload = build_indexed_unit_payload(object_id=source["artifact_id"], kind="note", source_ref=source["path"], text=text,
            payload={"note_path": source["path"], "domain": host.selection["context"]["scope"],
                     "vault_binding_id": host.binding_id}, embedding_identity=embedder.identity)
        get_object_store().put(UUID(source["artifact_id"]), kind="note", source_ref=source["path"], payload=payload)
        get_vector_index().upsert(UUID(source["artifact_id"]), kind="note", source_ref=source["path"], payload=payload,
            embedding=embedder.embed_text(text), model=embedder.identity.model, identity=embedder.identity)
        documents.append({"doc_id": source["artifact_id"], "text": text, "payload": payload})
    get_store().set_documents(documents)


class LocalNative:
    def __init__(self, host):
        self.host = host
        self.channel, self.operation_id = host.identity["channel"], OPERATION

    def admit(self):
        return self.host.initial

    def observe(self):
        return native_probe(self.host.runtime.registry.path)


def journey(host, directory, api_url, ui_url=None, *, native=None):
    from tests.operations.live_operations_acceptance import OperationsJourney
    result = OperationsJourney(native or LocalNative(host), directory)
    result.http.base_url = api_url
    result.api_url = api_url
    if ui_url is not None:
        result.ui_url = ui_url
    result.binding, result.bearer = host.binding, host.selection["context_selection_id"]
    directory.mkdir(mode=0o700)
    return result


class NativeFixturePorts:
    """Temporary native journal + external Docker/browser ports, no live PASS.

    Public NativeChannel orchestration/readers, Git resources, actual installed
    SDK qualification, native fixture producer and Product owners remain real.
    Only physical host/container/browser facts use this premerge fixture.
    """
    def __init__(self, host, tmp_path, monkeypatch):
        import yaml
        from app.ops import native_operations_acceptance_runner as runner
        from app.ops.postgres_deploy import DeployJournal, DeployPlan
        from app.ops.postgres_deploy_linux import LinuxConfig
        from tests.deploy.test_postmerge_pg_acceptance import _result, DIGEST, IMAGE_ID
        self.host = host
        self.runner, self.digest, self.image_id = runner, DIGEST, IMAGE_ID
        self.channel = host.identity["channel"]
        self.sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        self.journal = DeployJournal(tmp_path / "native-journal", self.channel)
        self.plan = DeployPlan(self.channel, self.sha, ("db", "api"), ("postgres-db", "postgres-api"),
                               image_digest=DIGEST, automatic=True)
        self.result = _result
        self.api_id, self.ui_id = "1" * 64, "2" * 64
        self.api_command = None
        self.api_workdir, self.ui_workdir = "/app", "/app/companion-ui/companion-app"
        self.prepares = 0
        self.compose = yaml.safe_load((ROOT / "docker-compose.yaml").read_text())
        self.commit(OPERATION)
        monkeypatch.setattr(LinuxConfig, "load", lambda *args, **kwargs: SimpleNamespace(root=ROOT, journal=self.journal))
        monkeypatch.setattr(runner, "SDK_PYTHON", Path(sdk_python()))
        original = runner.command
        self.browser = {"playwright": "premerge-external-port", "executable": "/native-fixture/browser",
                        "executable_sha256": "b" * 64}
        def port(argv, *, payload=None, cwd=None):
            if argv == [str(runner.SDK_PYTHON), "-I", "-c", runner.BROWSER_PROBE]:
                return json.dumps(self.browser)
            if argv[0] != "docker":
                return original(argv, payload=payload, cwd=cwd)
            if argv[1] == "ps":
                return self.api_id if "label=com.docker.compose.service=api" in argv else self.ui_id
            if argv[1] == "inspect":
                return json.dumps([self.container("api" if argv[2] == self.api_id else "companion-ui")])
            if argv[1:3] == ["image", "inspect"]:
                return json.dumps([{"RepoDigests": ["ghcr.io/rasmustho/pkm-app@" + DIGEST]}])
            assert argv[1] == "exec", argv
            if "app.api.native_operations_acceptance" not in argv:
                assert "socket.getaddrinfo" in argv[-1]
                return json.dumps(["172.24.0.2"])
            if argv[-1] == "prepare":
                self.prepares += 1
                return json.dumps(prepare_native_context(payload, registry_path=host.runtime.registry.path))
            assert argv[-1] == "probe", argv
            return json.dumps(native_probe(host.runtime.registry.path))
        monkeypatch.setattr(runner, "command", port)

    def commit(self, operation):
        self.journal.bind_request(operation, self.plan, False, create=True)
        for stage in ("prepared", "preflighted", "materialized", "authenticating", "activating", "verifying"):
            self.journal.write(operation, stage)
        self.journal.write(operation, "committed", self.result(self.sha, self.channel, operation))

    def successor(self):
        from uuid import uuid5
        operation = str(uuid5(UUID(OPERATION), PROFILE + ":backend-wsp-restart"))
        self.commit(operation)
        self.api_id = "6" * 64
        active_context_selection.reset_selection_store_for_tests()
        return operation

    def container(self, service):
        api = service == "api"
        api_port, ui_port = ((18001, 8111) if self.channel == "dev" else (18002, 8112))
        env = ["PKM_ENVIRONMENT=" + self.channel, "VCS_REF=" + self.sha, "PKM_ACTIVATION_SCOPE=full"]
        if not api:
            env += ["COMPANION_API_BASE_URL=http://api:8000", "PORT=" + str(ui_port)]
        inner, outer = (8000, api_port) if api else (ui_port, ui_port)
        command = ([value.replace("$$", "$") for value in self.compose["services"]["api"]["command"]]
                   if api else ["/bin/bash", "-c", 'python -m "${COMPANION_UI_SERVE_MODULE:-companion_ui.workspace.serve_dev_page}"'])
        if api and self.api_command is not None:
            command = self.api_command
        return {"Id": self.api_id if api else self.ui_id, "Image": self.image_id, "State": {"Running": True}, "Mounts": [],
            "Config": {"Env": env, "Entrypoint": None, "Cmd": command,
                "WorkingDir": self.api_workdir if api else self.ui_workdir,
                "Labels": {"org.opencontainers.image.revision": self.sha, "com.docker.compose.project": "pkm-" + self.channel,
                           "com.docker.compose.service": service, "io.yggdrasil.acceptance-kind": "premerge"}},
            "NetworkSettings": {"Ports": {str(inner) + "/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(outer)}]},
                "Networks": {"fixture": {"Aliases": ["api" if api else "companion-ui"], "IPAddress": "172.24.0.2" if api else "172.24.0.3"}}}}
