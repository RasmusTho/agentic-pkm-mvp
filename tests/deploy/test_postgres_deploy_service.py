from __future__ import annotations

import io
import hashlib
import json
import os
from pathlib import Path
import sys
from contextlib import nullcontext
from types import ModuleType, SimpleNamespace

import pytest

from app.ops import postgres_deploy as deploy
from app.ops import postgres_deploy_linux as linux
from scripts import postgres_deploy_service as service
from tests.deploy.bws_fixture_support import bws_secure_tmp_path  # noqa: F401


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('channel', ['dev', 'test'])
def test_service_establishes_canonical_cwd_before_native_validation(tmp_path, monkeypatch, capsys, channel):
    root = tmp_path / 'checkout'
    contract = root / 'config/secrets/host_secret_contract.json'
    contract.parent.mkdir(parents=True)
    contract.write_bytes((ROOT / 'config/secrets/host_secret_contract.json').read_bytes())
    pin = root / 'config/deploy' / (channel + '.env')
    pin.parent.mkdir()
    pin.write_text(f'DATABASE_URL=postgresql://app@db:5432/app_{channel}\n')
    runtime = root / 'runtime.env'
    runtime.write_text('')
    config = tmp_path / 'service.json'
    config.write_text(json.dumps({'root': str(root)}))
    config.chmod(0o600)
    root.chmod(0o755)
    unrelated = tmp_path / 'elsewhere'
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    assert not (unrelated / 'config').exists()
    monkeypatch.setattr(os, 'environ', {
        'HOME': str(tmp_path), 'XDG_STATE_HOME': str(tmp_path / 'state'), 'PATH': os.defpath,
    })
    monkeypatch.setattr(service.sys, 'path', list(service.sys.path))
    monkeypatch.setattr(service.sys, 'argv', ['yggdrasil-bws-deploy', 'rpc', channel])
    monkeypatch.setattr(service, '_preimport_reservation',
                        lambda _channel, _action: service._PreimportReservation(None))
    monkeypatch.setattr(service, '_install_source_loader', lambda _root: None)
    from app.ops import bws_installation_admission
    monkeypatch.setattr(bws_installation_admission, 'shared_caller_reservation',
                        lambda _channel: nullcontext())
    plan = deploy.DeployPlan(channel, 'a' * 40, ('db',), ('postgres-db',),
                             image_digest='sha256:' + 'b' * 64, automatic=True)
    monkeypatch.setattr(service.sys, 'stdin', io.StringIO(json.dumps({'plan': plan.payload()})))
    cfg = linux.LinuxConfig(channel, root, tmp_path / 'data', 1000, 1000,
                            'c' * 32, 'd' * 32, runtime)

    # Only privileged file metadata and the socket/Compose transports are fake.
    # The public contract reader, plan validation, native main/rpc and environment
    # construction remain real, including environment's second plan validation.
    real_open, real_fstat, real_stat = os.open, os.fstat, Path.stat

    def open_config(path, flags):
        if path == runtime:
            return real_open(path, flags)
        assert path == Path('/etc/yggdrasil/bws-deploy') / (channel + '.json')
        assert flags == os.O_RDONLY | os.O_NOFOLLOW
        return real_open(config, flags)

    def root_owned_stat(path, *args, **kwargs):
        info = real_stat(path, *args, **kwargs)
        if path == root:
            return SimpleNamespace(st_uid=0, st_mode=info.st_mode)
        return info

    monkeypatch.setattr(service.os, 'open', open_config)
    monkeypatch.setattr(service.os, 'fstat', lambda fd: SimpleNamespace(st_uid=0, st_mode=real_fstat(fd).st_mode))
    monkeypatch.setattr(Path, 'stat', root_owned_stat)
    monkeypatch.setattr(linux.os, 'geteuid', lambda: 0)
    contract_reads = []
    real_contract_reader = deploy.load_host_secret_contract

    def read_contract():
        contract_reads.append(Path.cwd())
        return real_contract_reader()

    monkeypatch.setattr(deploy, 'load_host_secret_contract', read_contract)
    commands = []

    def command(argv, **kwargs):
        commands.append((argv, kwargs))
        assert Path.cwd() == kwargs['cwd'] == root
        assert kwargs['env']['APP_IMAGE_TAG'] == plan.revision
        assert kwargs['env']['APP_IMAGE_DIGEST_SUFFIX'] == '@' + plan.image_digest
        assert kwargs['env']['BWS_DATABASE_NAME'] == 'app_' + channel
        return '{}'

    monkeypatch.setattr(linux, '_command', command)

    class SocketTransport:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def settimeout(self, timeout):
            assert timeout == 35

        def connect(self, path):
            assert path == f'/run/yggdrasil/bws-deploy/{channel}.sock'

        def makefile(self, mode):
            assert mode == 'rwb'
            return self

        def write(self, raw):
            self.request = json.loads(raw)

        def flush(self):
            candidate = deploy.DeployPlan.from_payload(self.request['plan'])
            linux.LinuxEffects(cfg).compose('config', candidate=candidate)

        def readline(self, limit):
            assert limit == 65537
            return b'{"accepted":true}\n'

    monkeypatch.setattr(linux.socket, 'socket', lambda *_args: SocketTransport())
    assert service.run() == 0
    assert contract_reads == [root, root]
    assert len(commands) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {'accepted': True}
    assert captured.err == ''


def test_fixed_launcher_holds_shared_reservation_before_replaceable_import(tmp_path):
    root = tmp_path / 'checkout'
    package = root / 'app/ops'
    package.mkdir(parents=True)
    (root / 'app/__init__.py').write_text('"""Synthetic package."""\n')
    (package / '__init__.py').write_text('"""Synthetic ops package."""\n')
    source = package / 'postgres_deploy_linux.py'
    source.write_text(
        'import fcntl, os\n'
        'fd = os.open(os.environ["LOCK_PROBE_PATH"], os.O_RDWR)\n'
        'try:\n'
        '    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n'
        'except BlockingIOError:\n'
        '    IMPORT_RESERVED = True\n'
        'else:\n'
        '    IMPORT_RESERVED = False\n'
        '    fcntl.flock(fd, fcntl.LOCK_UN)\n'
        'os.close(fd)\n'
        'def main(arguments):\n'
        '    return 0\n'
    )
    state_parent = tmp_path / 'state'
    state_parent.mkdir()
    code = r'''
import fcntl, importlib.util, os, sys
from pathlib import Path
repository, root, state_parent = map(Path, sys.argv[1:])
sys.path.insert(0, str(repository))
from scripts import postgres_deploy_service as service
service._RESERVATION_DIRECTORY = state_parent / 'convergence'
service._OWNER_UID = os.getuid()
service._OWNER_GID = os.getgid()
service._open_owned_directory = lambda path: os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
sys.pycache_prefix = '/dev/null'
sys.dont_write_bytecode = True
lock_path = service._RESERVATION_DIRECTORY / service._GLOBAL_LOCK_NAME
os.environ['LOCK_PROBE_PATH'] = str(lock_path)
sys.path.insert(0, str(root))
assert service._dispatch(root, 'dev', ['guard', 'dev']) == 0
module = sys.modules['app.ops.postgres_deploy_linux']
assert module.IMPORT_RESERVED is True
fd = os.open(lock_path, os.O_RDWR)
fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
fcntl.flock(fd, fcntl.LOCK_UN)
os.close(fd)
'''
    result = __import__('subprocess').run(
        [sys.executable, '-c', code, str(ROOT), str(root), str(state_parent)],
        cwd=ROOT, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_fixed_launcher_preloads_exact_transaction_before_releasing_reservation(tmp_path):
    root = tmp_path / 'checkout'
    package = root / 'app/ops'
    package.mkdir(parents=True)
    (root / 'app/__init__.py').write_text('"""Synthetic package."""\n')
    (package / '__init__.py').write_text('"""Synthetic ops package."""\n')
    (package / 'bws_installation_admission.py').write_text(
        'import fcntl, os\n'
        'fd = os.open(os.environ["LOCK_PROBE_PATH"], os.O_RDWR)\n'
        'try:\n'
        '    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n'
        'except BlockingIOError:\n'
        '    IMPORT_RESERVED = True\n'
        'else:\n'
        '    IMPORT_RESERVED = False\n'
        '    fcntl.flock(fd, fcntl.LOCK_UN)\n'
        'os.close(fd)\n'
    )
    (package / 'bws_installation_transaction.py').write_text(
        'import fcntl, os\n'
        'fd = os.open(os.environ["LOCK_PROBE_PATH"], os.O_RDWR)\n'
        'try:\n'
        '    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n'
        'except BlockingIOError:\n'
        '    IMPORT_RESERVED = True\n'
        'else:\n'
        '    IMPORT_RESERVED = False\n'
        '    fcntl.flock(fd, fcntl.LOCK_UN)\n'
        'def run_source_installation(channel, request):\n'
        '    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n'
        '    fcntl.flock(fd, fcntl.LOCK_UN)\n'
        '    return {"accepted": True}\n'
    )
    (package / 'postgres_deploy_linux.py').write_text(
        'import json, sys\n'
        'def main(arguments):\n'
        '    request = json.load(sys.stdin)\n'
        '    from app.ops.bws_installation_transaction import run_source_installation\n'
        '    return 0 if run_source_installation(arguments[1], request)["accepted"] else 78\n'
    )
    state_parent = tmp_path / 'state'
    state_parent.mkdir()
    code = r'''
import json, os, sys, uuid
from pathlib import Path
repository, root, state_parent = map(Path, sys.argv[1:])
sys.path.insert(0, str(repository))
from scripts import postgres_deploy_service as service
service._RESERVATION_DIRECTORY = state_parent / 'convergence'
service._OWNER_UID = os.getuid()
service._OWNER_GID = os.getgid()
service._open_owned_directory = lambda path: os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
service._candidate_checkout_root = lambda _candidate_sha: root
binding = {'candidate_sha':'a'*40,'checkout':str(root),'script_sha256':'c'*64}
service._candidate_launcher_binding = lambda *_args: (binding, b'exact candidate launcher')
setattr(sys, service._VERIFIED_CANDIDATE_ENTRYPOINT, binding)
sys.pycache_prefix = '/dev/null'
sys.dont_write_bytecode = True
lock_path = service._RESERVATION_DIRECTORY / service._GLOBAL_LOCK_NAME
os.environ['LOCK_PROBE_PATH'] = str(lock_path)
sys.path.insert(0, str(root))
request = {'action':'source-installation','operation_id':str(uuid.uuid4()),
           'candidate_sha':'a'*40,'image_digest':'sha256:'+'b'*64,'bundle_name':'synthetic'}
sys.stdin = __import__('io').StringIO(json.dumps(request))
assert service._dispatch(root, 'dev', ['rpc', 'dev'], caller_checkout=root) == 0
assert sys.modules['app.ops.bws_installation_transaction'].IMPORT_RESERVED is True
assert sys.modules['app.ops.bws_installation_admission'].IMPORT_RESERVED is True
'''
    result = __import__('subprocess').run(
        [sys.executable, '-c', code, str(ROOT), str(root), str(state_parent)],
        cwd=ROOT, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_candidate_rpc_checkout_requires_exact_clean_head(secure_tmp_path, monkeypatch):
    from app.ops import bws_installation_admission

    secure_tmp_path.chmod(0o750)
    checkout = secure_tmp_path / 'candidate'
    script = checkout / 'scripts' / 'postgres_deploy_service.py'
    application = checkout / 'app' / 'ops'
    application.mkdir(parents=True)
    script.parent.mkdir(parents=True)
    contract = checkout / 'config' / 'secrets' / 'host_secret_contract.json'
    contract.parent.mkdir(parents=True)
    script.write_bytes((ROOT / 'scripts/postgres_deploy_service.py').read_bytes())
    script.chmod(0o755)
    contract.write_bytes((ROOT / 'config/secrets/host_secret_contract.json').read_bytes())
    (application / 'postgres_deploy_linux.py').write_text('VALUE = 1\n')
    env = {
        **os.environ, 'GIT_AUTHOR_NAME': 'test', 'GIT_AUTHOR_EMAIL': 'test@example.invalid',
        'GIT_COMMITTER_NAME': 'test', 'GIT_COMMITTER_EMAIL': 'test@example.invalid',
    }
    __import__('subprocess').run(['git', 'init', '-q', str(checkout)], check=True, env=env)
    __import__('subprocess').run(['git', '-C', str(checkout), 'add', 'app', 'scripts', 'config'], check=True, env=env)
    __import__('subprocess').run(['git', '-C', str(checkout), 'commit', '-q', '-m', 'candidate'],
                                 check=True, env=env)
    revision = __import__('subprocess').run(
        ['git', '-C', str(checkout), 'rev-parse', 'HEAD'], check=True,
        capture_output=True, text=True, env=env,
    ).stdout.strip()

    # A replacement ref must not change the launcher bytes selected by the
    # candidate commit that the RPC request names.
    original_source = script.read_bytes()
    script.write_bytes(original_source + b'\n# replacement ref payload\n')
    __import__('subprocess').run(['git', '-C', str(checkout), 'add', 'scripts'], check=True, env=env)
    __import__('subprocess').run(
        ['git', '-C', str(checkout), 'commit', '-q', '-m', 'replacement payload'], check=True, env=env,
    )
    replacement_revision = __import__('subprocess').run(
        ['git', '-C', str(checkout), 'rev-parse', 'HEAD'], check=True,
        capture_output=True, text=True, env=env,
    ).stdout.strip()
    __import__('subprocess').run(['git', '-C', str(checkout), 'checkout', '-q', revision], check=True, env=env)
    __import__('subprocess').run(
        ['git', '-C', str(checkout), 'replace', revision, replacement_revision], check=True, env=env,
    )
    replaced_source = __import__('subprocess').run(
        ['git', '-C', str(checkout), 'show', f'{revision}:scripts/postgres_deploy_service.py'],
        check=True, capture_output=True, env=env,
    ).stdout
    assert replaced_source != original_source

    monkeypatch.setattr(service, '__file__', str(script))
    monkeypatch.setattr(service, '_OWNER_UID', os.geteuid())
    monkeypatch.setattr(service, '_OWNER_GID', os.getegid())
    monkeypatch.setattr(bws_installation_admission, '_OWNER_UID', os.geteuid())
    monkeypatch.setattr(bws_installation_admission, '_OWNER_GID', os.getegid())

    assert service._candidate_checkout_root(revision) == checkout.resolve()
    binding, source = service._candidate_launcher_binding(checkout.resolve(), revision)
    assert source == original_source
    assert script.read_bytes() == original_source
    assert binding == {
        'candidate_sha': revision,
        'checkout': str(checkout.resolve()),
        'script_sha256': hashlib.sha256(source).hexdigest(),
    }
    monkeypatch.setattr(service.sys, bws_installation_admission._VERIFIED_CANDIDATE_ENTRYPOINT, binding,
                        raising=False)
    bws_installation_admission.require_verified_candidate_entrypoint(checkout.resolve(), revision)
    monkeypatch.setattr(
        service.sys, bws_installation_admission._VERIFIED_CANDIDATE_ENTRYPOINT,
        {**binding, 'script_sha256': '0' * 64},
    )
    with pytest.raises(bws_installation_admission.InstallationAdmissionRefused):
        bws_installation_admission.require_verified_candidate_entrypoint(checkout.resolve(), revision)
    monkeypatch.setattr(service.sys, bws_installation_admission._VERIFIED_CANDIDATE_ENTRYPOINT, binding)
    binding = bws_installation_admission._checkout_binding(checkout.resolve(), revision)
    caller = {'candidate_sha': revision, 'source_checkout': binding}
    assert service._verify_caller_checkout(caller) == str(script)
    bws_installation_admission._verify_checkout_caller(caller)
    checkout.chmod(0o750)
    with pytest.raises(bws_installation_admission.InstallationAdmissionRefused):
        bws_installation_admission._checkout_binding(checkout.resolve(), revision)
    with pytest.raises(bws_installation_admission.InstallationAdmissionRefused):
        bws_installation_admission._verify_checkout_caller(caller)
    with pytest.raises(RuntimeError, match='bws_preimport_reservation_refused'):
        service._verify_caller_checkout(caller)
    checkout.chmod(0o755)

    secure_tmp_path.chmod(0o770)
    with pytest.raises(bws_installation_admission.InstallationAdmissionRefused):
        bws_installation_admission._checkout_binding(checkout.resolve(), revision)
    with pytest.raises(bws_installation_admission.InstallationAdmissionRefused):
        bws_installation_admission._verify_checkout_caller(caller)
    with pytest.raises(RuntimeError, match='bws_preimport_reservation_refused'):
        service._verify_caller_checkout(caller)
    secure_tmp_path.chmod(0o750)
    with pytest.raises(RuntimeError, match='bws_candidate_checkout_refused'):
        service._candidate_checkout_root('a' * 40)

    clean_contract = contract.read_bytes()
    contract.write_bytes(clean_contract + b'\n')
    with pytest.raises(RuntimeError, match='bws_candidate_checkout_refused'):
        service._candidate_checkout_root(revision)
    with pytest.raises(RuntimeError, match='bws_preimport_reservation_refused'):
        service._verify_caller_checkout(caller)
    with pytest.raises(bws_installation_admission.InstallationAdmissionRefused):
        bws_installation_admission._verify_checkout_caller(caller)

    contract.write_bytes(clean_contract)
    (application / 'postgres_deploy_linux.py').write_text('VALUE = 2\n')
    with pytest.raises(RuntimeError, match='bws_candidate_checkout_refused'):
        service._candidate_checkout_root(revision)


def test_candidate_admission_refuses_legacy_direct_caller_without_verified_entrypoint(tmp_path, monkeypatch):
    from app.ops import bws_installation_admission as admission

    checkout = tmp_path / 'candidate'
    candidate_sha = 'a' * 40
    monkeypatch.setattr(admission.sys, 'argv', [
        str(checkout / 'scripts' / 'postgres_deploy_service.py'), 'rpc', 'dev',
    ])
    monkeypatch.setattr(admission.os, 'geteuid', lambda: admission._OWNER_UID)
    monkeypatch.setattr(admission.os, 'getegid', lambda: admission._OWNER_GID)
    monkeypatch.delattr(admission.sys, admission._VERIFIED_CANDIDATE_ENTRYPOINT, raising=False)
    monkeypatch.setattr(admission, '_proc_identity', lambda *_args: pytest.fail('legacy caller reached census'))

    with pytest.raises(admission.InstallationAdmissionRefused):
        admission._candidate_checkout_caller_identity('dev', checkout, candidate_sha)


def test_source_installation_reexecs_exact_candidate_launcher_before_import(tmp_path, monkeypatch):
    root = tmp_path / 'candidate'
    root.mkdir()
    request = {
        'action': 'source-installation', 'operation_id': '019ff695-00a6-7072-a082-57cbf2b3ee22',
        'candidate_sha': 'a' * 40, 'image_digest': 'sha256:' + 'b' * 64,
        'bundle_name': 'candidate-reexec',
    }
    raw = json.dumps(request)
    released = []
    executed = []

    class Reservation:
        skip_cleanup = False

        def release(self):
            released.append(True)

    class CandidateReexec(Exception):
        pass

    binding = {
        'candidate_sha': request['candidate_sha'], 'checkout': str(root),
        'script_sha256': 'c' * 64,
    }
    monkeypatch.setattr(service, '_preimport_reservation', lambda *_args: Reservation())
    monkeypatch.setattr(service, '_candidate_checkout_root', lambda _sha: root)
    monkeypatch.setattr(service, '_candidate_launcher_binding', lambda *_args: (binding, b'exact C1 source'))
    monkeypatch.setattr(service.sys, 'stdin', io.StringIO(raw))

    def reexec(launcher_binding, source, request_raw, arguments):
        assert released == [True]
        executed.append((launcher_binding, source, request_raw, arguments))
        raise CandidateReexec

    monkeypatch.setattr(service, '_execute_verified_candidate_entrypoint', reexec)
    with pytest.raises(CandidateReexec):
        service._dispatch(root, 'dev', ['rpc', 'dev'], caller_checkout=root)

    assert executed == [(binding, b'exact C1 source', raw, ['rpc', 'dev'])]


def test_verified_candidate_entrypoint_runs_as_main_and_restores_process_state(tmp_path, monkeypatch):
    source = (
        b'import sys\n'
        b"sys._verified_candidate_observation = ("
        b"__name__, __file__, sys.argv[1:], sys.stdin.read(), "
        b"getattr(sys, '_yggdrasil_bws_verified_candidate_entrypoint'))\n"
        b"raise SystemExit(0)\n"
    )
    root = tmp_path / 'candidate'
    script = root / 'scripts/postgres_deploy_service.py'
    script.parent.mkdir(parents=True)
    script.write_bytes(source)
    binding = {
        'candidate_sha': 'a' * 40, 'checkout': str(root),
        'script_sha256': hashlib.sha256(source).hexdigest(),
    }
    previous_argv, previous_stdin = service.sys.argv, service.sys.stdin
    monkeypatch.setattr(service.sys, 'argv', ['old-launcher', 'rpc', 'dev'])
    monkeypatch.setattr(service.sys, 'stdin', io.StringIO('old stdin'))

    with pytest.raises(SystemExit) as raised:
        service._execute_verified_candidate_entrypoint(binding, source, 'request C1', ['rpc', 'dev'])

    assert raised.value.code == 0
    assert service.sys._verified_candidate_observation == (
        '__main__', str(script), ['rpc', 'dev'], 'request C1', binding,
    )
    assert service.sys.argv == ['old-launcher', 'rpc', 'dev']
    assert service.sys.stdin.read() == 'old stdin'
    assert not hasattr(service.sys, service._VERIFIED_CANDIDATE_ENTRYPOINT)
    assert previous_argv is not service.sys.argv
    assert previous_stdin is not service.sys.stdin


def test_source_loader_accepts_empty_python_files_with_provenance(tmp_path):
    import hashlib

    root = tmp_path / 'candidate'
    package = root / 'app' / 'receipts'
    package.mkdir(parents=True)
    (root / 'app' / '__init__.py').write_bytes(b'')
    source = package / '__init__.py'
    source.write_bytes(b'')

    finder = service._install_source_loader(root)
    try:
        spec = finder.find_spec('app.receipts', [str(root / 'app')])
        assert spec is not None and spec.loader is not None
        code = spec.loader.get_code('app.receipts')
        assert code is not None
        assert spec.loader.loaded_source_sha256 == hashlib.sha256(b'').hexdigest()
    finally:
        if finder in sys.meta_path:
            sys.meta_path.remove(finder)


def test_supervisor_releases_startup_reservation_after_socket_is_bound(tmp_path, monkeypatch):
    socket_path = tmp_path / 'run' / 'dev.sock'
    socket_path.parent.mkdir()
    config = SimpleNamespace(channel='dev', socket_path=socket_path)
    released = []

    class Server:
        def __init__(self, path, _handler):
            self.path = Path(path)

        def __enter__(self):
            self.path.write_bytes(b'synthetic socket')
            return self

        def __exit__(self, *_args):
            self.path.unlink(missing_ok=True)

        def serve_forever(self):
            assert released == ['released']
            assert self.path.stat().st_mode & 0o777 == 0o600

    monkeypatch.setattr(linux.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(linux.sys, 'platform', 'linux')
    monkeypatch.setattr(linux, '_root_directory', lambda _path: None)
    monkeypatch.setattr(linux, 'DeploymentSupervisor', lambda _config: object())
    monkeypatch.setattr(linux.socketserver, 'ThreadingUnixStreamServer', Server)
    monkeypatch.setattr(linux.sys, '_yggdrasil_bws_startup_reservation_release',
                        lambda: released.append('released'), raising=False)

    linux.serve(config)

    assert released == ['released']


def _synthetic_installation_start(tmp_path, monkeypatch, channel='dev', *, active=True, permit=True):
    import fcntl

    state_directory = tmp_path / 'state' / 'convergence'
    state_directory.mkdir(mode=0o700, parents=True)
    state_directory.chmod(0o700)
    monkeypatch.setattr(service, '_RESERVATION_DIRECTORY', state_directory)
    monkeypatch.setattr(service, '_OWNER_UID', os.geteuid())
    monkeypatch.setattr(service, '_OWNER_GID', os.getegid())
    monkeypatch.setattr(service, '_open_owned_directory',
                        lambda path: os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))

    runtime = tmp_path / 'fixed-runtime'
    runtime.write_text('synthetic executable identity\n')
    runtime.chmod(0o755)
    launcher = tmp_path / 'fixed-launcher'
    launcher.write_text('synthetic fixed launcher\n')
    launcher.chmod(0o755)
    monkeypatch.setattr(service, '_FIXED_RUNTIME', runtime)
    monkeypatch.setattr(service, '_FIXED_LAUNCHER', launcher)

    pid = 87654321
    proc_root = tmp_path / 'proc'
    process = proc_root / str(pid)
    process.mkdir(parents=True)
    fields = [b'S'] + [b'0'] * 19
    fields[19] = b'1234'
    (process / 'stat').write_bytes(str(pid).encode() + b' (python) ' + b' '.join(fields) + b'\n')
    status = (
        f'Uid:\t{os.geteuid()}\t{os.geteuid()}\t{os.geteuid()}\t{os.geteuid()}\n'
        f'Gid:\t{os.getegid()}\t{os.getegid()}\t{os.getegid()}\t{os.getegid()}\n'
    )
    (process / 'status').write_bytes(status.encode())
    command = b'\0'.join(os.fsencode(item) for item in (
        str(runtime), str(launcher), 'rpc', channel,
    )) + b'\0'
    (process / 'cmdline').write_bytes(command)
    (process / 'exe').symlink_to(runtime)
    monkeypatch.setattr(service, '_PROC', proc_root)
    runtime_identity = service._stat_identity(runtime.stat())
    caller = {
        'pid': pid, 'uid': os.geteuid(), 'gid': os.getegid(), 'start_time': 1234,
        'argv_sha256': hashlib.sha256(command).hexdigest(),
        'executable_sha256': hashlib.sha256(
            json.dumps(runtime_identity, separators=(',', ':')).encode('ascii'),
        ).hexdigest(),
        'launcher_sha256': hashlib.sha256(launcher.read_bytes()).hexdigest(),
    }
    owner = {
        'schema': 'bws-source-installation-owner.v2',
        'operation_id': '00000000-0000-0000-0000-000000000001',
        'channel': channel, 'candidate_sha': 'd' * 40,
        'image_digest': 'sha256:' + 'e' * 64, 'bundle_name': 'synthetic', 'caller': caller,
    }
    owner_path = state_directory / f'{channel}.source-installation.lock'
    owner_raw = (json.dumps(owner, sort_keys=True, separators=(',', ':')) + '\n').encode()
    owner_path.write_bytes(owner_raw)
    owner_path.chmod(0o600)

    global_lock = state_directory / service._GLOBAL_LOCK_NAME
    global_fd = os.open(global_lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    os.chmod(global_lock, 0o600)
    fcntl.flock(global_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    channel_fd = None
    if active:
        channel_path = state_directory / f'{channel}.source-installation.lock'
        channel_fd = os.open(channel_path, os.O_RDONLY | os.O_NOFOLLOW)
        fcntl.flock(channel_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    permit_path = state_directory / f'{channel}.source-installation-start.json'
    if permit:
        authorization = {
            'schema': service._START_AUTHORIZATION_SCHEMA,
            'operation_id': owner['operation_id'], 'channel': channel,
            'candidate_sha': owner['candidate_sha'], 'image_digest': owner['image_digest'],
            'phase': 'candidate', 'generation_sha256': 'f' * 64, 'caller': caller,
        }
        permit_path.write_text(json.dumps(authorization, sort_keys=True, separators=(',', ':')) + '\n')
        permit_path.chmod(0o600)
    return {
        'directory': state_directory, 'global_fd': global_fd, 'channel_fd': channel_fd,
        'owner': owner, 'caller': caller, 'permit_path': permit_path,
    }


def _release_synthetic_installation_start(state):
    import fcntl
    for descriptor in (state['channel_fd'], state['global_fd']):
        if descriptor is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def test_installer_owned_serve_consumes_exact_live_same_channel_permit_once(tmp_path, monkeypatch):
    state = _synthetic_installation_start(tmp_path, monkeypatch)
    imported = []
    admission = ModuleType('app.ops.bws_installation_admission')
    admission.shared_caller_reservation = lambda _channel: pytest.fail(
        'authorized installation start must not use ordinary shared admission',
    )
    deployment = ModuleType('app.ops.postgres_deploy_linux')
    deployment.main = lambda _arguments: imported.append('main') or 0
    monkeypatch.setitem(sys.modules, 'app.ops.bws_installation_admission', admission)
    monkeypatch.setitem(sys.modules, 'app.ops.postgres_deploy_linux', deployment)
    monkeypatch.setattr(service, '_install_source_loader', lambda _root: imported.append('loader'))
    try:
        assert service._dispatch(tmp_path, 'dev', ['serve', 'dev']) == 0
        assert imported == ['loader', 'main']
        assert not state['permit_path'].exists()
        assert hasattr(service.sys, '_yggdrasil_bws_startup_reservation_release') is False
        with pytest.raises(RuntimeError, match='bws_preimport_reservation_refused'):
            service._dispatch(tmp_path, 'dev', ['serve', 'dev'])
        assert imported == ['loader', 'main']
    finally:
        _release_synthetic_installation_start(state)


@pytest.mark.parametrize(('owner_channel', 'active', 'permit'), [
    ('dev', False, True),  # A terminal DEV owner is not a live transaction.
    ('dev', True, False),  # A live owner without its one-use start grant cannot start.
    ('test', True, True),  # A TEST owner cannot authorize a DEV start.
])
def test_installer_owned_serve_rejects_stale_missing_or_wrong_channel_authority_before_import(
    tmp_path, monkeypatch, owner_channel, active, permit,
):
    state = _synthetic_installation_start(
        tmp_path, monkeypatch, owner_channel, active=active, permit=permit,
    )
    if owner_channel == 'dev' and not active:
        receipt = state['directory'] / 'bws-source-installation-00000000-0000-0000-0000-000000000001.receipt.json'
        receipt.write_text('{}\n')
        receipt.chmod(0o600)
    imported = []
    monkeypatch.setattr(service, '_install_source_loader', lambda _root: imported.append('loader'))
    try:
        with pytest.raises(RuntimeError, match='bws_preimport_reservation_refused'):
            service._dispatch(tmp_path, 'dev', ['serve', 'dev'])
        assert imported == []
    finally:
        _release_synthetic_installation_start(state)


@pytest.mark.parametrize('state', ['missing', 'exclusive-owner'])
def test_fixed_launcher_exec_stop_post_skips_before_source_import_when_fence_unavailable(tmp_path, state):
    state_directory = tmp_path / 'state' / 'convergence'
    lock_fd = None
    if state == 'exclusive-owner':
        state_directory.mkdir(mode=0o700, parents=True)
        state_directory.chmod(0o700)
        global_lock = state_directory / service._GLOBAL_LOCK_NAME
        lock_fd = os.open(global_lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        os.chmod(global_lock, 0o600)
        import fcntl
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        owner = {
            'schema': 'bws-source-installation-owner.v2',
            'operation_id': '00000000-0000-0000-0000-000000000001', 'channel': 'dev',
            'candidate_sha': 'a' * 40, 'image_digest': 'sha256:' + 'b' * 64,
            'bundle_name': 'synthetic',
            'caller': {
                'pid': os.getpid(), 'uid': os.geteuid(), 'gid': os.getegid(), 'start_time': 1,
                'argv_sha256': 'c' * 64, 'executable_sha256': 'd' * 64, 'launcher_sha256': 'e' * 64,
            },
        }
        owner_path = state_directory / 'dev.source-installation.lock'
        owner_path.write_text(json.dumps(owner, sort_keys=True, separators=(',', ':')) + '\n')
        owner_path.chmod(0o600)

    root = tmp_path / 'checkout-without-importable-source'
    code = r'''
import os, sys
from pathlib import Path
repository, root, state_directory, expected_state = sys.argv[1:]
sys.path.insert(0, repository)
from scripts import postgres_deploy_service as service
service._RESERVATION_DIRECTORY = Path(state_directory)
service._OWNER_UID = os.geteuid()
service._OWNER_GID = os.getegid()
service._open_owned_directory = lambda path: os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
sys.path.insert(0, root)
assert 'app.ops.postgres_deploy_linux' not in sys.modules
assert service._dispatch(Path(root), 'dev', ['cleanup', 'dev']) == 0
assert 'app.ops.postgres_deploy_linux' not in sys.modules
if expected_state == 'missing':
    assert not Path(state_directory).exists()
'''
    try:
        result = __import__('subprocess').run(
            [sys.executable, '-c', code, str(ROOT), str(root), str(state_directory), state],
            cwd=ROOT, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        if lock_fd is not None:
            import fcntl
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
