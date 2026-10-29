"""The exact source CLI with real core/readers and temporary external targets."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import resource
import runpy
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.deploy.bws_fixture_support import bws_secure_tmp_path  # noqa: F401


def _exercise(base: Path, repository: Path, channel: str, fault: str) -> None:
    """Run in a disposable interpreter; no native configuration is consulted."""
    checkout = base / "candidate"
    checkout.mkdir(mode=0o755)
    for package in ("app", "scripts"):
        for source in (repository / package).rglob("*.py"):
            if "__pycache__" in source.parts:
                continue
            target = checkout / source.relative_to(repository)
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            target.chmod(0o755 if target.name == "postgres_deploy_service.py" else 0o644)
    contract = checkout / "config/secrets/host_secret_contract.json"
    contract.parent.mkdir(mode=0o755, parents=True)
    shutil.copyfile(repository / "config/secrets/host_secret_contract.json", contract)
    git_env = {**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
               "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
    for args in (("init", "-q"), ("add", "app", "scripts", "config"),
                 ("commit", "-qm", "synthetic source candidate")):
        subprocess.run(["git", "-C", str(checkout), *args], env=git_env, check=True)
    revision = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()

    script = checkout / "scripts/postgres_deploy_service.py"
    launcher = runpy.run_path(str(script))
    namespace = launcher["run"].__globals__
    namespace.update(__name__="__main__", _OWNER_UID=os.geteuid(), _OWNER_GID=os.getegid())
    binding, _source = namespace["_candidate_launcher_binding"](checkout, revision)
    setattr(sys, namespace["_VERIFIED_CANDIDATE_ENTRYPOINT"], binding)
    namespace["_candidate_checkout_root"] = lambda _sha: checkout
    namespace["_preimport_reservation"] = lambda *_args: namespace["_PreimportReservation"](None)
    real_loader = namespace["_install_source_loader"]
    state: dict[str, object] = {"events": []}

    def bind_effects(root):
        finder = real_loader(root)
        from app.ops import bws_control_installation as control
        from app.ops import bws_installation_admission as admission
        from app.ops import bws_installation_lifecycle as lifecycle
        from app.ops import bws_installation_transaction as transaction
        from app.ops import postgres_deploy_linux as linux
        from tests.ops.test_bws_installation_transaction import _ordinary_terminal_installation_fixture

        patch = pytest.MonkeyPatch()
        _ordinary_terminal_installation_fixture(base, patch, channel)
        config = linux.LinuxConfig.load(channel)
        installed = config.root
        state.update(config=config, installed=installed, transaction=transaction, control=control)
        for package in ("app", "scripts"):
            shutil.copytree(checkout / package, installed / package)
        (installed / "config/secrets").mkdir(mode=0o755, parents=True)
        shutil.copyfile(repository / "tests/ops/fixtures/host_secret_contract_legacy.json",
                        installed / "config/secrets/host_secret_contract.json")
        old_source = installed / "app/ops/bws_control_installation.py"
        old_source.write_bytes(b"# synthetic previous generation\n" + old_source.read_bytes())
        control_root, backups, launchers, receipts = (base / name for name in (
            "control", "backup", "launcher", "receipts",
        ))
        for directory in (control_root, backups, launchers, receipts):
            directory.mkdir(mode=0o755)
        public_launcher = launchers / "yggdrasil-bws-deploy"
        public_launcher.write_bytes(b"synthetic legacy launcher\n")
        public_launcher.chmod(0o755)
        runtime = base / "synthetic-runtime"
        runtime.write_bytes(b"synthetic runtime identity\n")
        runtime.chmod(0o755)
        transaction._OWNER_UID, transaction._OWNER_GID = os.geteuid(), os.getegid()
        transaction._CONTROL_DIRECTORY, transaction._BACKUP_DIRECTORY = control_root, backups
        transaction._LAUNCHER = public_launcher
        admission._OWNER_UID, admission._OWNER_GID = os.geteuid(), os.getegid()
        admission._RUNTIME_DIRECTORY = admission._RECEIPT_DIRECTORY = receipts
        admission._FIXED_RUNTIME, admission._FIXED_LAUNCHER = runtime, public_launcher
        lifecycle._public_launcher_bytes = public_launcher.read_bytes
        def private_target_directory(path):
            assert path == base or base in path.parents
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            return descriptor, os.fstat(descriptor)
        admission._open_directory = private_target_directory

        # Substitute native process metadata, not checkout/source/admission readers.
        real_stat = os.stat
        def observed_stat(path, *args, **kwargs):
            return real_stat(runtime if str(path) == "/proc/self/exe" else path, *args, **kwargs)
        os.stat = observed_stat
        command = b"\0".join(os.fsencode(value) for value in (str(runtime), str(script), "rpc", channel)) + b"\0"
        admission._proc_identity = lambda pid: {
            "pid": pid, "start_time": 123, "argv_sha256": admission._sha(command),
            "executable_sha256": "a" * 64,
        }
        lifecycle.require_no_cleanup_callers = lambda *_args, **_kwargs: state["events"].append("census")
        if sys.platform != "linux":
            real_listdir = os.listdir
            os.listdir = lambda path: ([str(os.getpid())] if path == "/proc/self/task" else real_listdir(path))

        real_command = linux._command
        def target_command(argv, **kwargs):
            if argv[1:3] == ["--host", "unix:///var/run/docker.sock"]:
                assert argv[3:5] == ["image", "inspect"]
                return json.dumps([{"Config": {"Labels": {"org.opencontainers.image.revision": revision}},
                                    "RepoDigests": [argv[-1]]}])
            return real_command(argv, **kwargs)
        linux._command = target_command
        # Emulate the privileged RPC boundary without changing the real UID used
        # by temporary file ownership checks in the transaction/file mechanic.
        linux.os = SimpleNamespace(**vars(os))
        linux.os.geteuid = lambda: 0
        def privileged_metadata(info):
            values = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
            return SimpleNamespace(**{**values, "st_uid": 0, "st_gid": 0})
        linux.os.fstat = lambda fd: privileged_metadata(os.fstat(fd))
        linux.os.stat = lambda *args, **kwargs: privileged_metadata(os.stat(*args, **kwargs))

        class Service:
            phase = "unqualified"
            runtime_context_started = runtime_close_completed = False
            old_token = "5" * 64
            contract = {"unit": "synthetic-external-unit"}
            control_inventory_empty = True
            def __init__(self, **_kwargs):
                state["events"].append("service")
                self.launcher_before = public_launcher.read_bytes()
            @contextmanager
            def retained_runtime(self):
                self.runtime_context_started = True
                descriptor = os.open(runtime, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    yield
                finally:
                    os.close(descriptor)
                    self.runtime_close_completed = True
                    state["events"].append("runtime_close")
            def qualify_old(self, **kwargs):
                assert kwargs["control_inventory_empty"] is True
                self.launcher_after = base64.b64decode(kwargs["launcher_content"]["base64"])
                self.phase = "qualified"
            def revalidate_empty_control_configuration(self):
                assert list(control_root.iterdir()) == []
            def require_old_kernel(self, *, launcher_content):
                assert public_launcher.read_bytes() == launcher_content
            def stop_old(self):
                self.phase = "stopped_checked"
                state["events"].append("stop")
            def require_stopped(self):
                assert self.phase in {"stopped_checked", "new_stopped_checked"}
            def start_new(self):
                self.phase = "start_requested"
                state["events"].append("start")
                if fault == "partial":
                    raise RuntimeError("synthetic external service start failure")
                permit = receipts / admission._start_authorization_name(channel)
                assert json.loads(permit.read_text())["operation_id"] == request["operation_id"]
                permit.unlink()
            def require_new_kernel(self):
                self.phase = "new_kernel_checked"
                return "6" * 64
            def require_same_new_kernel(self):
                assert self.phase == "new_kernel_checked"
            def stop_new(self):
                self.phase = "new_stopped_checked"
            def stop_failed_start_if_exact(self):
                self.phase = "new_stopped_checked"
        lifecycle.FixedBwsService = Service

        # The remote service profile is an external observation. Its actual disk
        # inventory, source-only loader, current contract parser and final reader
        # stay real and independently reject drift.
        def supervisor_rpc(selected_channel, selected):
            assert selected_channel == channel and selected["action"] == "source-installation-profile"
            profile = transaction.loaded_source_profile(
                SimpleNamespace(channel=channel, root=checkout), operation_id=request["operation_id"],
                candidate_sha=revision, image_digest=request["image_digest"],
                caller_source_modules=selected.get("caller_source_modules"),
            )
            profile["roots"]["application"] = transaction._root_identity(installed)
            canonical = {key: value for key, value in profile.items() if key != "profile_sha256"}
            profile["profile_sha256"] = transaction._sha(json.dumps(
                canonical, sort_keys=True, separators=(",", ":"),
            ).encode("ascii"))
            return {"source_installation_profile": profile, "supervisor_idle": True,
                    "exec_stop_post_no_write": True}
        linux._rpc_via_supervisor = supervisor_rpc

        # Only this disposable child receives a finite synthetic resource ceiling.
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 512 if fault == "hard" else 8192))
        state["original_limits"] = resource.getrlimit(resource.RLIMIT_NOFILE)
        if fault == "unknown":
            control._source_descriptor_capacity_snapshot = lambda: None
        if fault == "prepare-interrupt":
            def interrupt_backup(*_args):
                raise KeyboardInterrupt()
            control._backup = interrupt_backup
        state.update(backups=backups, receipts=receipts)
        return finder

    namespace["_install_source_loader"] = bind_effects
    request = {"action": "source-installation", "operation_id": "65752d22-1a9b-48df-a0cc-5e1087595b22",
               "candidate_sha": revision, "image_digest": "sha256:" + "b" * 64, "bundle_name": "assembled"}
    # run() still reads its root-owned configuration boundary, sets cwd, ignores
    # bytecode and dispatches the exact verified candidate before native imports.
    installed_root = base / "checkout"
    config_file = base / "launcher.json"
    config_file.write_text(json.dumps({"root": str(installed_root)}))
    config_file.chmod(0o600)
    installed_root.mkdir(mode=0o755)
    real_open, real_fstat = os.open, os.fstat
    config_descriptors = set()
    def open_target(path, flags, *args, **kwargs):
        if str(path) == f"/etc/yggdrasil/bws-deploy/{channel}.json":
            descriptor = real_open(config_file, flags, *args, **kwargs)
            config_descriptors.add(descriptor)
            return descriptor
        return real_open(path, flags, *args, **kwargs)
    def root_config_stat(descriptor):
        info = real_fstat(descriptor)
        if descriptor in config_descriptors and info.st_ino == config_file.stat().st_ino:
            return SimpleNamespace(st_uid=0, st_mode=info.st_mode)
        return info
    class LauncherPath(type(Path())):
        def stat(self, *args, **kwargs):
            info = super().stat(*args, **kwargs)
            if str(self) == str(installed_root):
                return SimpleNamespace(st_uid=0, st_mode=info.st_mode)
            return info
    os.open, os.fstat, namespace["Path"] = open_target, root_config_stat, LauncherPath
    sys.argv = [str(script), "rpc", channel]
    sys.stdin, output = io.StringIO(json.dumps(request)), io.StringIO()
    sys.stdout = output
    status = namespace["run"]()
    assert status == 0, (status, output.getvalue())
    result = json.loads(output.getvalue())["source_installation"]
    assert resource.getrlimit(resource.RLIMIT_NOFILE) == state["original_limits"]
    assert not hasattr(sys, "_yggdrasil_bws_source_rpc_process")
    if fault in {"hard", "unknown"}:
        assert result["status"] == "refused_before_backup", result
        assert result["prebackup_gate"] == ("descriptor_capacity_insufficient" if fault == "hard"
                                             else "descriptor_capacity_unknown")
        assert not {"service", "stop", "start"} & set(state["events"])
        assert list(state["backups"].iterdir()) == []
    else:
        assert result["status"] == ("compensated_stopped" if fault == "partial" else "installed"), result
        assert state["events"].index("service") < state["events"].index("stop")
        assert state["events"][-1] == "runtime_close"
        assert (state["backups"] / "assembled/manifest.json").exists()
    receipt_name = "bws-source-installation-" + request["operation_id"] + ".receipt.json"
    receipt = json.loads((state["receipts"] / receipt_name).read_text())
    assert receipt == result
    sys.stdout = sys.__stdout__
    print(json.dumps({"status": result["status"], "restored": True, "source_only": sys.pycache_prefix == "/dev/null"}))


@pytest.mark.parametrize("channel", ["dev", "test"])
@pytest.mark.parametrize("fault", ["none", "hard", "unknown", "partial", "prepare-interrupt"])
def test_assembled_source_rpc_uses_real_descriptor_envelope(secure_tmp_path, channel, fault):
    completed = subprocess.run(
        [sys.executable, "-m", "tests.deploy.test_bws_source_rpc_assembly", str(secure_tmp_path),
         str(Path(__file__).resolve().parents[2]), channel, fault],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=90,
    )
    if fault == "prepare-interrupt":
        assert completed.returncode == 78, completed.stderr
        assert completed.stdout == ""
        return
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["restored"] is True and result["source_only"] is True


if __name__ == "__main__":
    _exercise(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4])
