"""Read-only dev/test deploy preflight: detect a Compose `environment:`
override that resolves blank while the same service's `env_file` chain would
otherwise supply a non-empty value for that key (Issue #4230).

Compose's `environment:` block always wins over `env_file:` for the same key.
`scripts/lib/deploy_channel_compose.sh` deliberately never passes the
governed runtime env file as a Compose CLI `--env-file` (that would expose
DSNs to Compose interpolation, #3875), so an overlay entry shaped like
`${VAR:-}` interpolates to an empty string against the invoking shell and
silently shadows whatever value the same key would otherwise receive from the
service's env_file chain. This is the exact shape that crash-looped
`heimdal-capture-watch` on every dev-channel deploy until commit `f95a6811`
deleted the offending `environment:` entries -- that instance is already
fixed, but the deploy path ran zero check for the general class on the dev
and test channels (prod already carries an analogous, DSN-scoped gate via
`scripts/prod_deploy_retry_preflight.py`).

This script asks `app.release_channels.channel_isolation_preflight` (the one
purpose-built, tested Compose `environment:`-vs-`env_file:` resolver) whether
the channel's real compose overlay currently has this shape, for every
service in `CHANNEL_SERVICES` (`api`, `worker`, `watcher`,
`heimdal-capture-watch`). Read-only: no Docker, no network, never mutates
compose, pin, or env_file files.

Interpolation sources mirror the real deploy invocation exactly (#4613,
PR #4599 review r3700034269): `scripts/lib/deploy_channel_compose.sh` runs
`docker compose --env-file "config/deploy/<channel>.env"`, so the channel
deploy env file is a genuine interpolation source layered UNDER the invoking
shell (shell wins), and passing `--env-file` replaces the default repo-root
`.env` entirely. Resolving against `os.environ` plus the repo `.env` instead
(the reviewed behavior) let a variable defined only in the repo `.env`
resolve nonblank here while the real invocation resolved it blank -- masking
the exact clobber this gate exists to stop. Mirrors
`scripts/prod_deploy_retry_preflight.py::_interpolation_environ`.

Exit codes:
  0  no blank-override clobber found (including "channel has no overlay" --
     an unsupported/unknown channel argument is a caller error, not this
     preflight's job to adjudicate).
  1  at least one blank-override clobber found; the caller
     (`scripts/deploy_channel.sh`) must not proceed to pin write or
     migration/Compose mutation.

Usage: ``python scripts/dev_test_environment_clobber_preflight.py <dev|test>``.
Prints one JSON receipt object to stdout.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_CHANNEL_OVERLAYS = {
    "dev": "docker-compose.dev.yml",
    "test": "docker-compose.test.yml",
}


def _repo_root() -> Path:
    # This script is invoked by path (sys.path[0] is scripts/, not the repo
    # root), so the repo root is added to sys.path explicitly before any
    # `app.*` import.
    root = Path(__file__).resolve().parents[1]
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return root


def _deploy_env_file_interpolation_environ(
    root: Path, channel: str
) -> dict[str, str]:
    """The interpolation sources the real Compose invocation resolves against.

    ``scripts/lib/deploy_channel_compose.sh`` invokes ``docker compose
    --env-file "config/deploy/<channel>.env"``: the channel deploy env file
    is a genuine Compose interpolation source, layered UNDER the invoking
    shell (Compose gives the shell precedence over ``--env-file`` values), so
    its values are merged first and ``os.environ`` is applied last, on top —
    the same layering ``scripts/prod_deploy_retry_preflight.py::
    _interpolation_environ`` models for the prod channel. A missing or empty
    deploy env file contributes nothing rather than failing: a channel's
    first deploy runs this preflight before ``write_pin`` ever creates the
    file. Bare ``KEY`` lines (no ``=``) contribute nothing either — the host
    value they would pass through is already present via ``os.environ``.
    """
    # Imported lazily like main()'s checker import: sys.path gains the repo
    # root only once _repo_root() has run.
    from app.release_channels.channel_isolation_preflight import (
        _parse_env_file_text,
    )

    merged: dict[str, str] = {}
    env_file = root / "config" / "deploy" / f"{channel}.env"
    try:
        text = env_file.read_text(encoding="utf-8")
    except OSError:
        text = ""
    if text:
        parsed = _parse_env_file_text(text)
        merged.update(
            {key: value for key, value in parsed.items() if value is not None}
        )
    merged.update(os.environ)
    return merged


def main(argv: list[str], root: Path | None = None) -> int:
    if len(argv) != 1 or argv[0] not in _CHANNEL_OVERLAYS:
        print(
            f"usage: {Path(__file__).name} <{'|'.join(_CHANNEL_OVERLAYS)}>",
            file=sys.stderr,
        )
        return 2

    channel = argv[0]
    repo_root = _repo_root()
    if root is None:
        root = repo_root

    compose_path = root / _CHANNEL_OVERLAYS[channel]
    if not compose_path.is_file():
        # Fail open, not closed: an absent compose overlay is a setup/
        # environment concern this preflight does not adjudicate (mirrors
        # scripts/prod_deploy_retry_preflight.py's skipped:no_dsn posture for
        # "resolution is impossible at all", not "a violation was found").
        payload = {
            "status": "skipped",
            "channel": channel,
            "reason": "compose_overlay_missing",
        }
        print(json.dumps(payload, sort_keys=True))
        return 0

    from app.release_channels.channel_isolation_preflight import (
        check_environment_env_file_clobber,
    )

    # Resolve interpolation exactly as the real deploy invocation does: the
    # selected `--env-file config/deploy/<channel>.env` under the invoking
    # shell, and no repo-root `.env` contribution at all (a `--env-file`
    # replaces it) — see the module docstring (#4613).
    result = check_environment_env_file_clobber(
        compose_path,
        channel,
        environ=_deploy_env_file_interpolation_environ(root, channel),
        load_dotenv=False,
    )

    if result.ok:
        payload = {"status": "ok", "channel": channel, "violation_count": 0}
        print(json.dumps(payload, sort_keys=True))
        return 0

    payload = {
        "status": "blocked",
        "channel": channel,
        "violation_count": len(result.violations),
        "violations": [
            {
                "service": violation.service,
                "field": violation.field,
                "expected": violation.expected,
                "actual": violation.actual,
            }
            for violation in result.violations
        ],
    }
    print(json.dumps(payload, sort_keys=True))
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
