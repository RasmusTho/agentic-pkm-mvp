"""Private non-prod Karakeep lifecycle through the existing BWS supervisor.

The host controller and VM DeployJournal retain operation authority. A lost
worker leaves its nonterminal receipt pending; neither health nor a timeout
authorizes replay. Boot only rehydrates an already committed installation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import yaml

from app.ops.host_secret_bootstrap import _resolve_bws_consumer_values, validate_secret_value
from app.ops.host_secret_contract import load_host_secret_contract
from app.ops.postgres_deploy import DeployJournal, DeployReceipt
from app.ops.postgres_deploy_host import _configured_host_admin, require_qualification
from app.ops.postgres_deploy_linux import LinuxConfig, LinuxEffects, _private_json, rpc
from app.ops.secret_admin import SecretAdmin


SERVICE_CONSUMERS = ('karakeep-service-web', 'karakeep-service-search')
IMAGES = {'karakeep': 'ghcr.io/karakeep-app/karakeep:0.28.0',
          'karakeep-meilisearch': 'getmeili/meilisearch:v1.13.3'}
_DOCKER = ['docker', '--host', 'unix:///var/run/docker.sock']
_OBSERVATION_SECONDS = 600.0
_OBSERVATION_BACKOFF_SECONDS = 1.0


class KarakeepDeployError(RuntimeError):
    def __init__(self) -> None:
        super().__init__('Karakeep operation refused; inspect matching value-free receipt')


class KarakeepOperationPending(KarakeepDeployError):
    """Bounded observation ended; original operation still owns admission."""


def _observe_terminal(response: dict[str, Any], status: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    deadline = time.monotonic() + _OBSERVATION_SECONDS
    while response == {'pending': True}:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise KarakeepOperationPending()
        time.sleep(min(_OBSERVATION_BACKOFF_SECONDS, remaining))
        response = status()
    return response


def _server_url(value: object) -> bool:
    # Receipt-qualified SSH local forwarding only, never a guessed address,
    # DNS/firewall change, public interface, credentials, or dotenv syntax.
    if not isinstance(value, str):
        return False
    match = re.fullmatch(r'http://127\.0\.0\.1:([0-9]{4,5})', value)
    return bool(match and 1024 <= int(match[1]) <= 65535)


@dataclass(frozen=True)
class KarakeepPlan:
    channel: str
    revision: str

    def validate(self) -> None:
        if self.channel not in {'dev', 'test'} or not isinstance(self.revision, str) or not re.fullmatch(
            r'[0-9a-f]{40}', self.revision
        ):
            raise KarakeepDeployError()

    def payload(self) -> dict[str, str]:
        return asdict(self)


def _command(argv: list[str], *, env: dict[str, str] | None = None,
             timeout: int = 30) -> str:
    # Child environments contain non-secret wiring only, never the BWS handle
    # or ambient Docker/Compose overrides. Capture and discard diagnostics.
    clean = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': '/root', 'LC_ALL': 'C'}
    try:
        result = subprocess.run(argv, env={**clean, **(env or {})}, text=True,
                                capture_output=True, timeout=timeout, check=False)
        if result.returncode:
            raise KarakeepDeployError()
        return result.stdout
    except Exception:
        raise KarakeepDeployError() from None


def _valid_request(data: dict[str, Any], channel: str) -> tuple[str, KarakeepPlan]:
    fields = {'action', 'operation_id', 'plan'}
    if data.get('action') == 'karakeep-boot':
        fields.add('prior_operation_id')
        if str(UUID(data['prior_operation_id'])) != data['prior_operation_id']:
            raise KarakeepDeployError()
    if set(data) != fields or data['action'] not in {
        'karakeep-preflight', 'karakeep-deploy', 'karakeep-status', 'karakeep-boot', 'karakeep-boot-status'
    }:
        raise KarakeepDeployError()
    operation_id = data['operation_id']
    if not isinstance(operation_id, str) or str(UUID(operation_id)) != operation_id:
        raise KarakeepDeployError()
    raw = data['plan']
    if not isinstance(raw, dict) or set(raw) != {'channel', 'revision'}:
        raise KarakeepDeployError()
    plan = KarakeepPlan(**raw)
    plan.validate()
    if channel != plan.channel:
        raise KarakeepDeployError()
    return operation_id, plan


class KarakeepEffects:
    def __init__(self, config: LinuxConfig) -> None:
        if config.channel not in {'dev', 'test'}:
            raise KarakeepDeployError()
        self.config = config
        self.runtime = Path('/run/yggdrasil/karakeep') / config.channel
        self.journal = DeployJournal(Path('/var/lib/yggdrasil/karakeep'), config.channel)
        self.unit_directory = Path('/etc/systemd/system')
        self.server_url = ''

    @property
    def project(self) -> str:
        return 'karakeep-' + self.config.channel

    @property
    def boot_journal(self) -> DeployJournal:
        # Same existing operation protocol, separate attempt namespace. Boot
        # must never replace installation or host-reconciliation authority.
        return DeployJournal(self.journal.directory / 'boot', self.config.channel)

    def require_tmpfs(self) -> None:
        for parent in (self.runtime, *self.runtime.parents):
            if parent.is_symlink():
                raise KarakeepDeployError()
        existing = self.runtime
        while not existing.exists():
            existing = existing.parent
        if not existing.is_dir() or _command(['stat', '-f', '-c', '%T', str(existing)]).strip() != 'tmpfs':
            raise KarakeepDeployError()

    def _containers(self) -> list[dict[str, Any]]:
        ids = _command([*_DOCKER, 'ps', '-aq', '--filter',
                        'label=com.docker.compose.project=' + self.project]).split()
        if not ids:
            return []
        # Never retrieve Config.Env: the Docker metadata itself contains app keys.
        template = ('{"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
                    '"image":{{json .Config.Image}},"ports":{{json .HostConfig.PortBindings}},'
                    '"mounts":{{json .Mounts}},"state":{{json .State}}}')
        return [json.loads(line) for line in _command(
            [*_DOCKER, 'inspect', '--format', template, *ids]
        ).splitlines()]

    def _verify_topology(self, *, healthy: bool = False) -> None:
        rows = self._containers()
        if rows:
            if len(rows) != 2 or {row['service'] for row in rows} != set(IMAGES):
                raise KarakeepDeployError()
            for row in rows:
                service = row['service']
                volume = 'karakeep-data' if service == 'karakeep' else 'karakeep-meilisearch-data'
                if row['image'] != IMAGES[service] or not any(
                    mount.get('Type') == 'volume' and mount.get('Name') == self.project + '_' + volume
                    for mount in row['mounts']
                ):
                    raise KarakeepDeployError()
                expected_ports = {'3000/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '3000'}]} if service == 'karakeep' else {}
                if (row['ports'] or {}) != expected_ports:
                    raise KarakeepDeployError()
                if healthy and (not row['state'].get('Running') or
                                row['state'].get('Health', {}).get('Status') != 'healthy'):
                    raise KarakeepDeployError()
        elif healthy:
            raise KarakeepDeployError()
        else:
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 3000))

    def preflight(self, plan: KarakeepPlan, *, boot: bool = False) -> dict[str, dict[str, str]]:
        plan.validate()
        cfg = self.config
        self.require_tmpfs()  # before request persistence or secret resolution
        if plan.channel != cfg.channel or socket.gethostname().split('.')[0] != 'ygg-' + plan.channel:
            raise KarakeepDeployError()
        if _command(['git', '-c', 'safe.directory=' + str(cfg.root), '-C', str(cfg.root),
                     'rev-parse', 'HEAD']).strip() != plan.revision:
            raise KarakeepDeployError()
        settings = _private_json(Path('/etc/yggdrasil/karakeep') / (cfg.channel + '.json'))
        if (set(settings) != {'channel', 'server_url', 'qualification_ref', 'qualified_at'}
            or settings['channel'] != cfg.channel or not _server_url(settings['server_url'])
            or not re.fullmatch(r'https://github.com/RasmusTho/agentic-pkm-mvp/issues/3367#issuecomment-[0-9]+',
                                settings['qualification_ref'])):
            raise KarakeepDeployError()
        observed = datetime.fromisoformat(settings['qualified_at'])
        now = datetime.now(timezone.utc)
        if observed.tzinfo is None or observed > now or (not boot and now - observed > timedelta(days=1)):
            raise KarakeepDeployError()
        self.server_url = settings['server_url']
        manifest = cfg.root / 'docker-compose.karakeep.yml'
        tracked = _command(['git', '-c', 'safe.directory=' + str(cfg.root), '-C', str(cfg.root),
                            'show', plan.revision + ':docker-compose.karakeep.yml'])
        if manifest.read_text() != tracked:
            raise KarakeepDeployError()
        shape = yaml.safe_load(tracked)
        services = shape['services']
        if (set(services) != set(IMAGES) or set(shape['volumes']) != {'karakeep-data', 'karakeep-meilisearch-data'}
            or services['karakeep']['ports'] != ['127.0.0.1:3000:3000']
            or 'ports' in services['karakeep-meilisearch']
            or any(services[name]['image'] != image for name, image in IMAGES.items())):
            raise KarakeepDeployError()
        _command([*_DOCKER, 'info', '--format', '{{.ID}}'])
        version = _command([*_DOCKER, 'compose', 'version', '--short']).strip().removeprefix('v')
        match = re.fullmatch(r'([0-9]+)\.([0-9]+)\.([0-9]+)(?:[-+].*)?', version)
        if not match or tuple(int(part) for part in match.groups()) < (2, 17, 0):
            raise KarakeepDeployError()
        existing_volumes = set(_command([*_DOCKER, 'volume', 'ls', '--format', '{{.Name}}']).splitlines())
        for volume in ('karakeep-data', 'karakeep-meilisearch-data'):
            name = self.project + '_' + volume
            if name in existing_volumes:
                labels = json.loads(_command([*_DOCKER, 'volume', 'inspect', '--format', '{{json .Labels}}', name]))
                if (not isinstance(labels, dict) or labels.get('com.docker.compose.project') != self.project
                    or labels.get('com.docker.compose.volume') != volume):
                    raise KarakeepDeployError()
        self._verify_topology()
        # Resolve only service consumers through the supervisor's already
        # decrypted systemd reader handle. An unissued acquisition key is absent
        # from this set, and no fallback or admin token is installed on the VM.
        reader = cfg.reader()
        contract = load_host_secret_contract()
        cache: dict[Any, Any] = {}
        return {consumer: _resolve_bws_consumer_values(cfg.channel, consumer, contract, reader,
                                                     lookup_cache=cache)
                for consumer in SERVICE_CONSUMERS}

    def materialize(self, values: dict[str, dict[str, str]]) -> None:
        # /run is owner-controlled tmpfs on the qualified Linux host. The
        # existing controller directory traversal rejects symlink ancestry.
        from app.ops.host_secret_controller import HostSecretController

        if (set(values) != set(SERVICE_CONSUMERS)
            or set(values['karakeep-service-web']) != {'karakeep.session-token', 'karakeep.search-token'}
            or set(values['karakeep-service-search']) != {'karakeep.search-token'}
            or values['karakeep-service-web']['karakeep.search-token'] != values['karakeep-service-search']['karakeep.search-token']
            or any(not validate_secret_value(secret.split('.', 1)[1], value)
                   for bindings in values.values() for secret, value in bindings.items())
            or not _server_url(self.server_url)):
            raise KarakeepDeployError()
        directory = HostSecretController._durable_directory(self.runtime)
        try:
            self.require_tmpfs()  # check the actual materialization filesystem too
            info = os.fstat(directory)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise KarakeepDeployError()
            web = values['karakeep-service-web']
            search = values['karakeep-service-search']
            fields = {
                'web.env': {'NEXTAUTH_SECRET': web['karakeep.session-token'],
                            'MEILI_MASTER_KEY': web['karakeep.search-token'], 'NEXTAUTH_URL': self.server_url},
                'search.env': {'MEILI_MASTER_KEY': search['karakeep.search-token']},
            }
            for name, bindings in fields.items():
                descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                                     0o600, dir_fd=directory)
                with os.fdopen(descriptor, 'w') as target:
                    info = os.fstat(target.fileno())
                    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                        or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                        raise KarakeepDeployError()
                    os.ftruncate(target.fileno(), 0)
                    target.write(''.join(f'{key}={value}\n' for key, value in bindings.items()))
        finally:
            os.close(directory)

    def compose(self, *arguments: str) -> str:
        return _command([*_DOCKER, 'compose', '--project-name', self.project,
                         '--env-file', '/dev/null', '-f', str(self.config.root / 'docker-compose.karakeep.yml'),
                         *arguments], env={'KARAKEEP_WEB_ENV_FILE': str(self.runtime / 'web.env'),
                                          'KARAKEEP_SEARCH_ENV_FILE': str(self.runtime / 'search.env')}, timeout=300)

    def install_boot(self) -> None:
        # No reader token in the new unit: it invokes the existing authenticated
        # root-only supervisor socket, which loads the encrypted channel reader.
        unit = ('[Unit]\nDescription=Private Karakeep ' + self.config.channel + '\n'
                'Requires=docker.service yggdrasil-bws-deploy@' + self.config.channel + '.service\n'
                'After=docker.service yggdrasil-bws-deploy@' + self.config.channel + '.service\n'
                '[Service]\nType=oneshot\nRemainAfterExit=yes\n'
                'Restart=on-failure\nRestartSec=5\nTimeoutStartSec=690\n'
                'ExecStart=/usr/local/libexec/yggdrasil-bws-deploy karakeep-boot ' + self.config.channel + '\n'
                'StandardOutput=null\nStandardError=null\n[Install]\nWantedBy=multi-user.target\n')
        path = self.unit_directory / ('yggdrasil-karakeep-' + self.config.channel + '.service')
        if path.exists():
            if path.is_symlink() or path.read_text() != unit:
                raise KarakeepDeployError()
        else:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            with os.fdopen(descriptor, 'w') as target:
                target.write(unit)
                target.flush()
                os.fsync(target.fileno())
        _command(['systemctl', 'daemon-reload'])
        _command(['systemctl', 'enable', path.name])

    def verify(self) -> None:
        self._verify_topology(healthy=True)
        _command(['curl', '--fail', '--silent', '--output', '/dev/null', '--max-time', '10',
                  'http://127.0.0.1:3000/'])


class KarakeepSupervisor:
    """One supervised worker on the existing channel reader service/socket."""
    def __init__(self, effects: KarakeepEffects) -> None:
        self.effects = effects
        self.mutex = threading.Lock()
        self.worker: threading.Thread | None = None
        self.finished = threading.Event()

    def _deploy(self, operation_id: str, plan: KarakeepPlan, boot: bool = False) -> None:
        journal = self.effects.boot_journal if boot else self.effects.journal
        lock = LinuxEffects(self.effects.config)
        lock.operation_id = operation_id
        try:
            with lock.channel_lock(journal=journal):
                try:
                    values = self.effects.preflight(plan, boot=boot)
                    journal.write(operation_id, 'preflighted')
                    self.effects.materialize(values)
                    del values
                    journal.write(operation_id, 'materialized')
                    # Persist the indeterminate boundary before ANY service mutation.
                    journal.write(operation_id, 'activating')
                    if not boot:
                        self.effects.install_boot()
                    self.effects.compose('up', '-d', '--wait', '--wait-timeout', '180')
                    self.effects.verify()
                    journal.write(operation_id, 'committed')
                except Exception:
                    previous = journal.read()
                    if previous and previous.stage in {'prepared', 'preflighted', 'materialized'}:
                        journal.write(operation_id, 'aborted')
                    raise
        except Exception:
            previous = journal.read()
            if previous and previous.stage in {'prepared', 'preflighted', 'materialized'}:
                journal.write(operation_id, 'aborted')
            # Exceptions after activating stay pending, without compensation,
            # receipt fabrication, duplicate deploy, or blind restart.
        finally:
            self.finished.set()

    def request(self, data: dict[str, Any]) -> dict[str, Any]:
        operation_id, plan = _valid_request(data, self.effects.config.channel)
        action = data['action']
        with self.mutex:
            journal = self.effects.boot_journal if action in {'karakeep-boot', 'karakeep-boot-status'} else self.effects.journal
            previous = journal.read()
            if action == 'karakeep-preflight':
                boot_previous = self.effects.boot_journal.read()
                if ((previous and previous.terminal_result is None)
                    or (boot_previous and boot_previous.terminal_result is None)):
                    raise KarakeepDeployError()
                self.effects.preflight(plan)
                return {'ready': True}
            if action == 'karakeep-boot':
                installed = self.effects.journal.read()
                if (not installed or installed.operation_id != data['prior_operation_id']
                    or installed.terminal_result != 'committed' or operation_id == installed.operation_id
                    or (previous and previous.terminal_result is None)
                    or (self.worker and self.worker.is_alive())):
                    raise KarakeepDeployError()
                self.effects.journal.bind_request(installed.operation_id, plan, False)
                self.effects.preflight(plan, boot=True)
                journal.bind_request(operation_id, plan, False, create=True)
                journal.write(operation_id, 'prepared')
                self.finished.clear()
                self.worker = threading.Thread(target=self._deploy, args=(operation_id, plan, True), daemon=True)
                self.worker.start()
            elif previous and previous.operation_id == operation_id:
                journal.bind_request(operation_id, plan, False)
                if previous.terminal_result is not None:
                    if previous.terminal_result == 'committed':
                        self.effects.verify()
                    return {'receipt': previous.payload()}
                # Never recreate a worker after supervisor loss.
            elif action == 'karakeep-deploy':
                boot_previous = self.effects.boot_journal.read()
                if ((previous and previous.terminal_result is None)
                    or (boot_previous and boot_previous.terminal_result is None)
                    or (self.worker and self.worker.is_alive())):
                    raise KarakeepDeployError()
                # Validate all host and selected credential inputs before the
                # first durable request mutation, not only inside the worker.
                self.effects.preflight(plan)
                journal.bind_request(operation_id, plan, False, create=True)
                journal.write(operation_id, 'prepared')
                self.finished.clear()
                self.worker = threading.Thread(target=self._deploy, args=(operation_id, plan), daemon=True)
                self.worker.start()
            else:
                raise KarakeepDeployError()
        if self.worker and self.worker.is_alive():
            self.finished.wait(25)
        current = journal.read()
        if not current or current.operation_id != operation_id:
            raise KarakeepDeployError()
        if current.terminal_result is None:
            if not self.worker or not self.worker.is_alive():
                return {'unknown': True}
            return {'pending': True}
        return {'receipt': current.payload()}


class SshKarakeepRemote:
    def request(self, action: str, operation_id: str, plan: KarakeepPlan) -> dict[str, Any]:
        plan.validate()
        try:
            command = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                       '-o', 'ConnectTimeout=10', '-o', 'ClearAllForwardings=yes',
                       '-o', 'PermitLocalCommand=no', '--', 'ygg-' + plan.channel,
                       'sudo', '-n', '/usr/local/libexec/yggdrasil-bws-deploy', 'rpc', plan.channel]
            result = subprocess.run(command, input=json.dumps({'action': action, 'operation_id': operation_id,
                                                              'plan': plan.payload()}) + '\n',
                                    env={key: os.environ[key] for key in ('PATH', 'HOME', 'SSH_AUTH_SOCK')
                                         if key in os.environ},
                                    capture_output=True, text=True, timeout=45, check=False)
            if result.returncode:
                raise KarakeepDeployError()
            payload = json.loads(result.stdout)
            if not isinstance(payload, dict) or payload.get('refused'):
                raise KarakeepDeployError()
            return payload
        except Exception:
            raise KarakeepDeployError() from None


def deploy_from_host(admin: SecretAdmin, remote: SshKarakeepRemote, plan: KarakeepPlan,
                     *, qualified: Any, operation_id: str | None = None) -> DeployReceipt:
    plan.validate()  # prod refusal precedes admission, provider lookup, and SSH.
    try:
        receipt = None
        with admin.controller.deploy_operation(plan.channel, allow_bootstrap=False,
                                               operation_id=operation_id) as (operation, resumed):
            qualified()
            if resumed:
                response = remote.request('karakeep-status', operation.operation_id, plan)
            else:
                statuses = admin.check_selected(operation, plan.channel, SERVICE_CONSUMERS)
                if any(row['status'] != 'ok' for row in statuses):
                    raise KarakeepDeployError()
                if remote.request('karakeep-preflight', operation.operation_id, plan) != {'ready': True}:
                    raise KarakeepDeployError()
                operation.prepare_mutation()
                response = remote.request('karakeep-deploy', operation.operation_id, plan)
            try:
                response = _observe_terminal(response, lambda: remote.request(
                    'karakeep-status', operation.operation_id, plan
                ))
            except KarakeepOperationPending:
                # Leave the existing context normally, without terminalizing;
                # its exception redactor would erase this typed pending result.
                pass
            else:
                if set(response) != {'receipt'}:
                    raise KarakeepDeployError()
                receipt = DeployReceipt(**response['receipt'])
                receipt.validate()
                if receipt.operation_id != operation.operation_id or receipt.channel != plan.channel:
                    raise KarakeepDeployError()
                operation.finish(receipt.evidence())
        if receipt is None:
            raise KarakeepOperationPending()
        return receipt
    except KarakeepOperationPending:
        raise
    except Exception:
        raise KarakeepDeployError() from None


def _require_vm_root() -> None:
    if os.geteuid() != 0 or sys.platform != 'linux':
        raise KarakeepDeployError()


def _installation_journal(channel: str) -> DeployJournal:
    return DeployJournal(Path('/var/lib/yggdrasil/karakeep'), channel)


def boot(channel: str) -> None:
    if channel not in {'dev', 'test'}:
        raise KarakeepDeployError()
    _require_vm_root()
    journal = _installation_journal(channel)
    previous = journal.read()
    if not previous or previous.terminal_result != 'committed':
        raise KarakeepDeployError()
    # The unchanged binding is authoritative; HEAD alone must not choose a new
    # deployment on boot. A changed checkout requires an explicit host request.
    settings = _private_json(journal.directory / (channel + '.request.json'))
    operation_id = str(uuid4())
    request = {'action': 'karakeep-boot', 'operation_id': operation_id,
               'prior_operation_id': previous.operation_id, 'plan': settings['plan']}
    response = rpc(channel, request)
    response = _observe_terminal(response, lambda: rpc(channel, {
        'action': 'karakeep-boot-status', 'operation_id': operation_id, 'plan': settings['plan']
    }))
    if set(response) != {'receipt'}:
        raise KarakeepDeployError()
    receipt = DeployReceipt(**response['receipt'])
    receipt.validate()
    if receipt.operation_id != operation_id or receipt.channel != channel or receipt.terminal_result != 'committed':
        raise KarakeepDeployError()


def main(argv: list[str] | None = None) -> int:
    from app.ops.secret_admin import _ValueFreeParser
    try:
        parser = _ValueFreeParser(prog='karakeep-deploy')
        parser.add_argument('channel', choices=('dev', 'test'))
        parser.add_argument('--revision', required=True)
        parser.add_argument('--operation-id')
        args = parser.parse_args(argv)
        plan = KarakeepPlan(args.channel, args.revision)
        plan.validate()
        admin = SecretAdmin(_configured_host_admin())
        receipt = deploy_from_host(admin, SshKarakeepRemote(), plan,
                                   qualified=lambda: require_qualification(admin.controller),
                                   operation_id=args.operation_id)
        print(json.dumps(receipt.payload(), sort_keys=True))
        return 0 if receipt.terminal_result == 'committed' else 78
    except KarakeepOperationPending:
        print(json.dumps({'status': 'pending', 'kind': 'deploy'}), file=sys.stderr)
        return 78
    except Exception:
        print('Karakeep operation refused; inspect matching value-free receipt', file=sys.stderr)
        return 78


if __name__ == '__main__':
    raise SystemExit(main())
