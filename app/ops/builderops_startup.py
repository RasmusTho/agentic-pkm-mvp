"""BuilderOps startup bootstrap for the dev runtime stack.

This module is intentionally operational glue. GitHub Issues/PRs/CI remain the
durable truth; dispatcher and BuilderOps state are local coordination surfaces.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_REPO = "RasmusTho/agentic-pkm-mvp"
DEFAULT_RATE_LIMIT_MIN = 25


def _run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _json_or_empty(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _snippet(text: str, limit: int = 500) -> str:
    compact = " ".join((text or "").split())
    return compact[:limit]


def _append_reason(result: dict[str, Any], reason: str) -> None:
    reasons = result.setdefault("reasons", [])
    if reason not in reasons:
        reasons.append(reason)


def _dispatcher_bootstrap(
    *,
    python_bin: str,
    root: Path,
    repo: str,
    env: dict[str, str],
    gh_bin: str,
    rate_limit_min: int,
    skip_github_sync: bool,
    result: dict[str, Any],
) -> dict[str, Any]:
    dispatcher: dict[str, Any] = {
        "status": "ok",
        "initialized": False,
        "db_exists": None,
        "db_path": None,
        "github_sync": {"status": "not_run"},
    }

    status = _run([python_bin, "-m", "app.dispatcher", "status", "--json"], cwd=root, env=env)
    status_payload = _json_or_empty(status.stdout)
    if status.returncode != 0:
        dispatcher["status"] = "degraded"
        dispatcher["reason"] = "dispatcher_status_failed"
        dispatcher["stderr"] = _snippet(status.stderr)
        _append_reason(result, "dispatcher_status_failed")
        return dispatcher

    dispatcher["db_exists"] = bool(status_payload.get("db_exists"))
    dispatcher["db_path"] = status_payload.get("db_path")

    if not dispatcher["db_exists"]:
        init = _run([python_bin, "-m", "app.dispatcher", "init", "--json"], cwd=root, env=env)
        if init.returncode != 0:
            dispatcher["status"] = "degraded"
            dispatcher["reason"] = "dispatcher_init_failed"
            dispatcher["stderr"] = _snippet(init.stderr or init.stdout)
            _append_reason(result, "dispatcher_init_failed")
            return dispatcher
        dispatcher["initialized"] = True
        status = _run([python_bin, "-m", "app.dispatcher", "status", "--json"], cwd=root, env=env)
        status_payload = _json_or_empty(status.stdout)
        dispatcher["db_exists"] = bool(status_payload.get("db_exists"))
        dispatcher["db_path"] = status_payload.get("db_path")

    if not dispatcher["db_exists"]:
        dispatcher["status"] = "degraded"
        dispatcher["reason"] = "dispatcher_db_missing_after_init"
        _append_reason(result, "dispatcher_db_missing_after_init")
        return dispatcher

    dispatcher["github_sync"] = _github_sync(
        python_bin=python_bin,
        root=root,
        repo=repo,
        env=env,
        gh_bin=gh_bin,
        rate_limit_min=rate_limit_min,
        skip=skip_github_sync,
        result=result,
    )
    return dispatcher


def _resolve_gh(gh_bin: str) -> str | None:
    if os.sep in gh_bin:
        candidate = Path(gh_bin)
        return str(candidate) if candidate.exists() and os.access(candidate, os.X_OK) else None
    return shutil.which(gh_bin)


def _github_sync(
    *,
    python_bin: str,
    root: Path,
    repo: str,
    env: dict[str, str],
    gh_bin: str,
    rate_limit_min: int,
    skip: bool,
    result: dict[str, Any],
) -> dict[str, Any]:
    if skip:
        return {"status": "skipped", "reason": "disabled"}

    resolved = _resolve_gh(gh_bin)
    if resolved is None:
        _append_reason(result, "gh_not_found")
        return {"status": "skipped", "reason": "gh_not_found"}

    auth = _run([resolved, "auth", "status"], cwd=root, env=env)
    if auth.returncode != 0:
        _append_reason(result, "gh_not_authenticated")
        return {
            "status": "skipped",
            "reason": "gh_not_authenticated",
            "detail": _snippet(auth.stderr or auth.stdout),
        }

    rate = _run(
        [resolved, "api", "rate_limit", "--jq", ".resources.core.remaining"],
        cwd=root,
        env=env,
    )
    if rate.returncode != 0:
        _append_reason(result, "github_rate_limit_unavailable")
        return {
            "status": "skipped",
            "reason": "github_rate_limit_unavailable",
            "detail": _snippet(rate.stderr or rate.stdout),
        }
    try:
        remaining = int((rate.stdout or "").strip())
    except ValueError:
        _append_reason(result, "github_rate_limit_unparseable")
        return {
            "status": "skipped",
            "reason": "github_rate_limit_unparseable",
            "detail": _snippet(rate.stdout),
        }
    if remaining < rate_limit_min:
        _append_reason(result, "github_rate_limit_low")
        return {
            "status": "skipped",
            "reason": "github_rate_limit_low",
            "remaining": remaining,
            "required_minimum": rate_limit_min,
        }

    pull = _run(
        [python_bin, "-m", "app.dispatcher", "pull", "--repo", repo, "--json"],
        cwd=root,
        env=env,
    )
    payload = _json_or_empty(pull.stdout)
    if pull.returncode != 0 or payload.get("ok") is not True:
        _append_reason(result, "dispatcher_pull_failed")
        return {
            "status": "degraded",
            "reason": "dispatcher_pull_failed",
            "remaining": remaining,
            "detail": payload.get("error") or _snippet(pull.stderr or pull.stdout),
        }
    return {
        "status": "ok",
        "remaining": remaining,
        "upserted": payload.get("upserted", 0),
        "reconciled": payload.get("reconciled", 0),
    }


def _builderops_readiness(*, root: Path, env: dict[str, str], result: dict[str, Any]) -> dict[str, Any]:
    wrapper = root / "scripts" / "builderops_cli.sh"
    builderops: dict[str, Any] = {
        "status": "ok",
        "wrapper": str(wrapper.relative_to(root)),
        "db_path": _builderops_db_path(root, env),
    }
    if not wrapper.exists():
        builderops["status"] = "degraded"
        builderops["reason"] = "builderops_wrapper_missing"
        _append_reason(result, "builderops_wrapper_missing")
        return builderops

    probe = _run([str(wrapper), "builderops", "list", "--json"], cwd=root, env=env)
    if probe.returncode != 0:
        builderops["status"] = "degraded"
        builderops["reason"] = "builderops_readiness_failed"
        builderops["detail"] = _snippet(probe.stderr or probe.stdout)
        _append_reason(result, "builderops_readiness_failed")
        return builderops
    try:
        records = json.loads(probe.stdout or "[]")
    except json.JSONDecodeError:
        records = []
    builderops["record_count"] = len(records) if isinstance(records, list) else None
    return builderops


def _builderops_db_path(root: Path, env: dict[str, str]) -> str:
    if env.get("BUILDEROPS_DB_PATH"):
        return env["BUILDEROPS_DB_PATH"]
    state_dir = Path(env.get("BUILDEROPS_STATE_DIR", "runtime/builderops")).expanduser()
    if not state_dir.is_absolute():
        state_dir = root / state_dir
    return str(state_dir / "builderops.sqlite3")


def _project_reconciliation() -> dict[str, Any]:
    return {
        "status": "available",
        "command": "scripts/reconcile_builderops_project_status.sh --scan",
        "frequency": "manual_or_low_frequency_batch",
        "dispatcher_hot_path": False,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def _merge_startup_status(path: Path, result: dict[str, Any]) -> None:
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                existing = parsed
        except json.JSONDecodeError:
            existing = {}
    existing["builderops_bootstrap"] = result
    _write_json(path, existing)


def run_bootstrap(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).resolve()
    env = dict(os.environ)
    result: dict[str, Any] = {
        "ok": True,
        "status": "ok",
        "degraded": False,
        "reasons": [],
        "repo": args.repo,
    }

    result["dispatcher"] = _dispatcher_bootstrap(
        python_bin=sys.executable,
        root=root,
        repo=args.repo,
        env=env,
        gh_bin=args.gh_bin,
        rate_limit_min=args.rate_limit_min,
        skip_github_sync=args.skip_github_sync,
        result=result,
    )
    result["builderops"] = _builderops_readiness(root=root, env=env, result=result)
    result["project_reconciliation"] = _project_reconciliation()

    reasons = result.get("reasons", [])
    if reasons:
        result["status"] = "degraded"
        result["degraded"] = True

    if args.status_output:
        _write_json(Path(args.status_output), result)
    if args.startup_status_path:
        _merge_startup_status(Path(args.startup_status_path), result)

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap BuilderOps coordination for dev startup.")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--root", default=str(Path.cwd()))
    parser.add_argument("--startup-status-path", default="tmp/startup_status.json")
    parser.add_argument("--status-output", default="tmp/builderops_startup_status.json")
    parser.add_argument("--gh-bin", default=os.environ.get("BUILDEROPS_GH_BIN", "gh"))
    parser.add_argument("--rate-limit-min", type=int, default=DEFAULT_RATE_LIMIT_MIN)
    parser.add_argument(
        "--skip-github-sync",
        action="store_true",
        default=os.environ.get("BUILDEROPS_BOOTSTRAP_SKIP_GITHUB_SYNC", "0") == "1",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_bootstrap(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    elif result["status"] == "ok":
        print("BuilderOps bootstrap: ok")
    else:
        reasons = ", ".join(result.get("reasons", [])) or "unknown"
        print(f"BuilderOps bootstrap: degraded ({reasons})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
