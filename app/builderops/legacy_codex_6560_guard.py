"""Scoped, operator-attributed #6560 custody check, not a Codex app lock.

The operator's no-new-manual-starts commitment coordinates starts that neither
this check nor dispatcher/registry locks can mechanically prevent.
"""
from __future__ import annotations

import contextlib
from datetime import datetime, timezone
import os
from pathlib import Path
import pwd
import re
import subprocess
from typing import Any, Iterator, Mapping

CHILD = '01a19af5-6d04-7cc3-a7fb-29dab5293c38'
WORKTREE = str(Path(pwd.getpwuid(os.getuid()).pw_dir) / '.codex/worktrees/issue-6560-operations-fixture-preparation/agentic-pkm-mvp')
GENERATION = 'e78714d7a59a409688d45b26a05dbe04'
PR = 6565
OWNER = 'codex-issue-6560-20261102'
HOLDER = 'codex-issue-6560'
LEASE = 'lease-dae68142'
PR_HEAD = '976e47f3b771ce5f609fdcfe15f84608fd9cd926'
DELEGATES = {
    '01a19af7-bacf-7c02-ae06-1875b01bcaff': 'completed',
    '01a19b07-5075-71b1-ba8d-4f6e113818d1': 'completed',
    '01a19b15-2ebd-74d0-bea6-89d64b61ab26': 'completed',
    '01a19b2f-3e38-7013-be2a-46a2b9308e05': 'completed',
    '01a19b4b-9a25-70c2-8914-cf56b05952fe': 'completed',
    '01a19b71-4a13-7d01-9cbb-5468af159a90': 'completed',
    '01a19b7d-aa56-7a73-b7af-1d18e02482f0': 'completed',
    '01a19b9f-ef23-7dc3-ae25-dfa2e08f4e24': 'completed',
    '01a19b22-e9f7-74e1-84a3-ca0e42d454ec': 'failed',
    '01a19b28-938a-77a2-a388-50c723c1ddcd': 'failed',
    '01a19b06-d1c4-7e70-ad38-ff60fa134b21': 'interrupted',
}
PUBLICATION_COMMANDS = [
    'exec-84040e83-2441-4dcb-bf13-b8d23df094b6',
    'exec-a47e119f-44d7-4915-b28f-31b6fb35440c',
    'exec-49d277dc-3c05-44c7-9635-d4b1bbd40bea',
    'exec-89eb98a1-1de8-446f-b068-80409509cbd8',
]


class CodexGuardError(ValueError):
    """The specifically identified custody evidence is unknown or changed."""


def _run(*args: str, allow_no_crontab: bool = False) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CodexGuardError('scoped host readback unavailable') from exc
    if result.returncode:
        if allow_no_crontab and result.returncode == 1 and 'no crontab for' in result.stderr.lower():
            return ''
        raise CodexGuardError('scoped host readback unavailable')
    if len(result.stdout) > 4_000_000:
        raise CodexGuardError('scoped host readback exceeds limit')
    return result.stdout


def _host_readback() -> tuple[int, str, str, str]:
    raw_boot = _run('/usr/sbin/sysctl', '-n', 'kern.boottime')
    match = re.search(r'\bsec\s*=\s*(\d+)', raw_boot)
    if match is None:
        raise CodexGuardError('host boot readback unavailable')
    return (int(match.group(1)), _run('/bin/ps', '-axo', 'pid=,ppid=,command='),
            _run('/bin/launchctl', 'print', f'gui/{os.getuid()}'),
            _run('/usr/bin/crontab', '-l', allow_no_crontab=True))


def check(*, issue: int, pr: int, worktree: Path, session: str, receipt: Mapping[str, Any]) -> None:
    evidence = receipt.get('codex_custody')
    fields = {'issue', 'pr', 'worktree', 'successor_session', 'child', 'delegates', 'publication_commands',
              'observed_at', 'boot', 'rejected_postboot_resume', 'identified_commands_terminal',
              'identified_writes_reconciled', 'historical_push_outputs', 'historical_edited_bodies',
              'postboot_identified_activity_reconciled', 'no_new_manual_starts', 'sources'}
    if (issue != 6560 or pr != PR or str(worktree) != WORKTREE or not isinstance(evidence, dict)
            or set(evidence) != fields or evidence.get('issue') != issue or evidence.get('pr') != pr
            or evidence.get('worktree') != WORKTREE or evidence.get('successor_session') != session
            or evidence.get('child') != CHILD or evidence.get('delegates') != DELEGATES
            or evidence.get('publication_commands') != PUBLICATION_COMMANDS
            or evidence.get('rejected_postboot_resume') != -32600
            or evidence.get('identified_commands_terminal') is not True
            or evidence.get('identified_writes_reconciled') is not True
            or evidence.get('historical_push_outputs') != 'unknown'
            or evidence.get('historical_edited_bodies') != 'unknown'
            or evidence.get('postboot_identified_activity_reconciled') is not True
            or evidence.get('no_new_manual_starts') is not True
            or receipt.get('predecessor_registration', {}).get('generation') != GENERATION
            or receipt.get('predecessor_registration', {}).get('owner') != OWNER
            or receipt.get('predecessor', {}).get('holder') != HOLDER
            or receipt.get('predecessor', {}).get('lease_id') != LEASE
            or receipt.get('publication', {}).get('pr') != pr
            or receipt.get('publication', {}).get('head') != PR_HEAD):
        raise CodexGuardError('scoped Codex operator evidence is missing or mismatched')
    sources = evidence.get('sources')
    keys = {'app_child_and_delegates', 'sqlite_parent_links', 'available_journal', 'rejected_resume',
            'boot', 'processes', 'launchctl', 'crontab', 'publication'}
    if (not isinstance(sources, dict) or set(sources) != keys
            or any(not isinstance(value, str) or not value.strip() for value in sources.values())):
        raise CodexGuardError('scoped Codex source references are incomplete')
    required_refs = {'app_child_and_delegates': CHILD, 'sqlite_parent_links': 'state_5.sqlite',
                     'available_journal': CHILD, 'rejected_resume': '-32600', 'boot': 'kern.boottime',
                     'processes': 'ps', 'launchctl': 'launchctl', 'crontab': 'crontab',
                     'publication': str(PR)}
    if any(token not in sources[name] for name, token in required_refs.items()):
        raise CodexGuardError('scoped Codex source references do not identify the observed sources')
    try:
        observed = datetime.fromisoformat(str(evidence['observed_at']).replace('Z', '+00:00'))
        boot = datetime.fromisoformat(str(evidence['boot']).replace('Z', '+00:00'))
        if observed.tzinfo is None or boot.tzinfo is None:
            raise ValueError('timezone missing')
        if not boot <= observed <= datetime.now(timezone.utc):
            raise ValueError('observation timing')
    except (KeyError, ValueError, OverflowError) as exc:
        raise CodexGuardError('scoped Codex observation time is invalid') from exc
    actual_boot, processes, launchctl, crontab = _host_readback()
    if int(boot.timestamp()) != actual_boot or evidence['boot'] != receipt.get('writer', {}).get('boot'):
        raise CodexGuardError('host reboot changed since operator observation')
    # Only explicitly identified target identities are matched; this does not
    # claim absence of arbitrary or unregistered processes or future starts.
    targets = (WORKTREE, CHILD, *DELEGATES, "issue-6560")
    own = {os.getpid(), os.getppid()}
    for line in processes.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
            raise CodexGuardError('scoped process readback malformed')
        if int(parts[0]) in own:
            continue
        if any(target in parts[2] for target in targets):
            raise CodexGuardError('identified Codex target process is active or ambiguous')
        if re.search(r'(?i)\bcodex\b', parts[2]):
            cwd = _run('/usr/sbin/lsof', '-a', '-p', parts[0], '-d', 'cwd', '-Fn')
            if any(line == 'n' + WORKTREE for line in cwd.splitlines()):
                raise CodexGuardError('Codex process holds target worktree cwd')
    if any(target in text for target in targets for text in (launchctl, crontab)):
        raise CodexGuardError('identified Codex restart target is active or ambiguous')


@contextlib.contextmanager
def hold(**kwargs: Any) -> Iterator[None]:
    check(**kwargs)
    yield
