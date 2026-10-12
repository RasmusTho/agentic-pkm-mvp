"""Two finite TEST invocations; Product imports occur only in the Product child.

The existing root-only reader supervisor admits a fixed Docker exec. It never
becomes a Product Python runtime or a generic secret/command launcher. The child
owns its constituent flock through publication/writeback and acknowledgement.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import fcntl
from ipaddress import ip_address
import json
import logging
import os
from pathlib import Path
import re
import selectors
import signal
import socket
import stat
import subprocess
import sys
from typing import Any, Iterator

ACTIONS = frozenset({'karakeep-acquire', 'karakeep-project'})
_DOCKER = ['docker', '--host', 'unix:///var/run/docker.sock']
_ENV_KEYS = frozenset({
    'PKM_ENVIRONMENT', 'STORE_BACKEND', 'DATABASE_URL', 'DB_DSN',
    'DATABASE_PASSWORD_FILE', 'VAULT_ROOT', 'VAULT_ROOT_TEST',
    'INSTANCE_VAULT_REGISTRY_PATH', 'INSTANCE_OWNERSHIP_ROOT', 'VCS_REF',
    'KARAKEEP_RUNTIME_DB_ADDRESS',
})
_STATES = frozenset({'complete', 'partial', 'blocked', 'gated', 'failed', 'refused', 'overlap', 'pending'})


class RuntimeRefused(RuntimeError):
    def __init__(self) -> None:
        super().__init__('Karakeep runtime refused')


def require_action(action: str, channel: str) -> None:
    if action not in ACTIONS or channel != 'test':
        raise RuntimeRefused()


def _require_vm_host() -> None:
    if sys.platform != 'linux' or os.geteuid() != 0 or socket.gethostname().split('.')[0] != 'ygg-test':
        raise RuntimeRefused()


def _command(argv: list[str]) -> str:
    result = subprocess.run(argv, env={'PATH': '/usr/local/bin:/usr/bin:/bin'},
                            capture_output=True, text=True, timeout=15, check=False)
    if result.returncode:
        raise RuntimeRefused()
    return result.stdout


def _container(project: str, service: str) -> dict[str, Any]:
    ids = _command([*_DOCKER, 'ps', '-q', '--filter', 'label=com.docker.compose.project=' + project,
                    '--filter', 'label=com.docker.compose.service=' + service]).split()
    if len(ids) != 1 or not re.fullmatch(r'[0-9a-f]{12,64}', ids[0]):
        raise RuntimeRefused()
    # Captured private host state, never forwarded to callers or receipts.
    template = ('{"Id":{{json .Id}},"Image":{{json .Image}},'
                '"Config":{"Labels":{{json .Config.Labels}},"Env":' +
                ('{{json .Config.Env}}' if service == 'api' else '[]') + '},'
                '"State":{{json .State}},"Mounts":{{json .Mounts}},'
                '"HostConfig":{"NetworkMode":{{json .HostConfig.NetworkMode}}},'
                '"NetworkSettings":{{json .NetworkSettings}}}')
    row = json.loads(_command([*_DOCKER, 'inspect', '--format', template, ids[0]]))
    labels = row['Config']['Labels']
    if (labels.get('com.docker.compose.project') != project
        or labels.get('com.docker.compose.service') != service or not row['State']['Running']):
        raise RuntimeRefused()
    return row


def _environment(row: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for entry in row['Config']['Env']:
        key, value = entry.split('=', 1)
        if key in values:
            raise RuntimeRefused()
        values[key] = value
    if any(values.get(key) for key in ('PGPASSWORD', 'POSTGRES_PASSWORD', 'PGPASSFILE',
                                      'PGSERVICE', 'PGSERVICEFILE', 'KARAKEEP_API_TOKEN', 'KARAKEEP_BASE_URL')):
        raise RuntimeRefused()
    return {key: value for key, value in values.items() if key in _ENV_KEYS}


def _mount(row: dict[str, Any], path: str, *, volume: str | None = None) -> dict[str, Any]:
    matches = [item for item in row['Mounts'] if item['Destination'] == path and item['RW']]
    if len(matches) != 1 or (volume and matches[0].get('Name') != volume):
        raise RuntimeRefused()
    return matches[0]


def admitted_runtime(config: Any, action: str) -> tuple[dict[str, Any], dict[str, str], str | None]:
    """Read actual engine/container/code/mount topology before opening the reader."""
    require_action(action, config.channel)
    _require_vm_host()
    from app.ops.postgres_deploy_linux import _private_json

    qualification = _private_json(Path('/etc/yggdrasil/karakeep/test.json'))
    observed = datetime.fromisoformat(qualification['qualified_at'])
    now = datetime.now(timezone.utc)
    if (qualification['channel'] != 'test' or observed.tzinfo is None or not timedelta(0) <= now - observed <= timedelta(days=1)
        or not re.fullmatch(r'https://github.com/RasmusTho/agentic-pkm-mvp/issues/3367#issuecomment-[0-9]+',
                            qualification['qualification_ref'])):
        raise RuntimeRefused()
    row = _container('pkm-test', 'api')
    environment = _environment(row)
    revision = environment.get('VCS_REF', '')
    git = ['git', '-c', 'safe.directory=' + str(config.root), '-C', str(config.root)]
    if (not re.fullmatch(r'[0-9a-f]{40}', revision)
        or _command([*git, 'rev-parse', 'HEAD']).strip() != revision
        or _command([*git, 'status', '--porcelain', '--untracked-files=no', '--', 'app', 'scripts']).strip()):
        raise RuntimeRefused()
    image = json.loads(_command([*_DOCKER, 'image', 'inspect', row['Image']]))[0]
    if image['Config']['Labels'].get('org.opencontainers.image.revision') != revision:
        raise RuntimeRefused()
    from scripts.compose_env import compose_env_value

    pin = config.root / 'config/deploy/test.env'
    tags = [compose_env_value(line.split('=', 1)[1]) for line in pin.read_text().splitlines()
            if line.startswith('APP_IMAGE_TAG=')]
    if tags != [revision] or any(item['Destination'] == '/app' for item in row['Mounts']):
        raise RuntimeRefused()
    root = environment.get('VAULT_ROOT_TEST') or environment.get('VAULT_ROOT', '')
    if not root or (environment.get('VAULT_ROOT') and environment['VAULT_ROOT'] != root):
        raise RuntimeRefused()
    vault = _mount(row, root)
    _mount(row, '/app/instance-state', volume='pkm-test_instance-state')
    _mount(row, '/app/tmp-test', volume='pkm-test_runtime-tmp')
    ownership = _mount(row, '/app/instance-ownership')
    if vault['Type'] != 'bind' or ownership['Type'] != 'bind':
        raise RuntimeRefused()
    database = _container('pkm-test', 'db')
    _mount(database, '/var/lib/postgresql/data', volume='pkm-test_pgdata')
    shared_db = [item['IPAddress'] for name, item in database['NetworkSettings']['Networks'].items()
                 if name in row['NetworkSettings']['Networks']
                 and item['NetworkID'] == row['NetworkSettings']['Networks'][name]['NetworkID']]
    if len(shared_db) != 1 or not ip_address(shared_db[0]).is_private:
        raise RuntimeRefused()
    environment['KARAKEEP_RUNTIME_DB_ADDRESS'] = shared_db[0]
    # The established instance ownership authority is revalidated in the child;
    # none of these observed paths selects or repairs a vault.
    endpoint = None
    if action == 'karakeep-acquire':
        source = _container('karakeep-test', 'karakeep')
        if source['NetworkSettings']['Ports'] != {'3000/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '3000'}]}:
            raise RuntimeRefused()
        if row['HostConfig']['NetworkMode'] == 'host':
            endpoint = 'http://127.0.0.1:3000'
        else:
            networks = row['NetworkSettings']['Networks']
            shared = [(name, item) for name, item in source['NetworkSettings']['Networks'].items()
                      if name in networks and item['NetworkID'] == networks[name]['NetworkID']]
            if len(shared) != 1:
                raise RuntimeRefused()
            address = ip_address(shared[0][1]['IPAddress'])
            if address.version != 4 or not address.is_private or address.is_loopback or address.is_unspecified:
                raise RuntimeRefused()
            endpoint = 'http://' + str(address) + ':3000'
    return row, environment, endpoint


def _read_line(process: Any, *, seconds: int) -> dict[str, Any]:
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        if not selector.select(seconds):
            raise TimeoutError()
        raw = process.stdout.readline(65537)
    if not raw.endswith('\n') or len(raw) > 65536:
        raise RuntimeRefused()
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise RuntimeRefused()
    return result


def validate_receipt(value: dict[str, Any], action: str) -> dict[str, Any]:
    allowed = {'status', 'action', 'channel', 'revision', 'fetched', 'published', 'noops', 'item_errors',
               'consumed', 'written', 'already_exists', 'blocked', 'consumer_cursor'}
    if (set(value) - allowed or value.get('status') not in _STATES or value.get('action') != action
        or value.get('channel') != 'test' or ('revision' in value and not re.fullmatch(r'[0-9a-f]{40}', value['revision']))
        or any(type(item) is not int or item < 0 for key, item in value.items()
               if key not in {'status', 'action', 'channel', 'revision'})):
        raise RuntimeRefused()
    return value


def dispatch(config: Any, data: dict[str, Any], require_current_config: Any) -> dict[str, Any]:
    """Only the existing supervisor calls this; key stays on its reader path."""
    action = data.get('action', '')
    require_action(action, data.get('channel', ''))
    if set(data) != {'action', 'channel'}:
        raise RuntimeRefused()
    process = None
    sent = False
    values: dict[str, str] = {}
    try:
        require_current_config()
        row, environment, endpoint = admitted_runtime(config, action)
        # env -i prevents inherited provider/ingress/source keys reaching either
        # constituent. Runtime configuration and producer input travel over stdin.
        process = subprocess.Popen(
            [*_DOCKER, 'exec', '-i', '--user', f'{config.uid}:{config.gid}', row['Id'],
             'env', '-i', 'PATH=/usr/local/bin:/usr/bin:/bin', 'PYTHONUNBUFFERED=1',
             'python', '-m', 'app.ops.karakeep_runtime', 'child', action, 'test'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1, env={'PATH': '/usr/local/bin:/usr/bin:/bin'},
        )
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps(environment) + '\n')
        process.stdin.flush()
        first = _read_line(process, seconds=25)
        if first != {'ready': True}:
            return validate_receipt(first, action)
        require_current_config()
        current_row, current_env, current_endpoint = admitted_runtime(config, action)
        if (current_row['Id'], current_row['Image'], current_env, current_endpoint) != (
            row['Id'], row['Image'], environment, endpoint
        ):
            raise RuntimeRefused()
        inputs: dict[str, str] = {}
        if action == 'karakeep-acquire':
            from app.ops.host_secret_bootstrap import _resolve_bws_consumer_values
            from app.ops.host_secret_contract import load_host_secret_contract

            values = _resolve_bws_consumer_values('test', 'heimdal-karakeep-fetch',
                                                  load_host_secret_contract(), config.reader())
            if set(values) != {'karakeep.api-key'} or not endpoint:
                raise RuntimeRefused()
            inputs = {'endpoint': endpoint, 'token': values['karakeep.api-key']}
        sent = True  # even a partial pipe write can admit work before a lost ack
        process.stdin.write(json.dumps(inputs) + '\n')
        process.stdin.flush()
        result = validate_receipt(_read_line(process, seconds=130), action)
        if process.wait(timeout=5) != 0:
            raise RuntimeRefused()
        return result
    except Exception:
        # Once work was sent, loss of its acknowledgement cannot claim failure
        # or completion. Existing log/cursor replay is the recovery authority.
        return {'status': 'pending' if sent else 'refused', 'action': action, 'channel': 'test'}
    finally:
        values.clear()
        if process is not None:
            if process.stdin is not None:
                process.stdin.close()
            if process.poll() is None:
                # Killing the local docker client is not proof of child death.
                # Child alarm/OS flock retains exclusion until actual exit.
                process.terminate()
            if process.stdout is not None:
                process.stdout.close()


@contextmanager
def constituent_lock(directory: Path, action: str) -> Iterator[None]:
    require_action(action, 'test')
    if not directory.is_dir() or directory.is_symlink():
        raise RuntimeRefused()
    fd = os.open(directory / (action + '.lock'), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
            raise RuntimeRefused()
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)  # never unlink a lock another process may already have open


def child_preflight(environment: dict[str, str], action: str) -> Any:
    """Actual PG and vault/ownership authority, before the ready/key handshake."""
    if (set(environment) - _ENV_KEYS or environment.get('PKM_ENVIRONMENT') != 'test'
        or environment.get('STORE_BACKEND') != 'pg' or not re.fullmatch(r'[0-9a-f]{40}', environment.get('VCS_REF', ''))
        or environment.get('INSTANCE_VAULT_REGISTRY_PATH') != '/app/instance-state/agentic-pkm/vault-registry.md'
        or environment.get('INSTANCE_OWNERSHIP_ROOT') != '/app/instance-ownership'):
        raise RuntimeRefused()
    from app.config.database import credential_free_database_fields
    from app.db.dsn import resolve_dsn
    import psycopg

    urls = [value for name in ('DATABASE_URL', 'DB_DSN') if (value := environment.get(name))]
    if not urls or not environment.get('DATABASE_PASSWORD_FILE') or any(
        any(credential_free_database_fields(url).get(key) != expected
            for key, expected in (('dbname', 'app_test'), ('host', 'db'), ('port', '5432'), ('user', 'app')))
        or 'hostaddr' in credential_free_database_fields(url) for url in urls
    ) or any(credential_free_database_fields(url) != credential_free_database_fields(urls[0]) for url in urls):
        raise RuntimeRefused()
    root = environment.get('VAULT_ROOT_TEST') or environment.get('VAULT_ROOT', '')
    if not root or not Path(root).is_absolute() or not Path(root).is_dir():
        raise RuntimeRefused()
    os.environ.update(environment)
    os.environ['VAULT_ROOT'] = root
    os.environ['STORE_SCHEMA_AUTOCREATE'] = '0'
    from app.instance.scalar_binding_runtime import resolve_scalar_binding_runtime

    binding = resolve_scalar_binding_runtime(vault_root=Path(root))
    if binding is None or binding.channel_id != 'test':
        raise RuntimeRefused()
    registration = binding.registry_store.lookup(binding.vault_binding_id)
    if registration is None or not registration.vault_id:
        raise RuntimeRefused()
    # A real connection proves database identity in this namespace. Schema
    # checks are the existing migration-owned store gates, with autocreate off.
    with psycopg.connect(resolve_dsn(urls[0]), connect_timeout=5, autocommit=True) as conn:
        if conn.execute('SELECT current_database(), inet_server_addr()::text').fetchone() != (
            'app_test', environment.get('KARAKEEP_RUNTIME_DB_ADDRESS')
        ):
            raise RuntimeRefused()
    from app.heimdal.publish import read_observations_for_consumer

    # Fail early if the selected immutable Product image lacks this invocation's
    # library dependencies; never qualify them by importing into the BWS daemon.
    if action == 'karakeep-acquire':
        from app.heimdal import karakeep_ingest  # noqa: F401
    else:
        from app.heimdal import candidate_projection  # noqa: F401

    read_observations_for_consumer('mimer.candidate_projector', limit=1)
    return binding


def run_bound(action: str, binding: Any, inputs: dict[str, str], *, http: Any = None,
              write_guard: Any = None) -> dict[str, Any]:
    """Thin constituent-specific adapters over the shipped library contracts."""
    require_action(action, 'test')
    from app.instance.scalar_binding_runtime import frozen_binding_effect, validate_frozen_binding_runtime

    with binding.effect_leases.shared_effect(binding.vault_binding_id, channel_id='test', root=binding.root):
        validate_frozen_binding_runtime(binding)
        with frozen_binding_effect(binding):
            if action == 'karakeep-acquire':
                if set(inputs) != {'endpoint', 'token'}:
                    raise RuntimeRefused()
                from app.heimdal.karakeep_ingest import KarakeepAdapter, KarakeepConfig, KarakeepProducerCursor, StaticKarakeepToken
                from app.heimdal.karakeep_schedule import run_producer, source_health_gate

                cursor = KarakeepProducerCursor()
                source_id = 'karakeep-test'
                env = {'KARAKEEP_BASE_URL': inputs['endpoint'], 'KARAKEEP_API_TOKEN': inputs['token']}
                gate = lambda: source_health_gate(env, http=http)
                adapter = KarakeepAdapter(config=KarakeepConfig(base_url=inputs['endpoint'], source_id=source_id),
                                           token_provider=StaticKarakeepToken(inputs['token']), cursor=cursor,
                                           http=http, fetch_ready=lambda: _require_health(gate))
                receipt = run_producer(holder='native-test', health_gate=gate, acquire=adapter.acquire,
                                       read_producer_cursor=lambda: cursor.upstream_cursor(source_id))
                values = asdict(receipt)
                result: dict[str, Any] = {key: values[key] for key in ('fetched', 'published', 'noops', 'item_errors')}
                result['status'] = ('failed' if receipt.failed else 'gated' if receipt.gated else 'partial'
                                    if receipt.stopped_early or receipt.item_errors or receipt.producer_cursor else 'complete')
            else:
                if inputs:
                    raise RuntimeRefused()
                from app.heimdal.candidate_projection import CANDIDATE_CONSUMER_ID, project_pending_candidates
                from app.heimdal.karakeep_schedule import run_consumer
                from app.heimdal.publish import read_observations_for_consumer
                from app.heimdal.cursor_store import get_cursor
                from app.vault.manager import VaultContext
                from app.write_guard import DEFAULT_WRITE_GUARD

                context = VaultContext(status='selected', active_vault_path=str(binding.root), active_vault_id=binding.vault_binding_id)
                consumer_receipt = run_consumer(holder='native-test',
                    project=lambda: project_pending_candidates(vault_context=context, consumer_id=CANDIDATE_CONSUMER_ID,
                        write_guard=write_guard or DEFAULT_WRITE_GUARD, limit=100),
                    read_consumer_cursor=lambda: get_cursor(CANDIDATE_CONSUMER_ID))
                values = asdict(consumer_receipt)
                result = {key: values[key] for key in ('consumed', 'written', 'already_exists', 'blocked')}
                if consumer_receipt.consumer_cursor is not None:
                    result['consumer_cursor'] = consumer_receipt.consumer_cursor
                result['status'] = ('failed' if consumer_receipt.failed or consumer_receipt.consumer_cursor is None else 'blocked'
                    if consumer_receipt.blocked else 'partial' if read_observations_for_consumer(CANDIDATE_CONSUMER_ID, limit=1) else 'complete')
    return {**result, 'action': action, 'channel': 'test'}


def _require_health(gate: Any) -> None:
    if gate() is not None:
        raise RuntimeRefused()


def child(action: str, channel: str) -> int:
    require_action(action, channel)
    logging.disable(logging.CRITICAL)  # library/provider diagnostics never cross this boundary
    status = 'refused'
    signal.alarm(120)  # ends the actual process, releasing its OS-held exclusion
    try:
        environment = json.loads(sys.stdin.readline(65537))
        binding = child_preflight(environment, action)
        with constituent_lock(Path('/app/tmp-test'), action):
            print(json.dumps({'ready': True}), flush=True)
            inputs = json.loads(sys.stdin.readline(65537))
            status = 'pending'
            result = run_bound(action, binding, inputs)
            inputs.clear()
            result['revision'] = environment['VCS_REF']
    except BlockingIOError:
        result = {'status': 'overlap', 'action': action, 'channel': channel}
    except BaseException:
        result = {'status': status, 'action': action, 'channel': channel}
    finally:
        signal.alarm(0)
    print(json.dumps(validate_receipt(result, action)), flush=True)
    return 0


def remote(action: str, channel: str) -> int:
    require_action(action, channel)
    from app.ops.postgres_deploy_linux import rpc

    print(json.dumps(validate_receipt(rpc(channel, {'action': action, 'channel': channel}), action), sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    try:
        if len(args) == 3 and args[:1] == ['child']:
            return child(args[1], args[2])
        if len(args) != 2:
            raise RuntimeRefused()
        action, channel = args
        require_action(action, channel)  # before SSH, credential access or child launch
        result = subprocess.run([
            '/usr/bin/ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'ConnectTimeout=10', '-o', 'ClearAllForwardings=yes', '-o', 'PermitLocalCommand=no',
            '--', 'ygg-test', 'sudo', '-n', '/usr/local/libexec/yggdrasil-bws-deploy', action, channel],
            env={key: os.environ[key] for key in ('PATH', 'HOME', 'SSH_AUTH_SOCK') if key in os.environ},
            capture_output=True, text=True, timeout=180, check=False)
        if result.returncode or len(result.stdout) > 65536:
            raise RuntimeRefused()
        receipt = validate_receipt(json.loads(result.stdout), action)
        print(json.dumps(receipt, sort_keys=True))
        return 0 if receipt['status'] == 'complete' else 78
    except Exception:
        print(json.dumps({'status': 'refused', 'channel': 'test'}))
        return 78


if __name__ == '__main__':
    raise SystemExit(main())
