"""Fixed API-consumer producer for a supervised native deployment.

The run-only selector is not authority. The host's inherited BWS operation
guard, ordinary API instance preflight, migration authority and file-backed
database consumer remain the admission boundaries. No child output escapes.
"""
from __future__ import annotations

import contextlib
from collections.abc import Callable
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, cast

SOURCE_TIMEOUT_SECONDS = 7200
COMPOSE_TIMEOUT_SECONDS = SOURCE_TIMEOUT_SECONDS + 60
_SUMMARY_LIMIT = 1024 * 1024
_COUNTERS = ('scanned', 'ingested', 'errors', 'malformed', 'skipped_locked', 'skipped_invalid')
SOURCE_PROJECTION_FAILURE_CODES = {
    'vector_projection_failed': 79,
    'embedding_generation_failed': 80,
    'vector_index_write_failed': 81,
    'source_preflight_failed': 82,
    'source_readiness_failed': 83,
    'source_command_failed': 84,
    'source_summary_invalid': 85,
    'source_post_rebuild_failed': 86,
    'source_doctor_failed': 87,
    'source_settings_failed': 88,
    'source_worker_failed': 89,
    'legacy_producer_policy_refused': 90,
    'legacy_source_refused': 91,
    'legacy_admission_refused': 92,
    'legacy_identity_refused': 93,
    'legacy_race_refused': 94,
    'legacy_write_failed': 95,
    'source_worker_timeout': 96,
    'source_worker_terminated': 97,
    'source_worker_oom': 98,
}


def source_terminal_reason(status: int, *, oom_killed: bool = False) -> str | None:
    if oom_killed:
        return 'source_worker_oom'
    if status == 0:
        return None
    if status == 124:
        return 'source_worker_timeout'
    if status in {130, 143, -2, -15}:
        return 'source_worker_terminated'
    # 96–98 encode the host observer's result, not worker checkpoint exits.
    # In particular a raw 98 cannot assert Docker's OOMKilled state.
    return next((reason for reason, code in SOURCE_PROJECTION_FAILURE_CODES.items()
                 if code == status and reason not in {
                     'source_worker_timeout', 'source_worker_terminated', 'source_worker_oom',
                 }), 'source_worker_failed')


class SourceVectorProjectionFailure(RuntimeError):
    """Fixed private-child classification; never retain provider diagnostics."""


class SourceBootstrapFailure(ValueError):
    """A fixed checkpoint code, not exception or child-output text."""

    def __init__(self, reason: str) -> None:
        self.code = SOURCE_PROJECTION_FAILURE_CODES[reason]
        super().__init__(reason.replace('_', ' '))


def _checkpoint(reason: str, function: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return function(*args, **kwargs)
    except (SourceBootstrapFailure, SourceVectorProjectionFailure):
        raise
    except Exception:
        raise SourceBootstrapFailure(reason) from None


def source_rebuild_counts(payload: Any) -> tuple[int, ...]:
    """Require all six actual counters; absent, coerced or negative is unknown."""
    if not isinstance(payload, dict):
        raise ValueError('source summary invalid')
    values = tuple(payload.get(key) for key in _COUNTERS)
    if any(type(value) is not int or value < 0 for value in values):
        raise ValueError('source summary invalid')
    return cast(tuple[int, ...], values)


def source_rebuild_complete(payload: Any) -> bool:
    scanned, ingested, errors, malformed, locked, invalid = source_rebuild_counts(payload)
    return scanned == ingested and not any((errors, malformed, locked, invalid))


def wait_for_owned_child(argv: list[str], *, timeout: float) -> int:
    """Reap our CLI and its process group; Docker ownership is checked separately."""
    interrupted = 0

    def record_signal(signum: int, _frame: Any) -> None:
        nonlocal interrupted
        interrupted = signum

    previous = {signum: signal.signal(signum, record_signal)
                for signum in (signal.SIGTERM, signal.SIGINT)}
    try:
        child = subprocess.Popen(argv, start_new_session=True)
        deadline = time.monotonic() + timeout
        while not interrupted:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                status = child.wait(timeout=min(remaining, 1))
                if not interrupted:
                    return status
                break
            except subprocess.TimeoutExpired:
                pass
        result = 128 + interrupted if interrupted else 124
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        # A reaped parent is not proof that its descendants stopped. Kill the
        # entire owned group even if the parent acknowledged TERM immediately.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait(timeout=5)
        return result
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def quiesce_owned_container(channel: str, name: str, operation: str, revision: str, *,
                            observe_terminal: Callable[[int, bool], None] | None = None,
                            docker_command: Callable[..., str] | None = None) -> bool:
    """Prove absence/stoppage of only this operation's Docker API one-shot."""
    if (
        channel not in {'dev', 'test', 'prod'}
        or re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', operation) is None
        or re.fullmatch(r'[0-9a-f]{40}', revision) is None
        or name != f'pkm-{channel}-source-bootstrap-{operation}'
    ):
        return False

    def docker(*arguments: str, timeout: int = 15) -> str:
        if docker_command is not None:
            return docker_command(['docker', *arguments], timeout=timeout).strip()
        return subprocess.run(
            ['docker', *arguments], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, check=True, timeout=timeout,
        ).stdout.strip()

    def inventory() -> str:
        result = docker(
            'ps', '--all', '--filter', f'name=^/{name}$',
            '--filter', f'label=com.docker.compose.project=pkm-{channel}',
            '--filter', 'label=com.docker.compose.service=api',
            '--filter', 'label=com.docker.compose.oneoff=True', '--format', '{{.ID}}',
        )
        if result and re.fullmatch(r'[0-9a-f]{12,64}', result) is None:
            raise ValueError('source inventory invalid')
        return result

    def owned_state(cid: str) -> str:
        fields = docker('inspect', '--format',
            '{{.Name}} {{index .Config.Labels "com.docker.compose.project"}} '
            '{{index .Config.Labels "com.docker.compose.service"}} '
            '{{index .Config.Labels "com.docker.compose.oneoff"}} '
            '{{index .Config.Labels "yggdrasil.native.operation"}} '
            '{{index .Config.Labels "yggdrasil.native.revision"}} {{.State.Running}}', cid).split()
        if len(fields) != 7 or fields[:6] != [
            '/' + name, 'pkm-' + channel, 'api', 'True', operation, revision,
        ]:
            raise ValueError('source ownership invalid')
        return fields[6]

    try:
        cid = inventory()
        if not cid:
            return True
        state = owned_state(cid)
        if state == 'true':
            # A lost stop acknowledgement is harmless only if the next daemon
            # read proves that our container disappeared or actually stopped.
            try:
                docker('stop', '--time', '10', cid, timeout=20)
            except (subprocess.SubprocessError, OSError):
                pass
            remaining = inventory()
            if not remaining:
                return True
            if remaining != cid:
                return False
            state = owned_state(cid)
        if state != 'false':
            return False
        if observe_terminal is not None:
            # Revalidate exact ownership after stop, then read only fixed Docker
            # state fields. Never parse Error, logs, labels or free-form output.
            if owned_state(cid) != 'false':
                return False
            fields = docker('inspect', '--format',
                            '{{.State.Status}} {{.State.ExitCode}} {{.State.OOMKilled}}', cid).split()
            if (len(fields) != 3 or fields[0] not in {'exited', 'dead'}
                or re.fullmatch(r'[0-9]{1,3}', fields[1]) is None
                or not 0 <= int(fields[1]) <= 255 or fields[2] not in {'true', 'false'}):
                return False
            observe_terminal(int(fields[1]), fields[2] == 'true')
        docker('rm', cid)
        return True
    except (subprocess.SubprocessError, OSError, ValueError):
        return False


def _instance_preflight(channel: str) -> None:
    from app.instance.runtime import _preflight_runtime

    _preflight_runtime(
        channel=channel, instance_state_root=Path('/app/instance-state'),
        host_global_root=Path('/app/instance-ownership'), consumer='api',
    )


def preflight(selector: str) -> Path | None:
    from app.config.environment import active_environment
    from app.config.paths import resolve_optional_vault_root
    from app.objects import resolve_store_backend
    from app.version import get_runtime_version

    match = re.fullmatch(r'(dev|test|prod):([0-9a-f]{40})', selector)
    if (
        match is None or os.environ.get('NATIVE_SOURCE_BOOTSTRAP') != selector
        or os.environ.get('PKM_ENVIRONMENT') != match[1]
        or active_environment() != match[1]
        or get_runtime_version().get('git_sha') != match[2]
    ):
        raise ValueError('source context invalid')
    # Use the ordinary API binding and its ownership/floor/restart-fence guard.
    # No legacy rollback branch or caller-supplied registry/root is admitted.
    with open(os.devnull, 'w') as quiet, contextlib.redirect_stdout(quiet):
        _instance_preflight(match[1])
    selected = resolve_optional_vault_root()
    root = selected.resolve(strict=True) if selected is not None else None
    # Backend selection validates configuration without constructing the store.
    # StorePort construction can run provider initialization/repair effects, so
    # defer it until the bound-root Product-readiness path below.
    if (root is not None and not root.is_dir()) or resolve_store_backend() != 'pg':
        raise ValueError('source context invalid')
    return root


def _product_ready(root: Path) -> bool:
    from app.rebuildability import evaluate_product_store_readiness
    from app.rebuildability.product_total_loss import _is_product_row
    from app.objects import resolve_object_store_port

    rows = list(resolve_object_store_port().store.list_objects(limit=None))
    readiness = evaluate_product_store_readiness(root, rows)
    # Empty retained sources do not prove that this binding is empty. Refuse
    # stale Product rows without deleting them or admitting ordinary writers.
    return readiness.ready is True and (
        readiness.state != 'empty' or not any(_is_product_row(row) for row in rows)
    )


def _run_json(arguments: list[str]) -> Any:
    # Producer summaries can include examples and paths. Inspect them privately;
    # never print child stdout, stderr, exceptions or an untrusted summary field.
    command_reason = ('source_settings_failed' if arguments[:2] == ['settings', 'validate']
                      else 'source_doctor_failed' if arguments[:2] == ['index', 'doctor']
                      else 'source_command_failed')
    with tempfile.TemporaryFile() as output:
        result = _checkpoint(command_reason, subprocess.run,
            [sys.executable, '-m', 'app.cli', *arguments],
            stdout=output, stderr=subprocess.DEVNULL, check=False,
        )
        if result.returncode and result.returncode != 79:
            raise SourceBootstrapFailure(command_reason)
        output.seek(0)
        raw = output.read(_SUMMARY_LIMIT + 1)
        if len(raw) > _SUMMARY_LIMIT:
            raise SourceBootstrapFailure('source_summary_invalid')
        payload = _checkpoint('source_summary_invalid', json.loads, raw)
        if result.returncode:
            if arguments[:2] in (['index', 'repair-missing'], ['index', 'reconcile-legacy']):
                from app.rebuildability.legacy_source import LEGACY_RECONCILIATION_REASONS
                reason = payload.get('reason') if isinstance(payload, dict) else None
                allowed = {'source_post_rebuild_failed', 'embedding_generation_failed', 'vector_index_write_failed'}
                if arguments[:2] == ['index', 'reconcile-legacy']:
                    allowed |= LEGACY_RECONCILIATION_REASONS
                if reason not in allowed:
                    raise SourceBootstrapFailure('source_summary_invalid')
                raise SourceBootstrapFailure(reason)
            counts = _checkpoint('source_summary_invalid', source_rebuild_counts, payload)
            failures = payload.get('vector_projection_errors')
            if (
                arguments[:1] == ['vault-alpha-ingest']
                and '--source-backed-rebuild' in arguments
                and type(failures) is int and 0 < failures <= counts[2]
                and counts[1] + counts[2] <= counts[0]
            ):
                reasons = payload.get('vector_projection_failure_counts')
                if reasons is None:
                    reason = 'vector_projection_failed'  # Prior candidate summary.
                elif (
                    isinstance(reasons, dict) and reasons
                    and all(key in {'vector_projection_failed', 'embedding_generation_failed',
                                    'vector_index_write_failed'} for key in reasons)
                    and all(type(value) is int and value > 0 for value in reasons.values())
                    and sum(reasons.values()) == failures
                ):
                    reason = next(iter(reasons)) if len(reasons) == 1 else 'vector_projection_failed'
                else:
                    raise SourceBootstrapFailure('source_summary_invalid')
                raise SourceVectorProjectionFailure(reason)
            raise SourceBootstrapFailure('source_command_failed')
        return payload


def _diagnosis_unembedded_count(diagnosis: Any) -> int:
    if (
        not isinstance(diagnosis, dict)
        or diagnosis.get('backend') != 'PgVectorIndex'
        or type(diagnosis.get('unembedded_object_count')) is not int
        or diagnosis['unembedded_object_count'] < 0
        or type(diagnosis.get('non_vector_issue_count')) is not int
        or diagnosis['non_vector_issue_count'] < 0
        or not isinstance(diagnosis.get('issues'), list)
        or any(not isinstance(issue, str) for issue in diagnosis['issues'])
        or type(diagnosis.get('rebuild_required')) is not bool
        or not isinstance(diagnosis.get('pg_state'), dict)
        or len(diagnosis['issues'])
        != diagnosis['non_vector_issue_count'] + int(diagnosis['unembedded_object_count'] > 0)
    ):
        raise ValueError('source index diagnosis invalid')
    return diagnosis['unembedded_object_count']


def rebuild_if_needed(selector: str) -> None:
    root = _checkpoint('source_preflight_failed', preflight, selector)
    if root is None:
        # Preserve the ordinary explicitly unbound API/picker posture. Missing
        # or invalid configured roots still raise at the canonical resolver.
        return
    _checkpoint('source_settings_failed', _run_json, ['settings', 'validate', '--json'])
    product_ready = _checkpoint('source_readiness_failed', _product_ready, root)
    rebuild_source_projection = not product_ready
    if product_ready:
        preflight_diagnosis = _run_json(['index', 'doctor', '--json'])
        unembedded_count = _checkpoint('source_doctor_failed', _diagnosis_unembedded_count, preflight_diagnosis)
        rebuild_source_projection = (
            unembedded_count > 0 and preflight_diagnosis['non_vector_issue_count'] == 0
        )
    if rebuild_source_projection:
        summary = _run_json([
            'vault-alpha-ingest', '--vault-root', str(root), '--max-notes', '0',
            '--force', '--source-backed-rebuild', '--json',
        ])
        if not _checkpoint('source_summary_invalid', source_rebuild_complete, summary):
            raise SourceBootstrapFailure('source_post_rebuild_failed')
        remaining = _run_json(['index', 'doctor', '--json'])
        missing = _checkpoint('source_doctor_failed', _diagnosis_unembedded_count, remaining)
        if missing > 0 and remaining['non_vector_issue_count'] == 0:
            reconciled = _run_json(['index', 'reconcile-legacy', '--json'])
            if (not isinstance(reconciled, dict) or type(reconciled.get('processed')) is not int
                    or reconciled['processed'] < 0):
                raise SourceBootstrapFailure('source_summary_invalid')
            repaired = _run_json(['index', 'repair-missing', '--json'])
            if (not isinstance(repaired, dict) or type(repaired.get('processed')) is not int
                    or repaired['processed'] < 0):
                raise SourceBootstrapFailure('source_summary_invalid')
        if not _checkpoint('source_post_rebuild_failed', _product_ready, root):
            raise SourceBootstrapFailure('source_post_rebuild_failed')
    diagnosis = _run_json(['index', 'doctor', '--json', '--strict'])
    unembedded_count = _checkpoint('source_doctor_failed', _diagnosis_unembedded_count, diagnosis)
    if (
        diagnosis.get('issues') != [] or diagnosis.get('rebuild_required') is not False
        or unembedded_count != 0 or diagnosis.get('non_vector_issue_count') != 0
    ):
        raise SourceBootstrapFailure('source_doctor_failed')


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 2 or arguments[0] not in {'--preflight', '--run', '--worker'}:
        return SOURCE_PROJECTION_FAILURE_CODES['source_preflight_failed']
    mode, selector = arguments
    try:
        if mode == '--preflight':
            _checkpoint('source_preflight_failed', preflight, selector)
        elif mode == '--worker':
            rebuild_if_needed(selector)
        else:
            _checkpoint('source_preflight_failed', preflight, selector)
            return wait_for_owned_child(
                [sys.executable, '-m', 'app.ops.native_source_bootstrap', '--worker', selector],
                timeout=SOURCE_TIMEOUT_SECONDS,
            )
    except SourceVectorProjectionFailure as exc:
        return SOURCE_PROJECTION_FAILURE_CODES.get(str(exc), 78)
    except SourceBootstrapFailure as exc:
        return exc.code
    except Exception:
        return SOURCE_PROJECTION_FAILURE_CODES['source_worker_failed']
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
