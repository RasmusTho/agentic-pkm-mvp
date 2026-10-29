"""Assembled BuilderOps probe, with only external effect ports substituted."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


def setup_probe(tmp_path: Path) -> dict[str, str]:
    bins = tmp_path / "bin"
    bins.mkdir()
    fake = bins / "fake"
    fake.write_text(
        f"#!{sys.executable}\n"
        + """
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
mode = os.environ.get('CASE', '')
if name == 'docker' and (os.environ.get('DOCKER_CONTEXT') or os.environ.get('DOCKER_HOST')): sys.exit(77)
if name == 'docker' and mode == 'engine-down': sys.exit(1)
with open(os.environ['CALLS'], 'a') as f: f.write(json.dumps({'kind': name, 'args': sys.argv[1:]})+'\\n')
if name == 'hostname': print('wrong-host' if mode == 'wrong-host' else 'builder-system')
elif 'info' in sys.argv: print(json.dumps('other-engine' if mode == 'wrong-engine' else 'engine-test'))
else:
    rows=[]
    for service in ('api','worker','db'):
        rows.append({'Name':'/builderops-control-plane-'+service+'-1',
          'Config':{'Labels':{'com.docker.compose.project':'other' if mode == 'wrong-project' else 'builderops-control-plane', 'com.docker.compose.service':service}},
          'State':{'Running':True,'Health':{'Status':'unhealthy' if mode == 'db-down' and service == 'db' else 'healthy'}}})
    print(json.dumps(rows))
"""
    )
    fake.chmod(0o755)
    for name in ("hostname", "docker"):
        (bins / name).symlink_to(fake)
    token = tmp_path / "probe-token"
    token.write_text("private-probe-token")
    token.chmod(0o600)
    handoff = tmp_path / "alerts.env"
    handoff.write_text("DISCORD_WEBHOOK=https://discord.com/api/webhooks/123/private-webhook\n")
    handoff.chmod(0o600)
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "schema": "builderops_probe_config.v1",
                "target_hostname": "builder-system",
                "engine_socket": "unix:///run/docker-builderops.sock",
                "expected_engine_id": "engine-test",
                "project": "builderops-control-plane",
                "api_url": "http://127.0.0.1:18100",
                "expected_epoch": 42,
                "expected_schema_version": 5,
                "probe_token_file": str(token),
                "alert_runtime_file": str(handoff),
                "state_file": str(tmp_path / "state" / "alert.json"),
                "max_outbox_age_seconds": 300,
            }
        )
    )
    config.chmod(0o600)
    # Read/run the actual module with only urllib transport replaced. The real
    # configuration, identity, dependency, notification adapter and state paths run.
    harness = tmp_path / "run.py"
    harness.write_text("""
import io, json, os, socket, sys, urllib.request
from email.message import Message
from urllib.error import HTTPError
from urllib.response import addinfourl
def unexpected_connection(*args, **kwargs):
    raise AssertionError('unexpected network effect')
socket.create_connection=unexpected_connection
class Response:
    status=200
    def __init__(self, data, status=200): self.data=data; self.status=status
    def __enter__(self): return self
    def __exit__(self,*a): pass
    def read(self,*a): return json.dumps(self.data).encode()
def transport(request, timeout=0):
    mode=os.environ.get('CASE','')
    if request.get_method() == 'POST':
        assert request.full_url == 'https://discord.com/api/webhooks/123/private-webhook?wait=true'
        with open(os.environ['CALLS'],'a') as f: f.write(json.dumps({'kind':'notification'})+'\\n')
        if mode in ('delivery-failure','down-delivery-failure'): raise OSError('private-webhook private-probe-token')
        if mode in ('unconfirmed-down','unconfirmed-recovery'): return Response({},204)
        return Response({'id':'456','channel_id':'789','webhook_id':'123'})
    assert request.full_url == 'http://127.0.0.1:18100/readyz'
    assert request.get_header('Authorization') == 'Bearer private-probe-token'
    if mode in ('api-401','api-503'): raise HTTPError(request.full_url,int(mode[-3:]),'private-probe-token',{},None)
    payload={'ready':True,'database':{'available':True,'schema_version':5,'authority_epoch':42},
      'lineage':{'matches_release':True},'authority_bootstrap':{'status':'converged','writers_enabled':True},
      'executor_heartbeat':{'state':'healthy'},'outbox':{'pending':0,'oldest_age_seconds':0,'dead_letters':0,'authority_threatening':False},
      'durability':{'posture':'rebuildable'}}
    if mode in ('worker-stale','down-delivery-failure','unconfirmed-down'): payload['executor_heartbeat']['state']='stale'
    if mode == 'epoch-mismatch': payload['database']['authority_epoch']=41
    if mode == 'schema-mismatch': payload['database']['schema_version']=4
    if mode == 'not-bootstrapped': payload['authority_bootstrap']['writers_enabled']=False
    if mode == 'outbox-stale': payload['outbox'].update(pending=1,oldest_age_seconds=301)
    if mode == 'dead-letter': payload['outbox']['dead_letters']=1
    if mode == 'malformed-api': payload={'ready':True}
    return Response(payload)
if os.environ.get('CASE') == 'redirect':
    import io
    from email.message import Message
    from urllib.response import addinfourl
    def wire(handler, request):
        host=request.host
        category='api' if host=='127.0.0.1:18100' else 'alert' if host=='discord.com' else 'unexpected'
        assert category != 'unexpected'
        with open(os.environ['CALLS'],'a') as f: f.write(json.dumps({'kind':'wire','target':category})+'\\n')
        headers=Message()
        code=204 if category=='alert' else 302
        if code==302:headers['Location']='https://unrelated.invalid/private'
        response=addinfourl(io.BytesIO(b''),headers,request.full_url,code)
        response.msg='Found' if code==302 else 'No Content'
        return response
    urllib.request.HTTPHandler.http_open=wire
    urllib.request.HTTPSHandler.https_open=wire
else:
    def https_wire(handler, request):
        assert request.type == 'https' and request.host == 'discord.com'
        response=transport(request, timeout=request.timeout)
        wire=addinfourl(io.BytesIO(response.read()),Message(),request.full_url,response.status)
        wire.msg='OK'
        return wire
    urllib.request.HTTPSHandler.https_open=https_wire
    urllib.request.urlopen=transport
from app.ops.builderops_probe import main
raise SystemExit(main(sys.argv[1:]))
""")
    return {
        **os.environ,
        "PATH": str(bins) + os.pathsep + os.environ["PATH"],
        "PYTHONPATH": str(ROOT),
        "CALLS": str(tmp_path / "calls"),
        "CONFIG": str(config),
        "HARNESS": str(harness),
        "DOCKER_CONTEXT": "inherited-wrong-context",
        "DOCKER_HOST": "unix:///wrong",
    }


def invoke(env: dict[str, str], case: str = "") -> subprocess.CompletedProcess[str]:
    r = subprocess.run(
        [sys.executable, env["HARNESS"], "--config", env["CONFIG"]],
        cwd=ROOT,
        env={**env, "CASE": case},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert "private-probe-token" not in r.stdout + r.stderr
    assert "private-webhook" not in r.stdout + r.stderr
    return r


def events(env: dict[str, str]) -> list[dict]:
    p = Path(env["CALLS"])
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


@pytest.mark.parametrize(
    "case", ["wrong-host", "wrong-engine", "wrong-project", "epoch-mismatch", "schema-mismatch"]
)
def test_assembled_probe_refuses_wrong_identity(tmp_path: Path, case: str) -> None:
    env = setup_probe(tmp_path)
    result = invoke(env, case)
    assert result.returncode == 78, result.stdout + result.stderr
    assert not any(x["kind"] == "notification" for x in events(env))


@pytest.mark.parametrize(
    "case",
    [
        "worker-stale",
        "db-down",
        "api-401",
        "api-503",
        "not-bootstrapped",
        "outbox-stale",
        "dead-letter",
        "malformed-api",
    ],
)
def test_dependency_failures_are_not_false_green(tmp_path: Path, case: str) -> None:
    env = setup_probe(tmp_path)
    result = invoke(env, case)
    assert result.returncode == 1, result.stdout + result.stderr
    assert sum(x["kind"] == "notification" for x in events(env)) == 1


def test_transition_delivery_and_state_failures(tmp_path: Path) -> None:
    env = setup_probe(tmp_path)
    assert invoke(env).returncode == 0
    assert not any(x["kind"] == "notification" for x in events(env))
    assert invoke(env, "worker-stale").returncode == 1
    assert invoke(env, "worker-stale").returncode == 1
    assert sum(x["kind"] == "notification" for x in events(env)) == 1
    assert invoke(env, "delivery-failure").returncode == 1
    state = tmp_path / "state" / "alert.json"
    assert state.exists(), "failed recovery must retain the outage"
    assert invoke(env).returncode == 0
    assert invoke(env).returncode == 0
    assert sum(x["kind"] == "notification" for x in events(env)) == 3
    state.write_text("{")
    before = len(events(env))
    assert invoke(env).returncode == 78
    assert not any(x["kind"] == "notification" for x in events(env)[before:])
    assert state.read_text() == "{"


def test_preparation_is_plan_only(tmp_path: Path) -> None:
    env = setup_probe(tmp_path)
    r = subprocess.run(
        [
            sys.executable,
            "scripts/plan_builderops_probe.py",
            "--expected-engine-id",
            "engine-test",
            "--expected-epoch",
            "42",
            "--expected-schema-version",
            "5",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    plan = json.loads(r.stdout)
    assert (
        plan["target"] == "bob-1"
        and plan["host_mutations"] == []
        and plan["activation_ready"] is False
    )
    assert not events(env)
    r = subprocess.run(
        [sys.executable, "scripts/plan_builderops_probe.py", "--apply"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert r.returncode != 0
    assert not events(env)


@pytest.mark.parametrize(
    "change",
    [
        "missing-alert-handoff",
        "symlink-token",
        "invalid-config",
        "bad-state-type",
        "wrong-state-epoch",
    ],
)
def test_invalid_private_inputs_refuse_without_delivery(tmp_path: Path, change: str) -> None:
    env = setup_probe(tmp_path)
    state = tmp_path / "state" / "alert.json"
    if change == "missing-alert-handoff":
        (tmp_path / "alerts.env").unlink()
    elif change == "symlink-token":
        token = tmp_path / "probe-token"
        token.rename(tmp_path / "real-token")
        token.symlink_to(tmp_path / "real-token")
    elif change == "invalid-config":
        p = Path(env["CONFIG"])
        value = json.loads(p.read_text())
        value["token"] = "must-not-be-configuration"
        p.write_text(json.dumps(value))
    else:
        assert invoke(env, "worker-stale").returncode == 1
        data = json.loads(state.read_text())
        data["incident_id"] = None if change == "bad-state-type" else data["incident_id"]
        if change == "wrong-state-epoch":
            data["authority_epoch"] = 41
        state.write_text(json.dumps(data))
    before = len(events(env))
    result = invoke(env)
    assert result.returncode == 78, result.stdout + result.stderr
    assert not any(x["kind"] == "notification" for x in events(env)[before:])


def test_failed_down_delivery_remains_retryable(tmp_path: Path) -> None:
    env = setup_probe(tmp_path)
    assert invoke(env, "down-delivery-failure").returncode == 1
    assert not (tmp_path / "state" / "alert.json").exists()
    assert invoke(env, "worker-stale").returncode == 1
    assert invoke(env, "worker-stale").returncode == 1
    assert sum(x["kind"] == "notification" for x in events(env)) == 2


def test_unconfirmed_shared_delivery_preserves_builderops_retry_and_correlation(tmp_path: Path) -> None:
    env = setup_probe(tmp_path)
    state = tmp_path / "state" / "alert.json"
    assert invoke(env, "unconfirmed-down").returncode == 1
    assert not state.exists()
    assert invoke(env, "worker-stale").returncode == 1
    incident = json.loads(state.read_text())["incident_id"]
    assert invoke(env, "worker-stale").returncode == 1
    assert sum(x["kind"] == "notification" for x in events(env)) == 2
    assert invoke(env, "unconfirmed-recovery").returncode == 1
    assert json.loads(state.read_text())["incident_id"] == incident
    assert invoke(env).returncode == 0
    assert not state.exists()
    assert sum(x["kind"] == "notification" for x in events(env)) == 4


def test_assembled_transport_blocks_redirects_and_ambient_proxies(tmp_path: Path) -> None:
    env = setup_probe(tmp_path)
    env.update(
        HTTP_PROXY="http://unrelated.invalid:1234",
        HTTPS_PROXY="http://unrelated.invalid:1234",
        NO_PROXY="",
    )
    result = invoke(env, "redirect")
    assert result.returncode == 1, result.stdout + result.stderr
    assert [x["target"] for x in events(env) if x["kind"] == "wire"] == ["api", "alert"]


def test_overlapping_probe_refuses_without_notification(tmp_path: Path) -> None:
    import fcntl

    env = setup_probe(tmp_path)
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    lock = state / "probe.lock"
    lock.touch(mode=0o600)
    with lock.open("r+") as owner:
        fcntl.flock(owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert invoke(env, "worker-stale").returncode == 78
    assert not any(x["kind"] == "notification" for x in events(env))


@pytest.mark.parametrize("private_input", ["missing", "invalid-utf8", "empty"])
@pytest.mark.parametrize("dependency", ["", "engine-down"])
def test_private_token_refusal_precedes_outage(
    tmp_path: Path, private_input: str, dependency: str
) -> None:
    env = setup_probe(tmp_path)
    token = tmp_path / "probe-token"
    if private_input == "missing":
        token.unlink()
    else:
        token.write_bytes(b"\xff\xfe" if private_input == "invalid-utf8" else b"")
    result = invoke(env, dependency)
    assert result.returncode == 78, result.stdout + result.stderr
    assert not any(x["kind"] == "notification" for x in events(env))
