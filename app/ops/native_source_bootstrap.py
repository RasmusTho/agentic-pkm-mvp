"""Fixed API-consumer producer for a supervised native deployment.

The run-only selector is not authority. The host's inherited BWS operation
guard, ordinary API instance preflight, migration authority and file-backed
database consumer remain the admission boundaries. No child output escapes.
"""
from __future__ import annotations

import contextlib
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


def quiesce_owned_container(channel: str, name: str, operation: str, revision: str) -> bool:
    """Prove absence/stoppage of only this operation's Docker API one-shot."""
    if (
        channel not in {'dev', 'test', 'prod'}
        or re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', operation) is None
        or re.fullmatch(r'[0-9a-f]{40}', revision) is None
        or name != f'pkm-{channel}-source-bootstrap-{operation}'
    ):
        return False

    def docker(*arguments: str, timeout: int = 15) -> str:
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
    from app.stores import resolve_store_backend
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
    if (root is not None and not root.is_dir()) or resolve_store_backend() != 'pg':
        raise ValueError('source context invalid')
    return root


def _product_ready(root: Path) -> bool:
    from app.rebuildability import evaluate_product_store_readiness
    from app.stores import get_object_store

    return evaluate_product_store_readiness(
        root, get_object_store().list_objects(limit=None),
    ).ready is True


def _run_json(arguments: list[str]) -> Any:
    # Producer summaries can include examples and paths. Inspect them privately;
    # never print child stdout, stderr, exceptions or an untrusted summary field.
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(
            [sys.executable, '-m', 'app.cli', *arguments],
            stdout=output, stderr=subprocess.DEVNULL, check=False,
        )
        if result.returncode:
            raise ValueError('source command failed')
        output.seek(0)
        raw = output.read(_SUMMARY_LIMIT + 1)
        if len(raw) > _SUMMARY_LIMIT:
            raise ValueError('source summary invalid')
        return json.loads(raw)


def rebuild_if_needed(selector: str) -> None:
    root = preflight(selector)
    if root is None:
        # Preserve the ordinary explicitly unbound API/picker posture. Missing
        # or invalid configured roots still raise at the canonical resolver.
        return
    _run_json(['settings', 'validate', '--json'])
    if not _product_ready(root):
        summary = _run_json([
            'vault-alpha-ingest', '--vault-root', str(root), '--max-notes', '0',
            '--force', '--source-backed-rebuild', '--json',
        ])
        if not source_rebuild_complete(summary) or not _product_ready(root):
            raise ValueError('source projection incomplete')
    diagnosis = _run_json(['index', 'doctor', '--json', '--strict'])
    if (
        not isinstance(diagnosis, dict) or diagnosis.get('backend') != 'PgVectorIndex'
        or diagnosis.get('issues') != [] or diagnosis.get('rebuild_required') is not False
        or not isinstance(diagnosis.get('pg_state'), dict)
    ):
        raise ValueError('source index not ready')


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 2 or arguments[0] not in {'--preflight', '--run', '--worker'}:
        return 78
    mode, selector = arguments
    try:
        if mode == '--preflight':
            preflight(selector)
        elif mode == '--worker':
            rebuild_if_needed(selector)
        else:
            preflight(selector)
            return wait_for_owned_child(
                [sys.executable, '-m', 'app.ops.native_source_bootstrap', '--worker', selector],
                timeout=SOURCE_TIMEOUT_SECONDS,
            )
    except Exception:
        return 78
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
