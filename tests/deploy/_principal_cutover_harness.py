"""Synthetic external ports for the unmodified native deployment shell.

The shell, inherited guard, writer proof producers, authenticated ownership,
principal transaction and clean-failure verifier are all production code.
The socket merely models exec/container mount and OS/Docker observation ports.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import threading
from unittest.mock import patch

from app.instance import runtime as instance
from app.instance.principal_fence import principal_floor_recorded
from app.ops import postgres_deploy_linux as linux
from scripts import instance_state_writer_inventory as inventory
from tests._mvr_default_vault_harness import activate, new_runtime

REPO = Path(__file__).resolve().parents[2]

_CLIENT = '''import json, os, socket, subprocess, sys
from pathlib import Path
kind = Path(sys.argv[0]).name
args = sys.argv[1:]
if kind == "psql":
    print("0")
    raise SystemExit(0)
if kind == "python-port":
    if args[:2] == ["-m", "app.ops.postgres_deploy_linux"]:
        kind, args = "guard", args[2:]
    elif args and args[0].endswith("/instance_state_writer_inventory.py"):
        kind, args = "inventory", args[1:]
    elif args[:2] == ["-m", "pytest"] or (args[:1] == ["-c"] and "sync_playwright" in args[1]):
        # External browser/test executable availability, not an admission guard.
        raise SystemExit(0)
    else:
        os.execv(os.environ["FIXTURE_PYTHON"], [os.environ["FIXTURE_PYTHON"], *args])
held = None
if kind == "guard":
    info = os.fstat(int(os.environ["BWS_DEPLOY_LOCK_FD"]))
    held = [info.st_dev, info.st_ino]
with socket.socket(socket.AF_UNIX) as connection:
    connection.connect(os.environ["FIXTURE_SOCKET"])
    connection.sendall((json.dumps({"kind": kind, "args": args, "env": dict(os.environ), "held": held})+"\\n").encode())
    response = json.loads(connection.makefile().readline())
sys.stdout.write(response["out"])
sys.stderr.write(response["err"])
raise SystemExit(response["code"])
'''


class NativeShellBoundary:
    def __init__(self, native, tmp_path, monkeypatch, fault):
        self.native, self.fault = native, fault
        self.events, self.errors, self.results, self.messages = [], [], [], []
        self.output = ('', '')
        self.stopped = False
        self.snapshot_count = 0
        self.runtime = new_runtime(tmp_path / 'product', channel=native.cfg.channel)
        vault = tmp_path / 'synthetic-vault'
        vault.mkdir()
        first = self.runtime.bootstrap_env_binding(vault_root=vault, watcher_vault_path=vault)
        activate(self.runtime, first, tmp_path / 'product')
        self.store = instance.open_local_operator_principal_store(self.runtime.layout.registry_path)
        monkeypatch.setenv('INSTANCE_OWNERSHIP_HOST_STATE_DIR', str(self.runtime.ledger.root))
        monkeypatch.setenv('API_KEY', 'synthetic-product-auth-key')
        monkeypatch.setenv('COMPANION_UI_PROXY_HOSTS', 'companion-ui')
        root = native.cfg.root
        for name in ('app', 'mimer_runtime', 'llm_contract', 'tests'):
            (root / name).symlink_to(REPO / name, target_is_directory=True)
        for relative in (
            'scripts/deploy_channel.sh', 'scripts/start_full_system.sh', 'scripts/export_runtime_env.sh',
            'scripts/compose_env.py', 'scripts/companion_ui_postdeploy_smoke.sh',
            'scripts/dev_test_environment_clobber_preflight.py', 'scripts/instance_state_writer_inventory.py',
            'config/secrets/host_secret_contract.json', 'docker-compose.yaml',
            'docker-compose.dev.yml', 'docker-compose.test.yml', 'docker-compose.bws.yml',
        ):
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / relative, destination)
        shutil.copytree(REPO / 'scripts/lib', root / 'scripts/lib')
        (root / 'config/tts-disabled').mkdir()
        pin = root / 'config/deploy' / (native.cfg.channel + '.env')
        pin.write_text(pin.read_text() + 'MVR03_PRINCIPAL_LOOPBACK_LISTENER=0\n')
        native.cfg.runtime_env_file.write_text(native.cfg.runtime_env_file.read_text()
            + f'LOCAL_UID={os.getuid()}\nLOCAL_GID={os.getgid()}\nTTS_ENABLED=false\n'
            + 'API_KEY=synthetic-product-auth-key\nCOMPANION_UI_PROXY_HOSTS=companion-ui\n')
        self.bin = tmp_path / 'ports'
        self.bin.mkdir()
        for name in ('python-port', 'docker', 'git', 'psql'):
            path = self.bin / name
            path.write_text('#!' + sys.executable + '\n' + _CLIENT)
            path.chmod(0o755)
        self.socket_dir = tempfile.TemporaryDirectory(prefix='principal-', dir='/tmp')
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.bind(self.socket_dir.name + '/port')
        self.socket.listen()
        self.socket.settimeout(0.1)
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()
        # Only external OS/configuration census ports are synthetic. Normalizing,
        # stabilizing, signing and validating their observations remain real.
        monkeypatch.setattr(inventory, '_docker_legacy_owner_sources', lambda: ([], []))
        monkeypatch.setattr(inventory, '_config_legacy_owner_sources', lambda *a, **k: (
            [inventory.LegacyOwnerRecord(native.cfg.channel, str(vault), 'config_env')], ['synthetic-config']))
        monkeypatch.setattr(inventory, '_record_for_pid', lambda pid, **k:
            inventory.ProcessRecord(pid, 1, pid, 'linux:' + '0' * 64, ('bash', 'deploy_channel.sh')))
        monkeypatch.setattr(inventory, 'controller_namespace_digest', lambda *a, **k: '1' * 64)
        monkeypatch.setattr(inventory, '_docker_writers', self._writers)
        monkeypatch.setattr(inventory, '_native_writers', lambda **k: [])
        # Same runtime UID already in this process: exercise the real request
        # receiver instead of spawning a privilege-changing transport child.
        monkeypatch.setattr(inventory, '_run_ownership_ledger_as_runtime', inventory._ownership_ledger_runtime_request)
        original_replace = os.replace

        def replace(source, target, *args, **kwargs):
            if Path(target) != self.store.path:
                return original_replace(source, target, *args, **kwargs)
            self.events.append('role-write')
            assert self.stopped and self.snapshot_count == 2
            assert principal_floor_recorded(self.runtime.registry)
            if fault in {'clean', 'tampered-clean'}:
                raise OSError('synthetic pre-role storage failure')
            original_replace(source, target, *args, **kwargs)
            raise OSError('synthetic post-role lost result')

        monkeypatch.setattr(os, 'replace', replace)

    def _writers(self):
        self.events.append('writer-snapshot')
        self.snapshot_count += 1
        assert self.stopped
        if self.fault == 'incomplete':
            raise inventory.InventoryError('synthetic unavailable Docker observation')
        if self.fault == 'racing' and self.snapshot_count == 2:
            return [{'domain': 'dev', 'role': 'api', 'pid': 99, 'start_token': 'docker:' + '2' * 64}]
        return []

    def _mapped(self, argument):
        for source, destination in (
            ('/app/instance-state', self.runtime.layout.root.parent),
            ('/app/instance-ownership', self.runtime.ledger.root),
            ('/run/scalar-rollback-policy/docker-compose.yaml', REPO / 'docker-compose.yaml'),
            ('/run/principal-fence-native-producers', REPO),
        ):
            if argument == source or argument.startswith(source + '/'):
                return str(destination) + argument[len(source):]
        return argument

    def _dispatch(self, request):
        kind, args = request['kind'], request['args']
        if kind == 'guard':
            self.events.append('native-guard')
            info = os.fstat(self.native.supervisor.operation.effects.lock_fd)
            assert request['held'] == [info.st_dev, info.st_ino]
            return linux.main(args)
        elif kind == 'inventory':
            self.events.append(args[0])
            return inventory.main(args)
        elif kind == 'git':
            if 'rev-parse' in args:
                print(self.native.sha)
            elif 'show' in args:
                print((REPO / args[-1].split(':', 1)[1]).read_text(), end='')
            elif 'cat-file' in args:
                assert args[-2] == '-e'
            else:
                assert 'ls-tree' in args or 'diff' in args
        elif kind == 'psql':
            print('0')
        elif kind == 'docker':
            if 'app.instance.runtime' in args:
                command = [self._mapped(arg) for arg in args[args.index('app.instance.runtime') + 1:]]
                self.events.append(command[0])
                if command[0] == 'principal-verify-cutover-clean-failure' and self.fault == 'tampered-clean':
                    path = Path(command[command.index('--clean-failure-receipt-path') + 1])
                    payload = json.loads(path.read_text())
                    payload['payload']['result_registry_revision'] += 1
                    path.write_text(json.dumps(payload))
                # Compose's env_file mount is a container configuration port;
                # resolve it with the production reader, not supervisor secrets.
                from app.release_channels.channel_isolation_preflight import resolve_effective_dsn
                from app.settings import settings
                posture = {key: resolve_effective_dsn(
                    self.native.cfg.root / 'docker-compose.yaml', 'instance-state-init', key,
                    environ=os.environ, load_dotenv=False) or ''
                    for key in ('API_KEY', 'COMPANION_UI_PROXY_HOSTS')}
                with patch.dict(os.environ, posture), patch.object(settings, 'api_key', posture['API_KEY']), \
                     patch.object(settings, 'companion_ui_proxy_hosts', posture['COMPANION_UI_PROXY_HOSTS']):
                    code = instance.main(command)
                self.results.append((command[0], code))
                return code
            if 'config' in args:
                print((REPO / 'docker-compose.yaml').read_text())
            elif 'stop' in args:
                self.events.append('stop')
                self.stopped = True
            elif 'exec' in args and 'db' in args and args[-2] == '-ec':
                self.events.append('database-drain')
                result = self.native.real_run(['sh', '-ec', args[-1]], env=os.environ.copy(),
                    capture_output=True, text=True, check=False)
                print(result.stdout, end='')
                return result.returncode
            elif '-c' in args and 'native-source-embedding-identity.v1' in args[-1]:
                print(json.dumps({'contract': 'native-source-embedding-identity.v1', 'provider': 'mock', 'model': 'synthetic'}))
            elif 'ps' in args:
                if '--format' in args and 'json' in args[-1]:
                    print('[]')
            else:
                assert any(command in args for command in ('run', 'pull', 'up', 'rm', 'inspect')), args
        else:
            raise AssertionError(kind)
        return 0

    def _serve(self):
        while not self.closed.is_set():
            try:
                connection, _ = self.socket.accept()
            except TimeoutError:
                continue
            with connection:
                request = json.loads(connection.makefile().readline())
                out, err = StringIO(), StringIO()
                try:
                    with patch.dict(os.environ, request['env'], clear=True), redirect_stdout(out), redirect_stderr(err):
                        code = self._dispatch(request)
                except BaseException as error:
                    self.errors.append(error)
                    code = 78
                self.messages.append((request['kind'], request['args'], code, out.getvalue(), err.getvalue()))
                connection.sendall((json.dumps({'code': code, 'out': out.getvalue(), 'err': err.getvalue()}) + '\n').encode())

    def run(self, argv, **kwargs):
        environment = {**kwargs['env'], 'PATH': str(self.bin) + ':' + kwargs['env']['PATH'],
                       'PYTHON': str(self.bin / 'python-port'), 'FIXTURE_PYTHON': sys.executable,
                       'FIXTURE_SOCKET': self.socket_dir.name + '/port', 'PYTHONPATH': str(REPO),
                       'PYTHONDONTWRITEBYTECODE': '1'}
        result = self.native.real_run(argv, **{**kwargs, 'env': environment, 'timeout': 30})
        self.output = result.stdout, result.stderr
        return result

    def close(self):
        self.closed.set()
        self.thread.join(timeout=3)
        self.socket.close()
        self.socket_dir.cleanup()
        assert not self.thread.is_alive()
