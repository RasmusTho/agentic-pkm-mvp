"""Run a bounded, value-free validation-environment readiness diagnostic.

This is an opt-in diagnostic for deciding whether a costly validation command
has enough local evidence to start. It never installs packages, opens a
Postgres connection, invokes a provider, or changes a host-global resource.
The output is classification evidence, not a test-pass receipt.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Mapping, Sequence


_TARGET_MODULES: dict[str, tuple[str, ...]] = {
    "test": ("pytest",),
    "lint": ("ruff", "mypy"),
}

_PRIMARY_DB_KEYS = ("DATABASE_URL", "DB_DSN")
_RUNTIME_DB_KEYS = (
    "PKM_DB_HOST",
    "PKM_DB_PORT",
    "PKM_DB_NAME_DEV",
    "PKM_DB_NAME_TEST",
    "PKM_DB_NAME_PROD",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "BUILDEROPS_DATABASE_URL",
)
_AMBIENT_DB_KEYS = (
    "PGHOST",
    "PGHOSTADDR",
    "PGPORT",
    "PGDATABASE",
    "PGUSER",
)
_SERVICE_DB_KEYS = ("PGSERVICE", "PGSERVICEFILE")


def _nonempty(environment: Mapping[str, str], key: str) -> bool:
    return bool(environment.get(key, "").strip())


def _repo_root(value: str | None) -> Path:
    if value is not None:
        return Path(value).resolve()
    return Path(__file__).resolve().parents[1]


def _resolve_interpreter(root: Path, environment: Mapping[str, str]) -> tuple[str, Path | None]:
    resolver = root / "scripts" / "lib" / "resolve_repo_python.sh"
    if not resolver.is_file():
        return "unavailable", None
    command = [
        "bash",
        "-c",
        'source "$1"; builderops_resolve_python "$2"',
        "validation-readiness",
        str(resolver),
        str(root),
    ]
    try:
        result = subprocess.run(
            command,
            cwd=root,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable", None
    if result.returncode != 0:
        return "unavailable", None
    raw_path = result.stdout.strip()
    if not raw_path:
        return "unavailable", None
    path = Path(raw_path)
    if not path.is_absolute():
        path = root / path
    if not path.is_file() or not os.access(path, os.X_OK):
        return "unavailable", None
    return "executable", path


def _probe_imports(
    interpreter: Path | None,
    modules: Sequence[str],
    *,
    root: Path,
    environment: Mapping[str, str],
) -> str:
    if interpreter is None:
        return "not_checked"
    source = (
        "import importlib\n"
        f"modules = {tuple(modules)!r}\n"
        "for module in modules:\n"
        "    importlib.import_module(module)\n"
    )
    try:
        result = subprocess.run(
            [str(interpreter), "-c", source],
            cwd=root,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "import_incompatible"
    return "compatible" if result.returncode == 0 else "import_incompatible"


def _helper_status(
    interpreter: Path | None,
    helper: Path,
    *,
    root: Path,
    environment: Mapping[str, str],
) -> str:
    if interpreter is None:
        return "not_checked"
    if not helper.exists() or not helper.is_file():
        return "missing"
    try:
        mode = helper.stat().st_mode
    except OSError:
        return "unknown"
    if not mode & (stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH):
        return "restricted"
    try:
        result = subprocess.run(
            [str(interpreter), str(helper), "--help"],
            cwd=root,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
    except PermissionError:
        return "restricted"
    except subprocess.TimeoutExpired:
        return "unknown"
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unknown"
    # A non-zero helper invocation has no stable meaning at this boundary:
    # preserve it as unknown rather than guessing about credentials or ACLs.
    return "visible" if result.returncode == 0 else "unknown"


def _pg_status(environment: Mapping[str, str], *, root: Path) -> str:
    configured = any(
        _nonempty(environment, key)
        for key in (*_PRIMARY_DB_KEYS, *_RUNTIME_DB_KEYS, *_AMBIENT_DB_KEYS, *_SERVICE_DB_KEYS)
    )
    if not configured:
        return "absent"
    if any(_nonempty(environment, key) for key in _SERVICE_DB_KEYS):
        return "forbidden"
    if any(_nonempty(environment, key) for key in (*_RUNTIME_DB_KEYS, *_AMBIENT_DB_KEYS)):
        # A safe primary DSN cannot authorize a lane while another libpq or
        # runtime writer is present; leave the effective target unresolved.
        return "ambiguous"

    primary = next(
        (environment.get(key, "").strip() for key in _PRIMARY_DB_KEYS if _nonempty(environment, key)),
        "",
    )
    if primary:
        try:
            # Reuse the production classifier; this diagnostic does not maintain
            # a second DSN policy or attempt a connection.
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            from app.db.dsn import looks_like_prod_dsn

            if looks_like_prod_dsn(primary):
                return "forbidden"
        except Exception:
            return "ambiguous"
        lowered = primary.casefold()
        if "service=" in lowered or "servicefile=" in lowered:
            return "forbidden"
        return "disposable_candidate"

    # Runtime, ambient, and control-plane writers cannot authorize the ordinary
    # PG lane from this read-only probe; leave them explicitly unresolved.
    return "ambiguous"


def diagnose(
    *,
    root: Path,
    target: str,
    helper: Path,
    environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    env = dict(os.environ if environment is None else environment)
    interpreter_state, interpreter = _resolve_interpreter(root, env)
    modules = _TARGET_MODULES[target]
    toolchain_status = (
        _probe_imports(interpreter, modules, root=root, environment=env)
        if interpreter_state == "executable"
        else interpreter_state
    )
    helper_state = _helper_status(interpreter, helper, root=root, environment=env)
    return {
        "helper": {"status": helper_state},
        "pg": {"status": _pg_status(env, root=root)},
        "target": target,
        "toolchain": {
            "required_modules": list(modules),
            "status": toolchain_status,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=sorted(_TARGET_MODULES), required=True)
    parser.add_argument("--helper", type=Path, default=Path("scripts/run_with_host_lease.py"))
    parser.add_argument("--repo-root", type=str)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = _repo_root(args.repo_root)
    helper = args.helper if args.helper.is_absolute() else root / args.helper
    result = diagnose(root=root, target=args.target, helper=helper)
    print(json.dumps(result, sort_keys=True))
    # The command reports classifications even when readiness is blocked. A
    # zero exit means the diagnostic itself ran; inspect statuses before any
    # required lane is treated as evidence.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
