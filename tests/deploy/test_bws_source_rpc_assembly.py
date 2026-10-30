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
import tempfile
import traceback
from types import SimpleNamespace

import pytest

from tests.deploy.bws_fixture_support import bws_secure_tmp_path  # noqa: F401


_ROOT_RPC_BATCHES = {'empty': 5, 'anchored': 4, 'alias': 1, 'proposed': 1, 'uncertain': 1}


def _exercise(base: Path, repository: Path, channel: str, fault: str, journal_root: Path,
              batch: int | None = None) -> None:
    """Run in a disposable interpreter; no native configuration is consulted."""
    # Keep actual Git commands/bytes/readers on macOS, using a regular stdin
    # file for the external batch transport after observing blocked pipe writes.
    if sys.platform == 'darwin':
        native_run = subprocess.run
        def git_transport(argv, **kwargs):
            if argv[-2:] == ['cat-file', '--batch'] and 'input' in kwargs:
                raw = kwargs.pop('input')
                with tempfile.TemporaryFile() as incoming:
                    incoming.write(raw)
                    incoming.seek(0)
                    return native_run(argv, stdin=incoming, **kwargs)
            return native_run(argv, **kwargs)
        subprocess.run = git_transport
    # Secure public-source fixtures can live inside the checkout on CI. Model
    # that ancestry on every platform; private durable journals must stay outside.
    (base / ".git").mkdir(mode=0o700)
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
    if fault == 'root-matrix-proposed':
        # A genuine exact Git launcher whose supported code is unchanged but
        # whose bytes carry a forbidden empty-topology hint. No payload shim.
        candidate_launcher = checkout / 'scripts/postgres_deploy_service.py'
        candidate_launcher.write_bytes(candidate_launcher.read_bytes()
                                       + b'\n# synthetic support hint: ' + str(base / 'control').encode() + b'\n')
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
    if not fault.startswith('root-'):
        namespace["_candidate_checkout_root"] = lambda _sha: checkout
    namespace["_preimport_reservation"] = lambda *_args: namespace["_PreimportReservation"](None)
    real_loader = namespace["_install_source_loader"]
    state: dict[str, object] = {"events": []}

    def bind_effects(root):
        finder = real_loader(root)
        if state.get('bound'):
            return finder
        from app.ops import bws_control_installation as control
        from app.ops import bws_installation_admission as admission
        from app.ops import bws_installation_lifecycle as lifecycle
        from app.ops import bws_installation_transaction as transaction
        from app.ops import postgres_deploy_linux as linux
        from tests.ops.test_bws_installation_transaction import _ordinary_terminal_installation_fixture

        patch = pytest.MonkeyPatch()
        _ordinary_terminal_installation_fixture(base, patch, channel, journal_root=journal_root)
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
        if fault.startswith('root-matrix'):
            from tests.ops.test_bws_installation_lifecycle import configure_root_control_rpc
            anchored = fault.endswith('anchored')
            if fault.endswith('alias'):
                control_root = installed
                transaction._CONTROL_DIRECTORY = installed
            if anchored:
                shutil.copytree(checkout / 'app', control_root / 'app')
            state['root_fixture'] = configure_root_control_rpc(
                lifecycle, transaction, state, control_root, installed, runtime, public_launcher,
                channel, anchored=anchored,
            )
        elif fault.startswith('path-'):
            from tests.ops.test_bws_installation_lifecycle import configure_control_path_service
            slot_kind = fault.removeprefix('path-')
            slot = control_root if slot_kind == 'root' else control_root / (
                'absent/deeper' if slot_kind == 'absent' else 'lookup')
            if slot_kind not in {'root', 'absent'}:
                slot.mkdir(mode=0o755)
            (control_root / 'unrelated.txt').write_bytes(b'preserved synthetic non-executable data')
            (control_root / 'unrelated.txt').chmod(0o644)
            environment = ['LLM_PROVIDER=mock', f'PATH=/usr/bin:{slot}:/bin', 'EXACT=value with spaces']
            state['path_properties'] = configure_control_path_service(
                lifecycle, patch, state, control_root, installed, runtime, public_launcher, channel, environment,
            )
            state['path_environment'] = list(environment)
            def consume_start():
                permit = receipts / admission._start_authorization_name(channel)
                assert json.loads(permit.read_text())['operation_id'] == request['operation_id']
                permit.unlink()
            state['consume_start'] = consume_start
            if fault in {'path-close', 'path-transient-initial', 'path-transient-prebackup'}:
                original_close = lifecycle.os.close
                def uncertain_close(fd):
                    binding = getattr(state.get('service'), 'control_path_binding', None)
                    owned = binding is not None and (
                        (fault == 'path-close' and binding.closed and any(
                            record[0] == fd for record in binding.fds.values()))
                        or (fault == 'path-transient-initial' and binding.snapshot is None)
                        or (fault == 'path-transient-prebackup' and binding.snapshot is not None and not binding.closed)
                    )
                    original_close(fd)
                    if owned and not state.get('close_failed'):
                        state['close_failed'] = True
                        raise OSError('synthetic original close uncertainty')
                patch.setattr(lifecycle.os, 'close', uncertain_close)
            if fault == 'path-effect-alias':
                target_info = (installed / 'app/ops').stat()
                original_mount = lifecycle._control_path_mount
                def mounted_target(fd):
                    info = lifecycle.os.fstat(fd)
                    mount = original_mount(fd)
                    return mount + 1 if (info.st_dev, info.st_ino) == (target_info.st_dev, target_info.st_ino) else mount
                patch.setattr(lifecycle, '_control_path_mount', mounted_target)
            real_service = transaction._NativePorts.service
            def service(ports, selected_channel):
                value = real_service(ports, selected_channel)
                state['service'] = value
                state['events'].append('service')
                return value
            patch.setattr(transaction._NativePorts, 'service', service)
            original_prepare = transaction._NativePorts.prepare
            def prepare(ports, *args, **kwargs):
                try:
                    return original_prepare(ports, *args, **kwargs)
                except Exception as failure:
                    state['prepare_failure'] = (type(failure).__name__, getattr(failure, 'reason', None),
                        [(Path(frame.filename).name, frame.name, frame.lineno)
                         for frame in traceback.extract_tb(failure.__traceback__)[-6:]])
                    raise
            patch.setattr(transaction._NativePorts, 'prepare', prepare)
            state['old_source'] = old_source.read_bytes()
            state['old_launcher'] = public_launcher.read_bytes()
        else:
            lifecycle.FixedBwsService = Service

        # The remote service profile is an external observation. Its actual disk
        # inventory, source-only loader, current contract parser and final reader
        # stay real and independently reject drift.
        def supervisor_rpc(selected_channel, selected):
            assert selected_channel == channel and selected["action"] == "source-installation-profile"
            if fault == 'path-partial' and 'start' in state['events']:
                raise RuntimeError('synthetic external profile unavailable')
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
            state['last_profile'] = profile
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
        state.update(backups=backups, receipts=receipts, bound=True, control_root=control_root)
        return finder

    def guarded_bind_effects(root):
        try:
            return bind_effects(root)
        except Exception as exc:
            # Launcher refusals are deliberately value-free. Keep test failure
            # diagnosis value-free too: no exception message, paths or inputs.
            state["bootstrap_failure"] = (
                type(exc).__name__,
                [(Path(frame.filename).name, frame.name, frame.lineno)
                 for frame in traceback.extract_tb(exc.__traceback__)[-6:]],
            )
            raise
    namespace["_install_source_loader"] = guarded_bind_effects
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
    if fault.startswith('root-matrix'):
        import uuid
        # Bootstrap binds ports once, retaining every original source reader.
        # A real loader is still installed at each subsequent verified run.
        sys.path.insert(0, str(checkout))
        sys.dont_write_bytecode = True
        sys.pycache_prefix = '/dev/null'
        bootstrap_finder = guarded_bind_effects(checkout)
        sys.meta_path.remove(bootstrap_finder)
        from tests.ops.test_bws_installation_lifecycle import root_control_rpc_cases
        from app.ops import bws_installation_admission as admission
        cases = root_control_rpc_cases(state['control_root'], anchored=fault.endswith('anchored'))
        if fault.endswith('proposed'):
            cases = [dict(expected=('captured_empty', 'proposed', 'hints', 'launcher_hint'), stage='initial')]
        if fault.endswith('uncertain'):
            cases = [dict(runtime_close_failure=True,
                          os_fault=dict(operation='fstat', path=str(state['control_root']), occurrence=0,
                                        change={'st_mode': 0o100644}),
                          expected_gate='old_kernel_initial_retained_runtime')]
        if fault.endswith('alias'):
            cases = [dict(expected=('anchored_discovery', 'unknown', 'roots', 'separation'), stage='initial')]
        total_cases = len(cases)
        mode = fault.removeprefix('root-matrix-')
        batch_count = _ROOT_RPC_BATCHES[mode]
        # Disjoint strides partition the unchanged semantic case list exactly.
        # Bound each actual subprocess group under CI's unchanged 120s timer;
        # the existing child timeout remains 600s as its cleanup backstop.
        case_indices = list(range(total_cases))
        if batch is not None:
            assert 0 <= batch < batch_count
            groups = [set(range(i, total_cases, batch_count)) for i in range(batch_count)]
            assert set.union(*groups) == set(range(total_cases))
            assert sum(map(len, groups)) == total_cases
            case_indices = list(range(batch, total_cases, batch_count))
            cases = [cases[i] for i in case_indices]
            assert 1 <= len(cases) <= 15
        proved = set()
        for index, case in enumerate(cases):
            request['operation_id'] = str(uuid.uuid4())
            state['root_fixture']['prepare'](case)
            sys.stdin, output = io.StringIO(json.dumps(request)), io.StringIO()
            sys.stdout = output
            status = namespace['run']()
            assert status == 0, (index, case.get('expected'), status, output.getvalue())
            result = json.loads(output.getvalue())['source_installation']
            expected = case.get('expected_gate') or (
                'old_kernel_' + case['stage'] + '_root_control__' + '__'.join(case['expected'])
            )
            assert result['status'] == 'refused_before_backup', (index, result)
            assert result['prebackup_gate'] == expected, (index, case.get('expected'), result)
            assert all(result[key] is None for key in (
                'old_generation_sha256', 'new_generation_sha256', 'backup_manifest_sha256',
            ))
            kernel = state['root_fixture']['kernel']
            assert not kernel.fds and not kernel.runtime_fds
            if case.get('os_fault'):
                assert kernel.fired, (index, case)
            if case.get('positive') or case.get('stage') == 'empty_control':
                assert state['root_fixture']['after_qualification']
            assert not list(state['backups'].iterdir())
            owner = admission._owner_record((state['receipts'] / (channel + '.source-installation.lock')).read_bytes(), channel)
            assert owner['operation_id'] == request['operation_id']
            assert admission._terminal_receipt(owner) == result
            receipt_name = 'bws-source-installation-' + request['operation_id'] + '.receipt.json'
            receipt = json.loads((state['receipts'] / receipt_name).read_text())
            assert receipt == result
            assert admission._receipt_generations(result['status'], None, None, None,
                                                  prebackup_gate_present=True, prebackup_gate=expected)
            assert 'PRIVATE_CANARY' not in output.getvalue()
            assert resource.getrlimit(resource.RLIMIT_NOFILE) == state['original_limits']
            proved.add(expected)
        terminal_files = {p.name: p.read_bytes() for p in state['receipts'].iterdir()}
        original_request = dict(request)
        marker = getattr(sys, namespace['_VERIFIED_CANDIDATE_ENTRYPOINT'])
        for binding_fault in ('replay', 'candidate', 'marker', 'dirty'):
            request = dict(original_request)
            if binding_fault == 'candidate':
                request['candidate_sha'] = 'f' * 40
            elif binding_fault == 'marker':
                setattr(sys, namespace['_VERIFIED_CANDIDATE_ENTRYPOINT'], {**marker, 'script_sha256': 'f' * 64})
            elif binding_fault == 'dirty':
                script.write_bytes(script.read_bytes() + b'\n# PRIVATE_CANARY uncommitted\n')
            sys.stdin, output = io.StringIO(json.dumps(request)), io.StringIO()
            sys.stdout = output
            assert namespace['run']() != 0
            assert 'PRIVATE_CANARY' not in output.getvalue()
            assert {p.name: p.read_bytes() for p in state['receipts'].iterdir()} == terminal_files
            setattr(sys, namespace['_VERIFIED_CANDIDATE_ENTRYPOINT'], marker)
        sys.stdout = sys.__stdout__
        print(json.dumps(dict(status='matrix', cases=len(cases), total_cases=total_cases, case_indices=case_indices,
                              guards=len(proved), restored=True,
                              source_only=sys.pycache_prefix == '/dev/null')))
        return
    status = namespace["run"]()
    assert status == 0, (status, output.getvalue(), state.get("bootstrap_failure"))
    result = json.loads(output.getvalue())["source_installation"]
    assert resource.getrlimit(resource.RLIMIT_NOFILE) == state["original_limits"]
    assert not hasattr(sys, "_yggdrasil_bws_source_rpc_process")
    if fault in {"hard", "unknown"}:
        assert result["status"] == "refused_before_backup", result
        assert result["prebackup_gate"] == ("descriptor_capacity_insufficient" if fault == "hard"
                                             else "descriptor_capacity_unknown")
        assert not {"service", "stop", "start"} & set(state["events"])
        assert list(state["backups"].iterdir()) == []
    elif fault == 'path-effect-alias':
        assert result['status'] == 'refused_before_backup'
        assert result['prebackup_gate'] == 'old_kernel_initial_root_control'
        assert state['events'].count('stop') == state['events'].count('start') == 0
        assert not list(state['backups'].iterdir())
        assert state['service'].runtime_close_completed
        assert not state['service'].control_path_binding.fds
    elif fault.startswith('path-'):
        service = state['service']
        assert result['status'] == ('compensated_stopped' if fault == 'path-partial' else 'installed'), (result, state.get('prepare_failure'))
        assert service.runtime_close_completed and service.control_path_binding.closed
        assert not service.control_path_binding.fds
        assert state['path_properties']['Service', 'Environment'] == state['path_environment']
        assert service.contract[2] == tuple(state['path_environment'])
        assert (state['control_root'] / 'unrelated.txt').read_bytes() == b'preserved synthetic non-executable data'
        assert not (state['control_root'] / 'app').exists() and not (state['control_root'] / 'scripts').exists()
        manifest = json.loads((state['backups'] / 'assembled/manifest.json').read_text())
        assert all(row['root'] != 'control' for row in manifest)
        if fault == 'path-partial':
            assert (state['installed'] / 'app/ops/bws_control_installation.py').read_bytes() == state['old_source']
            assert (base / 'launcher/yggdrasil-bws-deploy').read_bytes() == state['old_launcher']
            assert state['events'].count('start') == 1
            assert service.phase == 'new_stopped_checked'
        else:
            assert result['new_generation_sha256'] == state['transaction']._generation_sha(
                state['last_profile'], service.new_token, service.contract,
            )
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
    with tempfile.TemporaryDirectory(prefix="pkm-source-journal-") as directory:
        completed = subprocess.run(
            [sys.executable, "-m", "tests.deploy.test_bws_source_rpc_assembly", str(secure_tmp_path),
             str(Path(__file__).resolve().parents[2]), channel, fault, str(Path(directory).resolve())],
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=90,
        )
    if fault == "prepare-interrupt":
        assert completed.returncode == 78, completed.stderr
        assert completed.stdout == ""
        return
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["restored"] is True and result["source_only"] is True


@pytest.mark.parametrize("channel", ["dev", "test"])
@pytest.mark.parametrize("mode,batch", [(mode, batch) for mode, count in _ROOT_RPC_BATCHES.items()
                                        for batch in range(count)])
def test_root_control_leaf_diagnostics_cross_verified_source_rpc(secure_tmp_path, channel, mode, batch):
    with tempfile.TemporaryDirectory(prefix="pkm-source-journal-") as directory:
        completed = subprocess.run(
            [sys.executable, "-m", "tests.deploy.test_bws_source_rpc_assembly", str(secure_tmp_path),
             str(Path(__file__).resolve().parents[2]), channel, 'root-matrix-' + mode,
             str(Path(directory).resolve()), str(batch)],
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=600,
        )
    if mode == 'uncertain':
        assert completed.returncode == 78 and completed.stdout == '', completed.stderr
        owner = json.loads((secure_tmp_path / 'receipts' / (channel + '.source-installation.lock')).read_text())
        assert owner['operation_id']
        return
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result['restored'] and result['source_only']
    assert result['total_cases'] >= (40 if mode in {'empty', 'anchored'} else 1)
    assert 1 <= result['cases'] <= 15
    assert result['case_indices'] == list(range(batch, result['total_cases'], _ROOT_RPC_BATCHES[mode]))


@pytest.mark.parametrize('channel', ['dev', 'test'])
@pytest.mark.parametrize('slot', ['root', 'descendant', 'absent'])
def test_control_path_slots_complete_real_source_transaction(secure_tmp_path, channel, slot):
    exercise_control_path_transaction(secure_tmp_path, channel, slot)


def exercise_control_path_transaction(base, channel, slot):
    with tempfile.TemporaryDirectory(prefix='pkm-source-journal-') as directory:
        completed = subprocess.run(
            [sys.executable, '-m', 'tests.deploy.test_bws_source_rpc_assembly', str(base),
             str(Path(__file__).resolve().parents[2]), channel, 'path-' + slot, str(Path(directory).resolve())],
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=90,
        )
    if slot in {'close', 'transient-initial', 'transient-prebackup'}:
        assert completed.returncode == 78 and completed.stdout == '', completed.stderr
        owner = json.loads((base / 'receipts' / (channel + '.source-installation.lock')).read_text())
        assert owner['operation_id']
        assert not list((base / 'receipts').glob('*.receipt.json'))
        return {'status': 'unknown'}
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result['restored'] and result['source_only']
    return result


if __name__ == "__main__":
    _exercise(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4], Path(sys.argv[5]),
              int(sys.argv[6]) if len(sys.argv) > 6 else None)
