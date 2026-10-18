from __future__ import annotations

import io
import ast
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from app.builderops.ckm.contracts import canonical_json
from app.builderops.devui_ckm_snapshot import FILENAME
from app.ops import devui_ckm_snapshot as ops
from tests.builderops.test_devui_ckm_snapshot import make_snapshot


def test_publish_uses_fixed_ssh_stdin_and_atomic_receiver(tmp_path, monkeypatch, capsys) -> None:
    value, _ = make_snapshot(tmp_path, repository=ops.REPOSITORY)
    raw = canonical_json(value).encode()
    calls = []

    def transport(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, json.dumps({
            "status": "published", "content_sha256": value["content_sha256"], "capability_count": 1,
        }).encode(), b"")

    monkeypatch.setattr(ops.subprocess, "run", transport)
    assert ops.publish_snapshot(raw)["status"] == "published"
    command, options = calls.pop()
    assert command[:-1] == ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "--", "bob-1-builder-system"]
    assert options["input"] == raw
    assert value["content_sha256"] not in command[-1]
    assert "sudo -n python3 -c" in command[-1]

    # Run the reviewed receiver body on an isolated real directory. Only host
    # identity/ownership and the Docker transport are substituted; the production
    # decoder and actual atomic file/rename/fsync path execute.
    host_opt = tmp_path / "host-opt"
    base = host_opt / "builderops" / "receipts"
    base.mkdir(parents=True)
    for directory in (host_opt, base.parent, base):
        directory.chmod(0o755)
    real_lstat = Path.lstat

    def metadata(path):
        info = real_lstat(path)
        fields = list(info)
        fields[4], fields[5] = 0, 101
        return os.stat_result(fields)

    consumer_identity = {"uid": 100}

    def consumer(command, **kwargs):
        if command[3:5] == ['inspect', '--format']:
            return subprocess.CompletedProcess(command, 0, json.dumps([{
                'Destination': '/run/builderops/devui-receipts', 'Source': str(base),
                'RW': False, 'Type': 'bind',
            }]).encode(), b'')
        assert command[:6] == ['/usr/bin/docker', '-H', 'unix:///run/docker-builderops.sock', 'exec', '-i', 'builderops-devui-devui-1']
        # Execute the actual consumer validator/readback with virtualized
        # container UID, mount and environment; no validation is stubbed out.
        with monkeypatch.context() as child:
            child.setattr(os, 'geteuid', lambda: consumer_identity["uid"])
            child.setattr(os, 'getegid', lambda: 101)
            child.setenv('DEVUI_REPOSITORY', ops.REPOSITORY)
            child.setenv('DEVUI_VM102_RECEIPT_DIR', str(base))
            child.setattr(sys, 'stdin', io.TextIOWrapper(io.BytesIO(kwargs.get('input', b''))))
            child.setattr(sys, 'argv', ['-c', *command[9:]])
            code = command[8].replace('/run/builderops/devui-receipts', str(base))
            with redirect_stdout(io.StringIO()):
                exec(compile(code, 'private-ckm-consumer', 'exec', optimize=1), {})
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", consumer)
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(os, "fchown", lambda *args: None)
    monkeypatch.setattr(socket, "gethostname", lambda: "builder-system")
    monkeypatch.setattr(Path, "lstat", metadata)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw)))
    source = (ops.REMOTE
              .replace("Path('/opt/builderops/receipts')", f"Path({str(base)!r})")
              .replace("Path('/opt')", f"Path({str(host_opt)!r})"))
    exec(compile(source, "private-ckm-receiver", "exec"), {})
    assert (base / FILENAME).read_bytes() == raw

    # Root-configured consumer drift is rejected by the actual validator before
    # replacing an existing valid source.
    consumer_identity["uid"] = 0
    before = (base / FILENAME).stat().st_mtime_ns
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw)))
    with pytest.raises(SystemExit, match="publication refused"):
        exec(compile(source, "private-ckm-receiver", "exec"), {})
    assert (base / FILENAME).stat().st_mtime_ns == before
    assert (base / FILENAME).stat().st_mode & 0o777 == 0o640
    assert [p.name for p in base.glob(".devui-ckm-*")] == ['.devui-ckm-publish.lock']
    assert json.loads(capsys.readouterr().out)["content_sha256"] == value["content_sha256"]

    # A malformed replacement reaches the real decoder and cannot replace the
    # already-published healthy snapshot.
    consumer_identity["uid"] = 100
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b'{}')))
    with pytest.raises(SystemExit, match="publication refused"):
        exec(compile(source, "private-ckm-receiver", "exec"), {})
    assert (base / FILENAME).read_bytes() == raw


@pytest.mark.parametrize('case', ['root', 'missing-source', 'digest-mismatch', 'wrong-mount'])
def test_consumer_checks_survive_optimized_python(tmp_path, monkeypatch, case) -> None:
    value, _ = make_snapshot(tmp_path, repository=ops.REPOSITORY)
    raw = canonical_json(value).encode()
    if case != 'missing-source':
        (tmp_path / FILENAME).write_bytes(raw)
    strings = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in ast.parse(ops.REMOTE).body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {'VALIDATE', 'READBACK'}
    }
    code = strings['VALIDATE' if case in {'root', 'wrong-mount'} else 'READBACK']
    monkeypatch.setattr(os, 'geteuid', lambda: 0 if case == 'root' else 100)
    monkeypatch.setattr(os, 'getegid', lambda: 101)
    monkeypatch.setenv('DEVUI_REPOSITORY', ops.REPOSITORY)
    monkeypatch.setenv('DEVUI_VM102_RECEIPT_DIR', 'wrong' if case == 'wrong-mount' else str(tmp_path))
    monkeypatch.setattr(sys, 'stdin', io.TextIOWrapper(io.BytesIO(raw)))
    monkeypatch.setattr(sys, 'argv', ['-c', 'sha256:' + '0' * 64 if case == 'digest-mismatch' else value['content_sha256']])
    code = code.replace('/run/builderops/devui-receipts', str(tmp_path))
    with pytest.raises(ValueError, match='Consumer'):
        exec(compile(code, 'optimized-ckm-consumer', 'exec', optimize=1), {})
