"""Optional, root-owned memory budgets for disposable DEV/TEST acceptance."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

CONFIG_ROOT = Path('/etc/yggdrasil/bws-deploy')
MIN_MEMORY = 6 * 1024**2  # Docker's documented minimum.
MAX_INTEGER = 2**63 - 1


class AcceptanceMemoryError(ValueError):
    """A configured test-memory policy cannot be safely applied."""


@dataclass(frozen=True)
class MemoryLimit:
    memory: int
    memory_swap: int

    def __post_init__(self) -> None:
        if (type(self.memory) is not int or type(self.memory_swap) is not int
            or self.memory < MIN_MEMORY or self.memory > MAX_INTEGER
            or not self.memory <= self.memory_swap <= MAX_INTEGER):
            raise AcceptanceMemoryError('acceptance_memory_policy_invalid')

    def docker_args(self) -> list[str]:
        return ['--memory', str(self.memory), '--memory-swap', str(self.memory_swap)]

    def applied(self, config: Any) -> bool:
        return (isinstance(config, dict) and config.get('Memory') == self.memory
                and config.get('MemorySwap') == self.memory_swap)


@dataclass(frozen=True)
class AcceptanceMemoryPolicy:
    heavy: MemoryLimit
    pg_db: MemoryLimit
    pg_tests: MemoryLimit


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AcceptanceMemoryError('acceptance_memory_policy_invalid')
        result[key] = value
    return result


def _limit(value: Any) -> MemoryLimit:
    if not isinstance(value, dict) or set(value) != {'memory', 'memory_swap'}:
        raise AcceptanceMemoryError('acceptance_memory_policy_invalid')
    return MemoryLimit(value['memory'], value['memory_swap'])


def _host_swap_total() -> int:
    text = Path('/proc/meminfo').read_text(encoding='ascii')
    rows = re.findall(r'^SwapTotal:\s+(\d+)\s+kB$', text, flags=re.MULTILINE)
    if len(rows) != 1:
        raise AcceptanceMemoryError('acceptance_memory_policy_invalid')
    return int(rows[0]) * 1024


def load_policy(channel: str, *, root: Path = CONFIG_ROOT, expected_uid: int = 0,
                total_memory: int | None = None, total_swap: int | None = None) -> AcceptanceMemoryPolicy | None:
    """Read one private optional policy; absence is visible and preserves old behavior."""
    if channel not in {'dev', 'test'}:
        raise AcceptanceMemoryError('acceptance_memory_channel_invalid')
    path = root / (channel + '.acceptance-memory.json')
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        print(f'acceptance_memory_policy_unconfigured channel={channel} isolation=inactive', file=sys.stderr, flush=True)
        return None
    except OSError:
        raise AcceptanceMemoryError('acceptance_memory_policy_invalid') from None
    try:
        with os.fdopen(descriptor, 'r', encoding='utf-8') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != expected_uid
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or info.st_size > 16384):
                raise AcceptanceMemoryError('acceptance_memory_policy_invalid')
            data = json.load(stream, object_pairs_hook=_unique_object)
        if (not isinstance(data, dict) or set(data) != {'version', 'heavy', 'pg_db', 'pg_tests'}
            or type(data['version']) is not int or data['version'] != 1):
            raise AcceptanceMemoryError('acceptance_memory_policy_invalid')
        policy = AcceptanceMemoryPolicy(_limit(data['heavy']), _limit(data['pg_db']), _limit(data['pg_tests']))
        physical = total_memory if total_memory is not None else os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
        swap = total_swap if total_swap is not None else _host_swap_total()
        swap_budget = sum(limit.memory_swap - limit.memory for limit in (policy.heavy, policy.pg_db, policy.pg_tests))
        # Heavy does not hold the channel lock and can overlap a later PG run.
        if (type(physical) is not int or physical <= 0 or type(swap) is not int or swap < 0
            or swap_budget > swap
            or policy.heavy.memory + policy.pg_db.memory + policy.pg_tests.memory > physical):
            raise AcceptanceMemoryError('acceptance_memory_policy_invalid')
        return policy
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError, RecursionError):
        raise AcceptanceMemoryError('acceptance_memory_policy_invalid') from None
