from __future__ import annotations

import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ops import postgres_deploy as deploy
from app.ops import postgres_deploy_linux as linux
from scripts import postgres_deploy_service as service


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
