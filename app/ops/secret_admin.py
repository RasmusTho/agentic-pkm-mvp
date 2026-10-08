"""Value-free command surface for selected BWS checks and stdin imports.

Prior-value snapshots are kept in a dedicated owner-only append-only history file,
never the value-free controller journal or diagnostics. Unknown provider outcomes
remain pending indefinitely: this module has no operator override or marker heuristic.
"""
from __future__ import annotations

import argparse
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
from typing import Any, Never, TextIO
from uuid import UUID, uuid4

from app.ops.bws_secret_admin import (
    PrecommitRejection, SecretAdminError, SecretAdminProvider, SecretCopy, configured_admin,
)
from app.ops.bws_token_push import TokenPushAdmin, load_token_push_targets
from app.ops.host_secret_bootstrap import validate_secret_value
from app.ops.host_secret_contract import (
    BWS_IDENTITIES, CHANNEL_PROJECTS, DATABASE_CONSUMERS, HostSecretContract,
    load_host_secret_contract,
)
from app.ops.host_secret_controller import (
    HostSecretController, HostSecretOperation, TerminalEvidence,
)

# Every currently declared identity is externally issued, a protected Heimdal
# key, or a database credential. A future BWS-owned identity needs its own contract.
BWS_OWNED_GENERATION_ALLOWLIST: frozenset[str] = frozenset()
_MARKER_PREFIX = '[yggdrasil-secret-operation:'


def _note(owner_note: str, operation_id: str) -> str:
    # Keep owner text verbatim; old operation markers are correlation history only.
    return owner_note + ('\n' if owner_note else '') + f'{_MARKER_PREFIX}{operation_id}]'


def _evidence(operation: HostSecretOperation, result: str) -> TerminalEvidence:
    return TerminalEvidence(operation.operation_id, operation.kind, operation.target,
                            result, 'read-complete' if operation.kind == 'check' else 'provider-terminal')


class SecretHistory:
    """Append-only snapshots and send outcomes, fsynced while the host lock is held.

    Each snapshot includes project and logical identity, plus a value only when
    the prior state existed. This private history is not an output/receipt/log.
    The controller's path policy excludes Git/iCloud and checks ownership/modes.
    A partial record poisons recovery; there is no truncate/delete repair path.
    """
    def __init__(self, descriptor: int) -> None:
        self.descriptor = descriptor

    @classmethod
    @contextmanager
    def open(cls, directory: Path) -> Iterator[SecretHistory]:
        directory_fd = file_fd = None
        try:
            directory_fd = HostSecretController._durable_directory(directory)
            file_fd = HostSecretController._open_file(directory_fd, 'secret-history.jsonl')
            os.fsync(directory_fd)
            yield cls(file_fd)
        except Exception:
            raise SecretAdminError() from None
        finally:
            for fd in (file_fd, directory_fd):
                if fd is not None:
                    os.close(fd)

    def append(self, **record: Any) -> None:
        raw = (json.dumps(record, sort_keys=True, ensure_ascii=True) + '\n').encode()
        if os.write(self.descriptor, raw) != len(raw):
            raise SecretAdminError()
        os.fsync(self.descriptor)

    def records(self, operation_id: str) -> list[dict[str, Any]]:
        os.lseek(self.descriptor, 0, os.SEEK_SET)
        records = []
        with os.fdopen(os.dup(self.descriptor), 'r', encoding='utf-8') as source:
            for line in source:
                if not line.endswith('\n'):
                    raise SecretAdminError()
                record = json.loads(line)
                if not isinstance(record, dict) or record.get('event') not in {
                    'snapshot', 'prepared', 'sent', 'committed', 'rejected', 'terminal',
                } or str(UUID(record['operation_id'])) != record['operation_id']:
                    raise SecretAdminError()
                if record['operation_id'] == operation_id:
                    records.append(record)
        return records

    def require_terminal_sends(self, operation_id: str, identity: str, was_sent: bool) -> str | None:
        records = self.records(operation_id)
        if was_sent and not records:
            raise SecretAdminError()
        sends: set[str] = set()
        outcomes: set[str] = set()
        previous_attempt = None
        for record in records:
            if record.get('identity') != identity:
                raise SecretAdminError()
            previous_attempt = record['attempt_id']
            if record['event'] == 'sent':
                request = record['request_id']
                if request in sends:
                    raise SecretAdminError()
                sends.add(request)
            elif record['event'] in {'committed', 'rejected'}:
                request = record['request_id']
                if request not in sends or request in outcomes:
                    raise SecretAdminError()
                outcomes.add(request)
        if sends != outcomes:
            raise SecretAdminError()
        return previous_attempt


class SecretAdmin:
    def __init__(self, provider: SecretAdminProvider, *,
                 controller: HostSecretController | None = None,
                 contract: HostSecretContract | None = None) -> None:
        self.provider = provider
        self.controller = controller or HostSecretController()
        self.contract = contract or load_host_secret_contract()

    def _identity(self, channel: str, secret: str) -> tuple[str, tuple[str, ...]]:
        if channel not in CHANNEL_PROJECTS or secret not in BWS_IDENTITIES:
            raise SecretAdminError()
        if secret == 'typesafe.api-key' and channel != 'dev':
            raise SecretAdminError()
        if BWS_IDENTITIES[secret] == 'shared':
            return 'shared/' + secret, ('non-prod', 'prod')
        return channel + '/' + secret, (CHANNEL_PROJECTS[channel],)

    def _kind(self, secret: str) -> str:
        return 'password' if secret == 'postgres.password' else self.contract.kind_for(secret)

    def check_selected(self, operation: HostSecretOperation, channel: str,
                       consumers: Sequence[str]) -> list[dict[str, str]]:
        """Preflight seam for BWS-04: caller holds the host lock through Compose.

        This does not grant live deploy admission, own VM locks, or finish a deploy.
        """
        operation.require_active(channel)
        if operation.kind not in {'check', 'deploy'} or not consumers:
            raise SecretAdminError()
        selected: dict[str, set[str]] = {}
        for consumer in consumers:
            if consumer in DATABASE_CONSUMERS:
                self.contract.file_binding(channel=channel, consumer=consumer, secret='postgres.password')
                selected.setdefault('postgres.password', set()).add(consumer)
            else:
                bindings = {secret for ch, name, secret in self.contract.allowed
                            if ch == channel and name == consumer}
                if not bindings:
                    raise SecretAdminError()
                for secret in bindings:
                    selected.setdefault(secret, set()).add(consumer)
        statuses = []
        for secret in sorted(selected):
            identity, projects = self._identity(channel, secret)
            copies = [self.provider.read(project, identity) for project in projects]
            absent = sum(copy is None for copy in copies)
            status = 'ok'
            if absent:
                all_selected_consumers_allow_absence = (
                    secret != 'postgres.password'
                    and all(self.contract.is_optional_for_consumer(
                        channel=channel, consumer=consumer, secret=secret
                    ) for consumer in selected[secret])
                )
                status = ('skipped' if absent == len(copies)
                          and all_selected_consumers_allow_absence else 'missing')
            if any(copy is not None and not validate_secret_value(self._kind(secret), copy.value)
                   for copy in copies):
                status = 'invalid'
            elif not absent and len({copy.value for copy in copies if copy is not None}) > 1:
                status = 'divergent'
            statuses.append({'secret': secret, 'status': status})
        return statuses

    def check(self, channel: str, consumers: Sequence[str]) -> list[dict[str, str]]:
        try:
            with self.controller.admit('check', channel) as operation:
                try:
                    statuses = self.check_selected(operation, channel, consumers)
                except Exception:
                    operation.finish(_evidence(operation, 'aborted'))
                    raise
                operation.finish(_evidence(operation, 'committed'))
                return statuses
        except Exception:
            raise SecretAdminError() from None

    def import_stdin(self, channel: str, secret: str, source: TextIO) -> str:
        try:
            identity, projects = self._identity(channel, secret)
            if secret == 'heimdal.archive-pass' or (secret == 'heimdal.raw-store-key' and channel == 'prod'):
                raise SecretAdminError()
            # Exact stdin bytes (decoded by the stream), including any newline. Do
            # not strip or truncate an existing database credential into a new one.
            value = source.read()
            if not isinstance(value, str) or not validate_secret_value(self._kind(secret), value):
                raise SecretAdminError()
            target = 'shared' if len(projects) == 2 else channel
            with self.controller.import_operation(target) as (operation, was_sent):
                with SecretHistory.open(self.controller.directory) as history:
                    previous_attempt = history.require_terminal_sends(operation.operation_id, identity, was_sent)
                    attempt = str(uuid4())
                    common = dict(operation_id=operation.operation_id, attempt_id=attempt, identity=identity)
                    previous = {p: self.provider.read(p, identity) for p in projects}
                    for project, copy in previous.items():
                        record: dict[str, Any] = dict(common, event='snapshot', project=project,
                                                      previous_state='present' if copy else 'absent')
                        if copy is not None:
                            record.update(item_id=copy.item_id, value=copy.value, note=copy.note)
                        history.append(**record)
                    history.append(**common, event='prepared', previous_attempt=previous_attempt)
                    committed: dict[str, SecretCopy] = {}
                    try:
                        for project in projects:
                            copy = previous[project]
                            committed[project] = self._send_put(history, operation, common, project,
                                identity, copy, value, _note(copy.note if copy else '', operation.operation_id))
                    except PrecommitRejection:
                        # Every prior send is terminal here. Unknown exceptions take
                        # the outer refusal path with NO compensation or retry.
                        for project, current in committed.items():
                            copy = previous[project]
                            if copy is None:
                                self._send_delete(history, operation, common, project, identity, current)
                            else:
                                self._send_put(history, operation, common, project, identity, current,
                                               copy.value, _note(copy.note, operation.operation_id))
                        history.append(**common, event='terminal', result='aborted')
                        operation.finish(_evidence(operation, 'aborted'))
                        raise SecretAdminError() from None
                    copies = [self.provider.read(p, identity) for p in projects]
                    if any(copy is None or copy.value != value for copy in copies):
                        raise SecretAdminError()
                    history.append(**common, event='terminal', result='committed', previous_attempt=previous_attempt)
                    operation.finish(_evidence(operation, 'committed'))
                    return 'imported'
        except Exception:
            raise SecretAdminError() from None

    def _send_put(self, history: SecretHistory, operation: HostSecretOperation,
                  common: dict[str, Any], project: str, identity: str,
                  previous: SecretCopy | None, value: str, note: str) -> SecretCopy:
        request_id = str(uuid4())
        history.append(**common, event='sent', project=project, request_id=request_id, action='put')
        operation.prepare_mutation()
        try:
            result = self.provider.put(project, identity, previous, value, note)
        except PrecommitRejection:
            history.append(**common, event='rejected', project=project, request_id=request_id)
            raise
        history.append(**common, event='committed', project=project, request_id=request_id)
        return result

    def _send_delete(self, history: SecretHistory, operation: HostSecretOperation,
                     common: dict[str, Any], project: str, identity: str, current: SecretCopy) -> None:
        request_id = str(uuid4())
        history.append(**common, event='sent', project=project, request_id=request_id, action='delete')
        operation.prepare_mutation()
        try:
            self.provider.delete(project, identity, current)
        except PrecommitRejection:
            history.append(**common, event='rejected', project=project, request_id=request_id)
            raise
        history.append(**common, event='committed', project=project, request_id=request_id)

    def generate(self, channel: str, secret: str) -> None:
        # Closed deny-by-default policy. No generic PostgreSQL first-init bypass.
        self._identity(channel, secret)
        raise SecretAdminError()

    rotate = generate


class _ValueFreeParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        # argparse normally repeats rejected arguments, which might be a value.
        raise SecretAdminError()


def main(argv: Sequence[str] | None = None, *, admin: SecretAdmin | None = None,
         stdin: TextIO | None = None,
         token_push_admin: TokenPushAdmin | None = None) -> int:
    try:
        parser = _ValueFreeParser(prog='secrets')
        sub = parser.add_subparsers(dest='command', required=True)
        check = sub.add_parser('check')
        check.add_argument('channel', choices=tuple(CHANNEL_PROJECTS))
        check.add_argument('--consumer', action='append', required=True)
        token_push = sub.add_parser('push-token')
        token_push.add_argument('vm')
        for command in ('import', 'generate', 'rotate'):
            cmd = sub.add_parser(command)
            cmd.add_argument('channel', choices=tuple(CHANNEL_PROJECTS))
            cmd.add_argument('secret', choices=tuple(BWS_IDENTITIES))
            if command == 'import':
                cmd.add_argument('--stdin', action='store_true', required=True)
        args = parser.parse_args(argv)
        if args.command == 'push-token':
            target = load_token_push_targets().get(args.vm)
            if target is None:
                raise SecretAdminError()
            (token_push_admin or TokenPushAdmin()).push(args.vm)
            print(json.dumps({
                'target': target.vm,
                'project': target.project,
                'status': 'pushed',
            }, sort_keys=True))
            return 0
        selected = admin or SecretAdmin(configured_admin())
        if args.command == 'check':
            statuses = selected.check(args.channel, args.consumer)
            print(json.dumps(statuses, sort_keys=True))
            return 0 if all(s['status'] in {'ok', 'skipped'} for s in statuses) else 1
        if args.command == 'import':
            selected.import_stdin(args.channel, args.secret, stdin or sys.stdin)
        else:
            selected.generate(args.channel, args.secret)
        # A write receipt is constant: neither stdin nor caller arguments flow
        # into output. Consumer checks separately report canonical logical IDs.
        print(json.dumps({'status': 'imported'}))
        return 0
    except Exception:
        print('secret administration refused; operation may remain pending', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
