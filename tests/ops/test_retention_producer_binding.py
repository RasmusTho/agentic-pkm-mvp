from __future__ import annotations

import json
import io
import os
import struct
import sys
import socket
from dataclasses import replace
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ops import bws_installation_admission as admission
from app.ops import bws_source_image_cache as cache
from app.ops import postgres_deploy_host as host
from app.ops.host_secret_controller import HostSecretAdmissionError, HostSecretController, TerminalEvidence
from app.ops.host_secret_contract import DATABASE_CONSUMERS
from app.ops.pg_acceptance import IMAGE_REPOSITORY
from app.ops.postgres_deploy import AuthorityCutover, DeployPlan, DeployReceipt
from app.ops.postgres_deploy import PostgresDeployError, deploy_from_host, host_deploy_image_binding
from app.ops.postgres_deploy_linux import source_identity_request_fingerprint
from tests.deploy.test_deploy_channel_script import _bws_host
from tests.ops.test_bws_installation_admission import _patch_directories, _receipt, _request
from tests.ops.test_bws_installation_transaction import _transaction_fixture

BOOT_ID = "12345678-1234-4234-8234-123456789abc"


@pytest.mark.parametrize("channel", ["dev", "test"])
def test_source_binding_retains_exact_identity_after_interruption(monkeypatch, tmp_path, channel):
    runtime, _ = _patch_directories(monkeypatch, tmp_path)
    request = {**_request(), "image_pull": True}
    request["channel"] = channel
    store = {"daemon_id": "daemon-a", "data_root": "/var/lib/docker", "device": 42, "inode": 5,
             "driver": "overlayfs", "driver_type": "io.containerd.snapshotter.v1",
             "daemon_pid": 42, "daemon_start_ticks": "1234", "daemon_boot_id": BOOT_ID}

    with pytest.raises(admission.InstallationAdmissionRefused):
        with admission.installation_admission(**request) as owner:
            owner.bind_image_cache(store)
            raise RuntimeError("simulated lost pull response")

    binding = json.loads((runtime / f"bws-source-installation-{request['operation_id']}.image-binding.json").read_text())
    assert binding == {
        "schema": "bws-source-image-binding.v1", "operation_id": request["operation_id"],
        "channel": request["channel"], "candidate_sha": request["candidate_sha"],
        "image_digest": request["image_digest"], "repository": IMAGE_REPOSITORY, "store": store,
    }
    with pytest.raises(admission.InstallationAdmissionRefused):
        with admission.installation_admission(channel, mode="shared"):
            pytest.fail("unresolved owner must prevent new source callers")


def test_source_binding_cannot_be_replaced_for_same_operation(monkeypatch, tmp_path):
    runtime, _ = _patch_directories(monkeypatch, tmp_path)
    request = {**_request(), "image_pull": True}
    store = {"daemon_id": "daemon-a", "data_root": "/var/lib/docker", "device": 42, "inode": 5,
             "driver": "overlayfs", "driver_type": "io.containerd.snapshotter.v1",
             "daemon_pid": 42, "daemon_start_ticks": "1234", "daemon_boot_id": BOOT_ID}
    with pytest.raises(admission.InstallationAdmissionRefused):
        with admission.installation_admission(**request) as owner:
            owner.bind_image_cache(store)
            owner.bind_image_cache({**store, "daemon_id": "daemon-b"})
    binding = json.loads((runtime / f"bws-source-installation-{request['operation_id']}.image-binding.json").read_text())
    assert binding["store"] == store


def test_source_binding_prevents_reuse_even_if_owner_marker_is_missing(monkeypatch, tmp_path):
    runtime, _ = _patch_directories(monkeypatch, tmp_path)
    request = {**_request(), "image_pull": True}
    store = {"daemon_id": "daemon-a", "data_root": "/var/lib/docker", "device": 42, "inode": 5,
             "driver": "overlayfs", "driver_type": "io.containerd.snapshotter.v1",
             "daemon_pid": 42, "daemon_start_ticks": "1234", "daemon_boot_id": BOOT_ID}
    with pytest.raises(admission.InstallationAdmissionRefused):
        with admission.installation_admission(**request) as owner:
            owner.bind_image_cache(store)
            raise RuntimeError("lost response")
    (runtime / "dev.source-installation.lock").unlink()
    with pytest.raises(admission.InstallationAdmissionRefused):
        with admission.installation_admission(**request):
            pytest.fail("a retained binding cannot be replayed")


@pytest.mark.parametrize("stage", ["not_started", "unfinished", "finished", "malformed"])
def test_source_pull_recovery_never_replays_or_discards_binding(monkeypatch, tmp_path, stage):
    runtime, receipts = _patch_directories(monkeypatch, tmp_path)
    request = {**_request(), "image_pull": True}
    store = {"daemon_id": "daemon-a", "data_root": "/var/lib/docker", "device": 42, "inode": 5,
             "driver": "overlayfs", "driver_type": "io.containerd.snapshotter.v1",
             "daemon_pid": 42, "daemon_start_ticks": "1234", "daemon_boot_id": BOOT_ID}
    with pytest.raises(admission.InstallationAdmissionRefused):
        with admission.installation_admission(**request) as owner:
            if stage != "not_started":
                owner.bind_image_cache(store)
            if stage in {"finished", "malformed"}:
                owner.finish_image_pull()
            raise RuntimeError("synthetic process loss before source transaction")
    prefix = f"bws-source-installation-{request['operation_id']}"
    if stage == "malformed":
        (runtime / (prefix + ".image-pull-finished.json")).write_text("{broken")
    recovery = {"action": "source-installation-reconcile", **{
        key: request[key] for key in ("operation_id", "candidate_sha", "image_digest", "bundle_name")
    }}
    proof_calls = []

    def prove(owner):
        assert owner["operation_id"] == request["operation_id"]
        with pytest.raises(admission.InstallationAdmissionRefused):
            with admission.installation_admission("dev", mode="shared"):
                pytest.fail("recovery must hold the source reservation")
        proof_calls.append("channel owner absent")

    result = admission.reconcile_installation_operation("dev", recovery, prove_before_backup=prove)
    if stage == "malformed":
        assert result["source_installation"]["status"] == "unresolved"
        assert proof_calls == [] and not (receipts / (prefix + ".receipt.json")).exists()
    else:
        expected = {"not_started": "source_pull_not_started", "unfinished": "source_pull_unresolved",
                    "finished": "source_pull_complete_before_backup"}[stage]
        assert result["source_installation"]["status"] == "refused_before_backup"
        assert result["source_installation"]["prebackup_gate"] == expected
        assert proof_calls == ["channel owner absent"]
        with admission.installation_admission("dev", mode="shared"):
            pass
        with pytest.raises(admission.InstallationAdmissionRefused):
            with admission.installation_admission(**request):
                pytest.fail("recovery must not permit replay")
    assert (runtime / (prefix + ".image-intent.json")).exists()
    assert (runtime / (prefix + ".image-binding.json")).exists() == (stage != "not_started")


@pytest.mark.parametrize("failure", ["error", "short_write"])
def test_source_crash_after_intent_before_owner_does_not_block_other_operations(monkeypatch, tmp_path, failure):
    runtime, _ = _patch_directories(monkeypatch, tmp_path)
    request = {**_request(), "image_pull": True}
    original_write = admission.os.write

    def interrupted(descriptor, raw):
        if b'"schema":"bws-source-installation-owner.v2"' in raw:
            if failure == "error":
                raise OSError("synthetic owner write interruption")
            return original_write(descriptor, raw[:10])
        return original_write(descriptor, raw)

    with monkeypatch.context() as scoped:
        scoped.setattr(admission.os, "write", interrupted)
        with pytest.raises(admission.InstallationAdmissionRefused):
            with admission.installation_admission(**request):
                pytest.fail("owner write must fail")
    prefix = f"bws-source-installation-{request['operation_id']}"
    assert (runtime / (prefix + ".image-intent.json")).exists()
    assert not (runtime / (prefix + ".image-binding.json")).exists()
    assert (runtime / "dev.source-installation.lock").read_bytes() == b""
    assert not list(runtime.glob(".dev.source-owner-*.tmp"))
    with admission.installation_admission("dev", mode="shared"):
        pass
    with pytest.raises(admission.InstallationAdmissionRefused):
        with admission.installation_admission(**request):
            pytest.fail("orphan intent operation ID must never be reused")


def test_owner_replacement_cannot_authorize_prior_callback(monkeypatch, tmp_path):
    _patch_directories(monkeypatch, tmp_path)
    old = _request()
    with admission.installation_admission(**old) as owner:
        owner.complete(_receipt(old))
    new = {**old, "operation_id": str(uuid4()), "image_pull": True}
    original_replace = admission.os.replace
    original_terminal_check = admission._require_terminal_channel_owners
    checked = []

    def terminal_check_before_truncate(parent):
        original_terminal_check(parent)
        with pytest.raises(admission.InstallationAdmissionRefused):
            admission.require_active_installation_owner(
                "dev", old["operation_id"], old["candidate_sha"], old["image_digest"],
                peer_credentials=(os.getpid(), os.geteuid(), os.getegid()),
            )
        checked.append("before_truncate")

    def replace_after_check(*args, **kwargs):
        if str(args[0]).startswith(".dev.source-owner-"):
            with pytest.raises(admission.InstallationAdmissionRefused):
                admission.require_active_installation_owner(
                    "dev", old["operation_id"], old["candidate_sha"], old["image_digest"],
                    peer_credentials=(os.getpid(), os.geteuid(), os.getegid()),
                )
            checked.append("before_rename")
        return original_replace(*args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(admission.os, "replace", replace_after_check)
        scoped.setattr(admission, "_require_terminal_channel_owners", terminal_check_before_truncate)
        with admission.installation_admission(**new) as owner:
            active = admission.require_active_installation_owner(
                "dev", new["operation_id"], new["candidate_sha"], new["image_digest"],
                peer_credentials=(os.getpid(), os.geteuid(), os.getegid()),
            )
            assert active["operation_id"] == new["operation_id"]
            owner.complete(_receipt(new))
    assert checked == ["before_truncate", "before_rename"]


def test_reconcile_does_not_open_channel_before_global_lock(monkeypatch, tmp_path):
    _patch_directories(monkeypatch, tmp_path)
    request = {**_request(), "image_pull": True}
    recovery = {"action": "source-installation-reconcile", **{
        key: request[key] for key in ("operation_id", "candidate_sha", "image_digest", "bundle_name")
    }}
    original_open = admission._open_lock
    opened = []

    def checked_open(parent, name, **kwargs):
        opened.append(name)
        return original_open(parent, name, **kwargs)

    with admission.installation_admission(**request) as owner:
        with monkeypatch.context() as scoped:
            scoped.setattr(admission, "_open_lock", checked_open)
            result = admission.reconcile_installation_operation("dev", recovery)
        assert result["source_installation"]["reason"] == "global_lock_active"
        assert opened == [admission._GLOBAL_LOCK]
        owner.complete(_receipt(request))


def test_partial_intent_never_publishes_owner_or_effect(monkeypatch, tmp_path):
    runtime, _ = _patch_directories(monkeypatch, tmp_path)
    request = {**_request(), "image_pull": True}
    original_write = admission.os.write

    def partial(descriptor, raw):
        if b'"schema":"bws-source-image-intent.v1"' in raw:
            return original_write(descriptor, raw[:10])
        return original_write(descriptor, raw)

    with monkeypatch.context() as scoped:
        scoped.setattr(admission.os, "write", partial)
        with pytest.raises(admission.InstallationAdmissionRefused):
            with admission.installation_admission(**request):
                pytest.fail("partial intent cannot admit source")
    prefix = f"bws-source-installation-{request['operation_id']}"
    assert not (runtime / (prefix + ".image-intent.json")).exists()
    assert not list(runtime.glob(f".{prefix}.image-intent.json.*.tmp"))
    with admission.installation_admission("dev", mode="shared"):
        pass
    with admission.installation_admission(**request) as owner:
        owner.complete(_receipt(request))


def test_partial_binding_never_dispatches_or_fabricates_recovery(monkeypatch, tmp_path):
    runtime, receipts = _patch_directories(monkeypatch, tmp_path)
    request = {**_request(), "image_pull": True}
    store = {"daemon_id": "daemon-a", "data_root": "/var/lib/docker", "device": 42, "inode": 5,
             "driver": "overlayfs", "driver_type": "io.containerd.snapshotter.v1",
             "daemon_pid": 42, "daemon_start_ticks": "1234", "daemon_boot_id": BOOT_ID}
    original_write = admission.os.write
    effects = []

    def partial(descriptor, raw):
        if b'"schema":"bws-source-image-binding.v1"' in raw:
            return original_write(descriptor, raw[:10])
        return original_write(descriptor, raw)

    with pytest.raises(admission.InstallationAdmissionRefused):
        with admission.installation_admission(**request) as owner:
            with monkeypatch.context() as scoped:
                scoped.setattr(admission.os, "write", partial)
                owner.bind_image_cache(store)
            effects.append("pull")
    recovery = {"action": "source-installation-reconcile", **{
        key: request[key] for key in ("operation_id", "candidate_sha", "image_digest", "bundle_name")
    }}
    result = admission.reconcile_installation_operation("dev", recovery, prove_before_backup=lambda _owner: None)
    assert effects == [] and result["source_installation"]["status"] == "refused_before_backup"
    assert result["source_installation"]["prebackup_gate"] == "source_pull_not_started"
    assert list(receipts.iterdir())
    assert not (runtime / f"bws-source-installation-{request['operation_id']}.image-binding.json").exists()
    with admission.installation_admission("dev", mode="shared"):
        pass


@pytest.mark.parametrize("point", ["before_rename", "after_rename"])
def test_binding_publication_crash_keeps_complete_or_absent_record(monkeypatch, tmp_path, point):
    runtime, _ = _patch_directories(monkeypatch, tmp_path)
    request = {**_request(), "image_pull": True}
    store = {"daemon_id": "daemon-a", "data_root": "/var/lib/docker", "device": 42, "inode": 5,
             "driver": "overlayfs", "driver_type": "io.containerd.snapshotter.v1",
             "daemon_pid": 42, "daemon_start_ticks": "1234", "daemon_boot_id": BOOT_ID}
    original = admission.os.replace
    effects = []

    def interrupted(source, target, **kwargs):
        if str(target).endswith(".image-binding.json"):
            if point == "after_rename":
                original(source, target, **kwargs)
            raise OSError("synthetic process loss at publication")
        return original(source, target, **kwargs)

    with pytest.raises(admission.InstallationAdmissionRefused):
        with admission.installation_admission(**request) as owner:
            with monkeypatch.context() as scoped:
                scoped.setattr(admission.os, "replace", interrupted)
                owner.bind_image_cache(store)
            effects.append("pull")
    path = runtime / f"bws-source-installation-{request['operation_id']}.image-binding.json"
    assert effects == []
    assert path.exists() == (point == "after_rename")
    if path.exists():
        assert json.loads(path.read_text())["store"] == store
    recovery = {"action": "source-installation-reconcile", **{
        key: request[key] for key in ("operation_id", "candidate_sha", "image_digest", "bundle_name")
    }}
    result = admission.reconcile_installation_operation("dev", recovery, prove_before_backup=lambda _owner: None)
    assert result["source_installation"]["prebackup_gate"] == (
        "source_pull_unresolved" if point == "after_rename" else "source_pull_not_started"
    )


@pytest.mark.parametrize("point", ["short_write", "before_rename", "after_rename"])
def test_reconcile_receipt_publication_crash_can_be_retried(monkeypatch, tmp_path, point):
    _, receipts = _patch_directories(monkeypatch, tmp_path)
    request = {**_request(), "image_pull": True}
    with pytest.raises(admission.InstallationAdmissionRefused):
        with admission.installation_admission(**request):
            raise RuntimeError("synthetic process loss")
    recovery = {"action": "source-installation-reconcile", **{
        key: request[key] for key in ("operation_id", "candidate_sha", "image_digest", "bundle_name")
    }}
    original_write, original_replace = admission.os.write, admission.os.replace

    def interrupted_write(descriptor, raw):
        if point == "short_write" and b'"schema":"agentic-pkm.bws-source-installation-receipt.v1"' in raw:
            return original_write(descriptor, raw[:10])
        return original_write(descriptor, raw)

    def interrupted_replace(source, target, **kwargs):
        if point != "short_write" and str(target).endswith(".receipt.json"):
            if point == "after_rename":
                original_replace(source, target, **kwargs)
            raise OSError("synthetic interruption during receipt publication")
        return original_replace(source, target, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(admission.os, "write", interrupted_write)
        scoped.setattr(admission.os, "replace", interrupted_replace)
        first = admission.reconcile_installation_operation("dev", recovery, prove_before_backup=lambda _owner: None)
    assert first["source_installation"]["status"] == "unresolved"
    path = receipts / f"bws-source-installation-{request['operation_id']}.receipt.json"
    assert path.exists() == (point == "after_rename")
    if path.exists():
        assert json.loads(path.read_text())["prebackup_gate"] == "source_pull_not_started"
    second = admission.reconcile_installation_operation("dev", recovery, prove_before_backup=lambda _owner: None)
    assert second["source_installation"]["status"] == "refused_before_backup"
    assert second["source_installation"]["prebackup_gate"] == "source_pull_not_started"
    with admission.installation_admission("dev", mode="shared"):
        pass


@pytest.mark.parametrize("channel_lock_present", [False, True])
def test_real_source_reconcile_requires_absent_channel_lock(monkeypatch, tmp_path, channel_lock_present):
    from app.ops import bws_installation_transaction, postgres_deploy_linux
    runtime, receipts = _patch_directories(monkeypatch, tmp_path)
    request = {**_request(), "image_pull": True}
    store = {"daemon_id": "daemon-a", "data_root": "/var/lib/docker", "device": 42, "inode": 5,
             "driver": "overlayfs", "driver_type": "io.containerd.snapshotter.v1",
             "daemon_pid": 42, "daemon_start_ticks": "1234", "daemon_boot_id": BOOT_ID}
    with pytest.raises(admission.InstallationAdmissionRefused):
        with admission.installation_admission(**request) as owner:
            owner.bind_image_cache(store)
            raise RuntimeError("pull reply lost")
    root = tmp_path / "installed"
    (root / "config/deploy").mkdir(parents=True)
    if channel_lock_present:
        (root / "config/deploy/dev.env.lock").mkdir()
    cfg = SimpleNamespace(channel="dev", root=root)
    monkeypatch.setattr(postgres_deploy_linux.LinuxConfig, "load", lambda *_args: cfg)
    recovery = {"action": "source-installation-reconcile", **{
        key: request[key] for key in ("operation_id", "candidate_sha", "image_digest", "bundle_name")
    }}
    result = bws_installation_transaction.reconcile_source_installation("dev", recovery)["source_installation"]
    receipt = receipts / f"bws-source-installation-{request['operation_id']}.receipt.json"
    if channel_lock_present:
        assert result["status"] == "unresolved" and not receipt.exists()
    else:
        assert result["status"] == "refused_before_backup" and result["prebackup_gate"] == "source_pull_unresolved"
        assert receipt.exists() and (runtime / f"bws-source-installation-{request['operation_id']}.image-binding.json").exists()


def test_host_binding_rejects_same_revision_with_different_digest_after_unknown(tmp_path):
    controller = HostSecretController(tmp_path / "host")
    operation_id = str(uuid4())

    def binding(digest):
        plan = DeployPlan("dev", "a" * 40, ("db",), ("postgres-db",), image_digest=digest)
        return host_deploy_image_binding(plan)

    selected = binding("sha256:" + "b" * 64)
    with controller.deploy_operation("dev", allow_bootstrap=False, operation_id=operation_id,
                                     deploy_image_binding=selected) as (operation, resumed):
        assert not resumed
        operation.prepare_mutation()
    with controller._locked_journal() as descriptor:
        pending = controller._pending(descriptor)
    assert pending is not None and pending["deploy_image_binding"] == selected
    with pytest.raises(HostSecretAdmissionError):
        with controller.deploy_operation("dev", allow_bootstrap=False, operation_id=operation_id,
                                         deploy_image_binding=binding("sha256:" + "c" * 64)):
            pytest.fail("conflicting digest must never resume the unknown operation")
    controller.reconcile(lambda op, kind, channel: TerminalEvidence(op, kind, channel, "failed", "remote-terminal"),
                         expected_deploy_image_binding=selected)
    with controller._locked_journal() as descriptor:
        assert controller._pending(descriptor) is None


def test_host_entrypoint_binds_plan_before_lost_remote_prepare(tmp_path):
    admin, provider, original, remote = _bws_host(tmp_path)
    provider.seed('test/postgres.password', 'fake-role-password', ('non-prod',))
    plan = replace(original, image_digest="sha256:" + "b" * 64)
    sent = []

    def lost(operation_id, selected, *, bootstrap):
        rows = [json.loads(line) for line in (admin.controller.directory / "operations.jsonl").read_text().splitlines()]
        record = rows[-1]
        stored = json.loads(record["deploy_image_binding"])
        assert record["stage"] == "sent" and record["operation_id"] == operation_id
        assert stored["repository"] == IMAGE_REPOSITORY
        assert stored["image_digest"] == selected.image_digest
        sent.append(operation_id)
        raise RuntimeError("lost transport reply")

    remote.prepare = lost
    with pytest.raises(PostgresDeployError):
        deploy_from_host(admin, remote, plan, qualified=lambda: None, allow_bootstrap=False)
    with pytest.raises(PostgresDeployError):
        deploy_from_host(admin, remote, replace(plan, image_digest="sha256:" + "c" * 64),
                         qualified=lambda: None, allow_bootstrap=False)
    assert len(sent) == 1


def test_manual_tag_only_host_deploy_refuses_before_dispatch(tmp_path):
    admin, _provider, plan, remote = _bws_host(tmp_path)
    with pytest.raises(PostgresDeployError):
        deploy_from_host(admin, remote, replace(plan, image_digest=None), qualified=lambda: None,
                         allow_bootstrap=False)
    assert remote.events == []
    assert not (admin.controller.directory / "operations.jsonl").exists()


@pytest.mark.parametrize("foreign", [
    {"DOCKER_CONTEXT": "remote"}, {"DOCKER_HOST": "tcp://example.invalid:2375"},
    {"APP_IMAGE_REPOSITORY": "example.invalid/other"}, {"DOCKER_TLS_VERIFY": "1"},
])
def test_host_image_endpoint_refuses_ambient_selector(foreign):
    from app.ops.postgres_deploy_linux import _bind_nonproduction_image_endpoint
    with pytest.raises(PostgresDeployError):
        _bind_nonproduction_image_endpoint(dict(foreign))


def test_host_image_endpoint_pins_official_repo_and_local_daemon():
    from app.ops.postgres_deploy_linux import _bind_nonproduction_image_endpoint
    env = {"DOCKER_CONTEXT": "default"}
    _bind_nonproduction_image_endpoint(env)
    assert env == {"DOCKER_HOST": "unix:///var/run/docker.sock", "APP_IMAGE_REPOSITORY": IMAGE_REPOSITORY}


@pytest.mark.parametrize("pull_fails", [False, True])
def test_source_engine_binds_pull_and_inspection_to_one_connection(monkeypatch, pull_fails):
    digest = "sha256:" + "b" * 64
    revision = "a" * 40
    reference = IMAGE_REPOSITORY + "@" + digest
    events = []

    class Stream:
        def settimeout(self, _timeout):
            pass

        def bind(self, address):
            assert address.startswith("\0yggdrasil-source-")

        def connect(self, path):
            assert path == cache._SOCKET

        def getsockopt(self, *_args):
            return struct.pack("3i", 42, 0, 0)

        def close(self):
            pass

    class Response:
        status = 200
        will_close = False

        def __init__(self, body):
            self.body = io.BytesIO(body)

        def read(self, size):
            return self.body.read(size)

        def readline(self, size):
            return self.body.readline(size)

    class Connection:
        def __init__(self, *_args, **_kwargs):
            self.sock = None
            self.auto_open = 1
            self.method = ""
            self.target = ""

        def request(self, method, target):
            assert self.auto_open == 0 and self.sock is stream
            self.method, self.target = method, target
            events.append((method, target))

        def getresponse(self):
            if self.target == "/info":
                return Response(json.dumps({"ID": "daemon-a", "DockerRootDir": "/var/lib/docker",
                                            "Driver": "overlayfs",
                                            "DriverStatus": [["driver-type", "io.containerd.snapshotter.v1"]]}).encode())
            if self.method == "POST":
                return Response(b'{"error":"synthetic"}\n' if pull_fails else b'{"status":"downloaded"}\n')
            return Response(json.dumps({"Config": {"Labels": {"org.opencontainers.image.revision": revision}},
                                        "RepoDigests": [reference]}).encode())

        def close(self):
            self.sock = None

    stream = Stream()
    monkeypatch.setattr(cache.socket, "SO_PEERCRED", 17, raising=False)
    monkeypatch.setattr(cache.socket, "socket", lambda *_args: stream)
    monkeypatch.setattr(cache.http.client, "HTTPConnection", Connection)
    monkeypatch.setattr(cache, "_root_identity", lambda _root: (10, 20))
    monkeypatch.setattr(cache, "_qualified_daemon", lambda *_args:
                        (cache.os.open("/dev/null", cache.os.O_RDONLY), 42, "1234", BOOT_ID))
    monkeypatch.setattr(cache.SourceImageCacheSession, "_check_daemon", lambda _self: None)
    original_stat = cache.os.stat
    original_read_text = cache.Path.read_text

    def fake_stat(path, *args, **kwargs):
        if str(path) in {"/proc/42/ns/mnt", "/proc/self/ns/mnt", "/proc/42/root", "/proc/self/root"}:
            return SimpleNamespace(st_dev=1, st_ino=2)
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(cache.os, "stat", fake_stat)
    monkeypatch.setattr(cache.Path, "read_text", lambda path, *args, **kwargs:
                        "dockerd\n" if str(path) == "/proc/42/comm" else original_read_text(path, *args, **kwargs))
    owner = SimpleNamespace(candidate_sha=revision, image_digest=digest,
                            bind_image_cache=lambda store: events.append(("BIND", store)),
                            finish_image_pull=lambda: events.append(("FINISH", None)))
    with cache.SourceImageCacheSession() as session:
        assert session.store == {"daemon_id": "daemon-a", "data_root": "/var/lib/docker", "device": 10,
                                 "inode": 20, "driver": "overlayfs", "driver_type": "io.containerd.snapshotter.v1",
                                 "daemon_pid": 42, "daemon_start_ticks": "1234", "daemon_boot_id": BOOT_ID}
        if pull_fails:
            with pytest.raises(cache.SourceImageCacheRefused):
                session.pull_and_inspect(owner, revision, digest)
        else:
            session.pull_and_inspect(owner, revision, digest)
        with pytest.raises(cache.SourceImageCacheRefused):
            session.pull_and_inspect(owner, revision, digest)
    assert [event[0] for event in events] == (["GET", "BIND", "POST"] if pull_fails
                                             else ["GET", "BIND", "POST", "GET", "FINISH"])
    assert events[2][1].startswith("/images/create?")


@pytest.mark.parametrize("channel", ["dev", "test"])
@pytest.mark.parametrize("pull_fails", [False, True])
def test_source_prep_binds_before_pull_and_survives_unknown(monkeypatch, tmp_path, channel, pull_fails):
    from app.ops import bws_installation_transaction as transaction
    runtime, _ = _patch_directories(monkeypatch, tmp_path)
    request, ports, _fake_admission, _service, _events, _old_state, _candidate = _transaction_fixture(
        channel=channel, channel_lock_error=not pull_fails,
    )
    store = {"daemon_id": "daemon-a", "data_root": "/var/lib/docker", "device": 42, "inode": 5,
             "driver": "overlayfs", "driver_type": "io.containerd.snapshotter.v1",
             "daemon_pid": 42, "daemon_start_ticks": "1234", "daemon_boot_id": BOOT_ID}
    effects = []

    @contextmanager
    def reservation(selected, selected_channel, operation_id, digest):
        assert selected == store and selected_channel == channel
        assert operation_id == request["operation_id"] and digest == request["image_digest"]
        yield

    class Session(cache.SourceImageCacheSession):
        def __enter__(self):
            self.store = store
            self._socket = SimpleNamespace(shutdown=lambda _how: None)
            return self

        def _check_daemon(self):
            pass

        def _response(self, method, target):
            assert method == "POST" and target.startswith("/images/create?")
            path = runtime / f"bws-source-installation-{request['operation_id']}.image-binding.json"
            binding = json.loads(path.read_text())
            assert binding["image_digest"] == request["image_digest"] and binding["store"] == store
            effects.append("pull")
            return io.BytesIO(b'{"error":"lost"}\n' if pull_fails else b'{"status":"done"}\n')

        def _json(self, method, target):
            assert method == "GET" and target.startswith("/images/")
            return {"Config": {"Labels": {"org.opencontainers.image.revision": request["candidate_sha"]}},
                    "RepoDigests": [IMAGE_REPOSITORY + "@" + request["image_digest"]]}

        def close(self):
            self._socket = None

    monkeypatch.setattr(cache, "reserve_capacity", reservation)
    monkeypatch.setattr(cache, "SourceImageCacheSession", Session)
    monkeypatch.setattr(cache, "require_capacity_guard", lambda: None)
    monkeypatch.setattr(cache, "_root_identity", lambda _path: (42, 5))
    monkeypatch.setattr(transaction, "_verify_candidate_git", lambda *_args: None)
    monkeypatch.setattr(transaction, "_verify_candidate_image", lambda *_args: (_ for _ in ()).throw(RuntimeError()))
    native = transaction._NativePorts()
    native.caller_root = cache.Path("/candidate")
    ports.preflight_source_image = native.preflight_source_image
    ports.prepare_source_image = native.prepare_source_image
    ports.admission = lambda selected_channel, selected: admission.installation_admission(
        selected_channel, mode="exclusive", operation_id=selected["operation_id"],
        candidate_sha=selected["candidate_sha"], image_digest=selected["image_digest"],
        bundle_name=selected["bundle_name"], image_pull=True,
    )
    if pull_fails:
        with pytest.raises(admission.InstallationAdmissionRefused):
            transaction._execute_source_installation(channel, request, ports)
    else:
        result = transaction._execute_source_installation(channel, request, ports)
        assert result["source_installation"]["status"] == "refused_before_backup"
    assert effects == ["pull"]
    assert (runtime / f"bws-source-installation-{request['operation_id']}.image-binding.json").exists()
    if pull_fails:
        with pytest.raises(admission.InstallationAdmissionRefused):
            with admission.installation_admission(channel, mode="shared"):
                pytest.fail("ambiguous pull must retain the source owner")


@pytest.mark.parametrize("channel", ["dev", "test"])
def test_source_capacity_guard_fails_before_admission_when_image_missing(monkeypatch, tmp_path, channel):
    from app.ops import bws_installation_transaction as transaction
    runtime, _ = _patch_directories(monkeypatch, tmp_path)
    request, ports, _admission, _service, events, _old_state, _candidate = _transaction_fixture(channel=channel)
    native = transaction._NativePorts()
    native.caller_root = cache.Path("/candidate")
    ports.preflight_source_image = native.preflight_source_image
    monkeypatch.setattr(transaction, "_verify_candidate_git", lambda *_args: None)
    monkeypatch.setattr(transaction, "_verify_candidate_image", lambda *_args: (_ for _ in ()).throw(RuntimeError()))
    with pytest.raises(cache.SourceImageCapacityUnavailable, match="capacity_guard_unavailable"):
        transaction._execute_source_installation(channel, request, ports)
    assert "admission_enter" not in events
    assert list(runtime.iterdir()) == []


def test_source_rpc_exposes_capacity_guard_refusal(monkeypatch, capsys):
    from app.ops import postgres_deploy_linux
    monkeypatch.setattr(postgres_deploy_linux.sys, "stdin", io.StringIO('{"action":"source-installation"}\n'))
    monkeypatch.setattr(postgres_deploy_linux, "rpc", lambda *_args:
                        (_ for _ in ()).throw(cache.SourceImageCapacityUnavailable()))
    assert postgres_deploy_linux.main(["rpc", "dev"]) == 78
    assert json.loads(capsys.readouterr().out) == {"refused": True, "reason": "capacity_guard_unavailable"}


@pytest.mark.parametrize("channel", ["dev", "test"])
def test_already_cached_source_remains_usable_without_new_pull_guard(monkeypatch, channel):
    from app.ops import bws_installation_transaction as transaction
    request, ports, _admission, _service, events, _old_state, _candidate = _transaction_fixture(channel=channel)
    native = transaction._NativePorts()
    native.caller_root = cache.Path("/candidate")
    ports.preflight_source_image = native.preflight_source_image
    ports.prepare_source_image = native.prepare_source_image
    monkeypatch.setattr(transaction, "_verify_candidate_git", lambda *_args: None)
    monkeypatch.setattr(transaction, "_verify_candidate_image", lambda *_args: None)
    monkeypatch.setattr(cache, "require_capacity_guard", lambda: pytest.fail("cached source must not pull"))
    assert transaction._execute_source_installation(channel, request, ports)["source_installation"]["status"] == "installed"
    assert "admission_enter" in events


def test_source_reconciliation_does_not_require_cached_image_or_capacity_guard(monkeypatch):
    from app.ops import bws_installation_transaction, postgres_deploy_linux
    monkeypatch.setattr(postgres_deploy_linux.os, "geteuid", lambda: 0)
    monkeypatch.setattr(bws_installation_transaction._NativePorts, "preflight_source_image",
                        lambda *_args: pytest.fail("readback must not prepare an image"))
    request = {"action": "source-installation-reconcile", "operation_id": str(uuid4())}
    monkeypatch.setattr(bws_installation_transaction, "reconcile_source_installation",
                        lambda channel, selected: {"readback": (channel, selected)})
    assert postgres_deploy_linux.rpc("dev", request) == {"readback": ("dev", request)}


@pytest.mark.skipif(sys.platform != "linux", reason="Linux SOCK_DIAG integration")
def test_source_engine_sock_diag_identifies_the_actual_accepted_peer(tmp_path):
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(tmp_path / "listener.sock"))
    listener.listen(1)
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.bind("\0source-diag-test-" + uuid4().hex)
    client.connect(str(tmp_path / "listener.sock"))
    accepted, _ = listener.accept()
    try:
        assert cache._connected_peer_inode(client) == cache.os.fstat(accepted.fileno()).st_ino
    finally:
        accepted.close()
        client.close()
        listener.close()


@pytest.mark.parametrize("socket_owned", [True, False])
def test_systemd_socket_peer_requires_the_actual_dockerd_connection(monkeypatch, socket_owned):
    monkeypatch.setattr(cache.subprocess, "run", lambda *_a, **_kw:
                        SimpleNamespace(returncode=0, stdout=b"42\n", stderr=b""))
    monkeypatch.setattr(cache, "_connected_peer_inode", lambda _stream: 12345)
    monkeypatch.setattr(cache, "_process_has_socket", lambda pid, inode:
                        socket_owned and (pid, inode) == (42, 12345))
    original_stat = cache.os.stat
    original_read_text = cache.Path.read_text

    def fake_stat(path, *args, **kwargs):
        if str(path) in {"/proc/42/ns/mnt", "/proc/self/ns/mnt", "/proc/42/root", "/proc/self/root", "/proc/42"}:
            return SimpleNamespace(st_dev=1, st_ino=2, st_uid=0)
        return original_stat(path, *args, **kwargs)

    def fake_read(path, *args, **kwargs):
        if str(path) == "/proc/42/comm":
            return "dockerd\n"
        if str(path) == "/proc/42/stat":
            return "42 (dockerd) " + " ".join(["S", *(["0"] * 18), "1234"])
        if str(path) == "/proc/sys/kernel/random/boot_id":
            return BOOT_ID
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(cache.os, "stat", fake_stat)
    monkeypatch.setattr(cache.Path, "read_text", fake_read)
    monkeypatch.setattr(cache.os, "pidfd_open", lambda *_args: cache.os.open("/dev/null", cache.os.O_RDONLY), raising=False)
    if socket_owned:
        descriptor, pid, start, boot = cache._qualified_daemon(SimpleNamespace(), 1)
        assert (pid, start, boot) == (42, "1234", BOOT_ID)
        cache.os.close(descriptor)
    else:
        with pytest.raises(cache.SourceImageCacheRefused):
            cache._qualified_daemon(SimpleNamespace(), 1)


def test_legacy_unbound_host_unknown_is_not_assigned_a_new_digest(tmp_path):
    admin, provider, original, remote = _bws_host(tmp_path)
    provider.seed('test/postgres.password', 'fake-role-password', ('non-prod',))
    with admin.controller.deploy_operation("test", allow_bootstrap=False) as (operation, _):
        operation.prepare_mutation()
    with pytest.raises(PostgresDeployError):
        deploy_from_host(admin, remote, replace(original, image_digest="sha256:" + "b" * 64),
                         qualified=lambda: None, allow_bootstrap=False)
    assert remote.events == []


def test_source_persistence_retains_binding_through_generic_reconciliation(tmp_path):
    controller = HostSecretController(tmp_path / "host")
    operation_id = str(uuid4())
    binding = json.dumps({"schema": "host-source-image-binding.v1", "repository": IMAGE_REPOSITORY,
                          "channel": "test", "revision": "a" * 40,
                          "image_digest": "sha256:" + "b" * 64, "plan_fingerprint": "f" * 64},
                         sort_keys=True, separators=(",", ":"))
    with controller.source_persistence_operation("test", operation_id=operation_id,
                                                 source_image_binding=binding) as (operation, _):
        operation.prepare_mutation()
    controller.reconcile(lambda op, kind, channel: TerminalEvidence(op, kind, channel, "failed", "remote-terminal"))
    with controller._locked_journal() as descriptor:
        assert controller._pending(descriptor) is None
    rows = [json.loads(line) for line in (controller.directory / "operations.jsonl").read_text().splitlines()]
    assert all(row["source_image_binding"] == binding for row in rows)


def test_source_persistence_host_entry_binds_before_lost_dispatch(monkeypatch, tmp_path):
    controller = HostSecretController(tmp_path / "host")
    operation_id = str(uuid4())
    effects = []

    class Remote:
        def __init__(self, hostname):
            assert hostname == "ygg-dev"

        def persist_source_identity(self, selected_id, revision, digest, selected):
            rows = [json.loads(line) for line in (controller.directory / "operations.jsonl").read_text().splitlines()]
            binding = json.loads(rows[-1]["source_image_binding"])
            assert rows[-1]["stage"] == "sent" and rows[-1]["operation_id"] == selected_id
            assert binding["revision"] == revision and binding["image_digest"] == digest
            effects.append(selected_id)
            raise RuntimeError("lost native response")

    monkeypatch.setattr(host, "HostSecretController", lambda: controller)
    monkeypatch.setattr(host, "SshDeployRemote", Remote)
    args = ["dev", "a" * 40, "--automatic", "--existing-secrets-only", "--persist-source-identity",
            "--operation-id", operation_id, "--image-digest", "sha256:" + "b" * 64,
            "--authority-cutover-binding", "selection", "--authority-cutover-root", "/private/source",
            "--authority-cutover-ownership-root", "/private/owner"]
    assert host.main(args) == 78
    changed = list(args)
    changed[changed.index("--image-digest") + 1] = "sha256:" + "c" * 64
    assert host.main(changed) == 78
    changed = list(args)
    changed[changed.index("--authority-cutover-root") + 1] = "/private/other"
    assert host.main(changed) == 78
    assert effects == [operation_id]
    journal = (controller.directory / "operations.jsonl").read_text()
    assert "/private/source" not in journal and "/private/owner" not in journal


def test_host_journal_fingerprints_plan_without_private_cutover_paths(tmp_path):
    controller = HostSecretController(tmp_path / "host")
    plan = DeployPlan("dev", "a" * 40, ("db",), ("postgres-db",),
                      image_digest="sha256:" + "b" * 64,
                      authority_cutover=AuthorityCutover("selection", "/private/canary-vault", "/private/canary-owner"))
    binding = host_deploy_image_binding(plan)
    with controller.deploy_operation("dev", allow_bootstrap=False, deploy_image_binding=binding) as (operation, _):
        operation.prepare_mutation()
    journal = (controller.directory / "operations.jsonl").read_text()
    assert "canary-vault" not in journal and "canary-owner" not in journal
    changed = replace(plan, authority_cutover=replace(plan.authority_cutover, root="/private/other"))
    with pytest.raises(HostSecretAdmissionError):
        with controller.deploy_operation("dev", allow_bootstrap=False,
                                         deploy_image_binding=host_deploy_image_binding(changed)):
            pytest.fail("a changed private plan must not resume the existing operation")


@pytest.mark.parametrize("mode", ["terminal", "fence"])
def test_bound_host_pending_can_only_reconcile_exact_plan(monkeypatch, tmp_path, mode):
    controller = HostSecretController(tmp_path / "host")
    operation_id = str(uuid4())
    digest = "sha256:" + "b" * 64
    plan = DeployPlan("test", "a" * 40, tuple(DATABASE_CONSUMERS.values()),
                      (*DATABASE_CONSUMERS, "heimdal-api-ingress"), image_digest=digest, automatic=True)
    binding = host_deploy_image_binding(plan)
    with controller.deploy_operation("test", allow_bootstrap=False, operation_id=operation_id,
                                     deploy_image_binding=binding) as (operation, _):
        operation.prepare_mutation()
    with controller.deploy_operation("test", allow_bootstrap=False, operation_id=operation_id,
                                     deploy_image_binding=binding, reconciliation_only=True) as (operation, _):
        with pytest.raises(HostSecretAdmissionError):
            operation.prepare_mutation()
    observed = []

    class Remote:
        def __init__(self, hostname):
            assert hostname == "ygg-test"

        def reconcile_failed(self, selected_id, selected):
            observed.append((selected_id, selected))
            return DeployReceipt(selected_id, "test", "deploy", "failed", "failed")

        def reconcile_unknown(self, selected_id, selected):
            observed.append((selected_id, selected))
            return {"outcome": "unknown"}

    monkeypatch.setattr(host, "HostSecretController", lambda: controller)
    monkeypatch.setattr(host, "SshDeployRemote", Remote)
    action = "--reconcile-pending" if mode == "terminal" else "--reconcile-unknown-pending"
    args = ["test", plan.revision, "--existing-secrets-only", "--automatic", action, "--operation-id", operation_id,
            "--image-digest", digest]
    assert host.main([*args[:-1], "sha256:" + "c" * 64]) == 78
    assert observed == []
    assert host.main(args) == 0
    assert observed == [(operation_id, plan)]
    with controller._locked_journal() as descriptor:
        assert controller._pending(descriptor) is None


def test_legacy_unknown_is_not_replayed_without_terminal_receipt(tmp_path):
    admin, provider, original, remote = _bws_host(tmp_path)
    provider.seed("test/postgres.password", "fake-role-password", ("non-prod",))
    with admin.controller.deploy_operation("test", allow_bootstrap=False) as (operation, _):
        operation.prepare_mutation()
    plan = replace(original, image_digest="sha256:" + "b" * 64)
    with pytest.raises(PostgresDeployError):
        deploy_from_host(admin, remote, plan, qualified=lambda: None, allow_bootstrap=False)
    assert remote.events == []


@pytest.mark.parametrize("receipt_available", [True, False])
def test_legacy_terminal_can_be_read_back_without_rewriting_binding(tmp_path, receipt_available):
    controller = HostSecretController(tmp_path / "host")
    operation_id = str(uuid4())
    with controller.deploy_operation("test", allow_bootstrap=False, operation_id=operation_id) as (operation, _):
        operation.prepare_mutation()
        operation.finish(TerminalEvidence(operation_id, "deploy", "test", "failed", "remote-terminal"))
    before = (controller.directory / "operations.jsonl").read_bytes()
    plan = DeployPlan("test", "a" * 40, tuple(DATABASE_CONSUMERS.values()),
                      (*DATABASE_CONSUMERS, "heimdal-api-ingress"),
                      image_digest="sha256:" + "b" * 64, automatic=True)

    class Remote:
        def reconcile_failed(self, selected_id, selected):
            assert selected_id == operation_id and selected == plan
            if not receipt_available:
                raise RuntimeError("no authenticated receipt")
            return DeployReceipt(selected_id, "test", "deploy", "failed", "failed")

        def prepare(self, *_args, **_kwargs):
            pytest.fail("terminal legacy operation must never send again")

    if receipt_available:
        assert deploy_from_host(SimpleNamespace(controller=controller), Remote(), plan, qualified=lambda: None,
                                allow_bootstrap=False, operation_id=operation_id).terminal_result == "failed"
    else:
        with pytest.raises(PostgresDeployError):
            deploy_from_host(SimpleNamespace(controller=controller), Remote(), plan, qualified=lambda: None,
                             allow_bootstrap=False, operation_id=operation_id)
    assert (controller.directory / "operations.jsonl").read_bytes() == before
    assert b"deploy_image_binding" not in before


@pytest.mark.parametrize("mode,stage", [("absence", "prepared"), ("absence", "sent"), ("cleanup", "sent")])
def test_legacy_current_source_uses_exact_readback_without_fabricated_binding(monkeypatch, tmp_path, mode, stage):
    controller = HostSecretController(tmp_path / "host")
    operation_id = str(uuid4())
    digest = "sha256:" + "b" * 64
    request = {"source_kind": "source-persistence", "source_mode": "current-state",
               "revision": "a" * 40, "image_digest": digest, "producer_kind": "registry",
               "authority_cutover": {"binding_id": "selection", "root": "/private/source",
                                     "ownership_root": "/private/owner"}}
    fingerprint = source_identity_request_fingerprint(request)
    with controller.source_persistence_operation("dev", operation_id=operation_id, producer_kind="registry",
                                                 current_state=True, request_fingerprint=fingerprint) as (op, _):
        if stage == "prepared":
            op._record("prepared")
        else:
            op.prepare_mutation()
    calls = []

    class Remote:
        def __init__(self, hostname):
            assert hostname == "ygg-dev"

        def prove_source_identity_absence(self, selected_id, *, source_request):
            assert selected_id == operation_id and source_request == request
            calls.append("absence")
            return {"operation_id": selected_id, "native_request_absent": True}

        def persist_source_identity(self, selected_id, revision, selected_digest, selected, producer_kind,
                                    *, current_state, cleanup_only):
            assert selected_id == operation_id and revision == request["revision"] and selected_digest == digest
            assert current_state and cleanup_only and producer_kind == "registry"
            calls.append("cleanup")
            return {"terminal_state": "failed"}

    monkeypatch.setattr(host, "HostSecretController", lambda: controller)
    monkeypatch.setattr(host, "SshDeployRemote", Remote)
    args = ["dev", request["revision"], "--automatic", "--existing-secrets-only", "--current-state-source",
            "--persist-source-identity", "--operation-id", operation_id, "--image-digest", digest,
            "--source-producer-kind", "registry", "--authority-cutover-binding", "selection",
            "--authority-cutover-root", "/private/source", "--authority-cutover-ownership-root", "/private/owner"]
    if mode == "absence":
        args.append("--prove-source-persistence-never-admitted")
    changed = list(args)
    changed[changed.index("--image-digest") + 1] = "sha256:" + "c" * 64
    assert host.main(changed) == 78
    assert calls == []
    assert host.main(args) == (0 if mode == "absence" else 78)
    assert calls == [mode]
    with controller._locked_journal() as descriptor:
        assert controller._pending(descriptor) is None
    assert "source_image_binding" not in (controller.directory / "operations.jsonl").read_text()
    rows = [json.loads(line) for line in (controller.directory / "operations.jsonl").read_text().splitlines()]
    assert (any(row["stage"] == "sent" for row in rows)) == (stage == "sent")


@pytest.mark.parametrize("producer_kind", ["vault-alpha", "registry"])
def test_legacy_noncurrent_terminal_readback_never_replays(monkeypatch, tmp_path, producer_kind):
    from app.ops import native_source_identity_persistence as persistence, postgres_deploy_linux as linux

    controller = HostSecretController(tmp_path / "host")
    operation_id = str(uuid4())
    revision, digest = "a" * 40, "sha256:" + "b" * 64
    selected = AuthorityCutover("selection", "/private/source", "/private/owner")
    with controller.source_persistence_operation("dev", operation_id=operation_id,
                                                 producer_kind=producer_kind) as (op, _):
        op.prepare_mutation()
        op.finish(TerminalEvidence(operation_id, "source-persistence", "dev", "committed", "remote-terminal"))
    native_request = {
        "contract": ("native-source-identity-persistence-request.v3" if producer_kind == "registry"
                     else "native-source-identity-persistence-request.v2"),
        "operation_id": operation_id, "channel": "dev", "revision": revision, "image_digest": digest,
        "authority_cutover": {"binding_id": selected.binding_id, "root": selected.root,
                              "ownership_root": selected.ownership_root},
        "installed_fingerprint": "1" * 64, "execution_fingerprint": "2" * 64,
        "writers": ["api", "worker", "watcher"], "container_root": "/app/vault",
        "vault_overlay": "docker-compose.legacy-vault.yml",
    }
    if producer_kind == "registry":
        native_request["producer_kind"] = producer_kind
    receipt = persistence._receipt(operation_id, "dev", revision, persistence.IdentityInventory(0, 0, 0, 0, 0),
                                   producer_kind=producer_kind)
    available = {"request": native_request, "receipt": receipt}
    config = SimpleNamespace(channel="dev", root=tmp_path, journal=SimpleNamespace(directory=tmp_path))
    supervisor = linux.DeploymentSupervisor(config)
    supervisor._require_current_config = lambda: None
    lock = tmp_path / 'config/deploy/dev.env.lock'
    lock.mkdir(mode=0o700, parents=True)
    owner = {'kind': 'source-identity-persistence', 'channel': 'dev', 'operation_id': operation_id}
    if producer_kind == 'registry':
        owner['producer_kind'] = producer_kind
    owner_file = lock / 'bws-owner'
    owner_file.write_text(json.dumps(owner, sort_keys=True) + '\n')
    owner_file.chmod(0o600)
    runtime = SimpleNamespace(installed_fingerprint='1' * 64, container_root='/app/vault',
                              vault_overlay='docker-compose.legacy-vault.yml',
                              existing_writers=native_request['writers'], running_writers=[])
    calls = []
    monkeypatch.setattr(linux.LinuxEffects, 'qualify_source_identity_authority', lambda *_: None)
    monkeypatch.setattr(linux.LinuxEffects, 'source_identity_runtime_snapshot', lambda *_, **__: runtime)
    monkeypatch.setattr(linux.LinuxEffects, 'compose',
                        lambda self, *args, **kwargs: calls.append(args))
    from app.ops import native_source_bootstrap
    monkeypatch.setattr(native_source_bootstrap, 'quiesce_owned_container', lambda *_args, **_kwargs: True)

    def read_private(path):
        if path.name.endswith(".request.json"):
            return available["request"]
        return available["receipt"]

    actions = []

    def ssh_transport(argv, *, input, **_kwargs):
        assert argv[-3:] == ["/usr/local/libexec/yggdrasil-bws-deploy", "rpc", "dev"]
        payload = json.loads(input)
        actions.append(payload["action"])
        assert payload["action"] == "source-identity-persistence-readback"
        try:
            result = supervisor.request(payload)
        except PostgresDeployError:
            return SimpleNamespace(returncode=78, stdout="")
        return SimpleNamespace(returncode=0, stdout=json.dumps(result))

    monkeypatch.setattr(linux, "_private_json", read_private)
    monkeypatch.setattr(host, "HostSecretController", lambda: controller)
    monkeypatch.setattr(linux.subprocess, "run", ssh_transport)
    args = ["dev", revision, "--automatic", "--existing-secrets-only", "--persist-source-identity",
            "--operation-id", operation_id, "--image-digest", digest, "--source-producer-kind", producer_kind,
            "--authority-cutover-binding", "selection", "--authority-cutover-root", "/private/source",
            "--authority-cutover-ownership-root", "/private/owner"]
    changed = list(args)
    changed[changed.index("--image-digest") + 1] = "sha256:" + "c" * 64
    assert host.main(changed) == 78
    assert lock.is_dir()
    saved = available.pop("receipt")
    assert host.main(args) == 78
    assert lock.is_dir()
    available["receipt"] = saved
    assert host.main(args) == 0
    assert actions == ["source-identity-persistence-readback"] * 3
    assert calls == [('start', *native_request['writers'])]
    assert not lock.exists()
    assert "source_image_binding" not in (controller.directory / "operations.jsonl").read_text()


@pytest.mark.parametrize(('matching_owner', 'producer_exists', 'legacy_allowed'), [
    (True, False, True), (True, True, False), (False, False, False),
])
def test_terminal_readback_fences_retained_cleanup(monkeypatch, tmp_path, matching_owner,
                                                   producer_exists, legacy_allowed):
    from app.ops import native_source_bootstrap, native_source_identity_persistence as persistence
    from app.ops import postgres_deploy_linux as linux

    operation_id = str(uuid4())
    revision, digest = 'a' * 40, 'sha256:' + 'b' * 64
    selected = AuthorityCutover('selection', '/private/source', '/private/owner')
    request = {
        'contract': 'native-source-identity-persistence-request.v2',
        'operation_id': operation_id, 'channel': 'dev', 'revision': revision, 'image_digest': digest,
        'authority_cutover': {'binding_id': selected.binding_id, 'root': selected.root,
                              'ownership_root': selected.ownership_root},
        'installed_fingerprint': '1' * 64, 'execution_fingerprint': '2' * 64,
        'writers': ['api', 'worker', 'watcher'], 'container_root': '/app/vault',
        'vault_overlay': 'docker-compose.legacy-vault.yml',
    }
    receipt = persistence._receipt(operation_id, 'dev', revision, persistence.IdentityInventory(0, 0, 0, 0, 0),
                                    producer_error_count=1, reason='source_operation_conflict')
    lock = tmp_path / 'config/deploy/dev.env.lock'
    lock.mkdir(mode=0o700, parents=True)
    owner = {'kind': 'source-identity-persistence', 'channel': 'dev',
             'operation_id': operation_id if matching_owner else str(uuid4())}
    marker = lock / 'bws-owner'
    marker.write_text(json.dumps(owner, sort_keys=True) + '\n')
    marker.chmod(0o600)
    if producer_exists:
        (tmp_path / f'dev-source-identity-{operation_id}.producer.json').touch()
    monkeypatch.setattr(linux, '_private_json',
                        lambda path: request if path.name.endswith('.request.json') else receipt)
    runtime = SimpleNamespace(installed_fingerprint='1' * 64, container_root='/app/vault',
                              vault_overlay='docker-compose.legacy-vault.yml',
                              existing_writers=request['writers'], running_writers=[])
    effects = linux.LinuxEffects(SimpleNamespace(channel='dev', root=tmp_path,
                                                  journal=SimpleNamespace(directory=tmp_path)))
    monkeypatch.setattr(effects, 'qualify_source_identity_authority', lambda *_: None)
    monkeypatch.setattr(effects, 'source_identity_runtime_snapshot', lambda *_, **__: runtime)
    calls = []
    monkeypatch.setattr(effects, 'compose', lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(native_source_bootstrap, 'quiesce_owned_container', lambda *_args, **_kwargs: True)
    original = effects.reconcile_source_identity_cleanup
    flags = []

    def capture(*args, **kwargs):
        flags.append(kwargs['allow_legacy_mount_order'])
        return original(*args, **kwargs)

    monkeypatch.setattr(effects, 'reconcile_source_identity_cleanup', capture)
    assert effects.readback_source_identity(operation_id, revision, digest, selected, 'vault-alpha') == receipt
    assert flags == [legacy_allowed]
    assert lock.exists() is not matching_owner
    assert calls == ([('start', *request['writers'])] if matching_owner else [])
