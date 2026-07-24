#!/usr/bin/env python3
"""Preflight, start, and run a BuilderOps model inquiry from a desktop skill."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.builderops.model_inquiry import ModelInquiryService
from app.builderops.model_inquiry_adapters import (
    ADAPTER_FAILURE_CLASSES,
    AdapterUnavailableError,
    LocalCommandAdapter,
    load_adapters,
    sanitized_adapter_identity,
)
from app.builderops.models import BuilderOpsValidationError
from scripts.install_model_inquiry_host import (
    HostInstallError,
    check as check_host_entrypoints,
)

WORKFLOW = "fable-gpt-architecture"
SOURCE_REF = "desktop_skill:start-model-inquiry"


class LauncherError(RuntimeError):
    """A safe operator-facing launcher failure."""


def preflight_dependencies(
    env: Mapping[str, str],
    *,
    command_cwd: Path,
) -> dict[str, Any]:
    """Validate the durable store and explicit adapters without mutation."""
    ModelInquiryService.from_env(env)
    adapters = load_adapters(env)
    subscription_entrypoints = {
        "fable": "fable-subscription-cli",
        "gpt_codex": "codex-subscription-cli",
    }
    if all(
        isinstance(adapters.get(role), LocalCommandAdapter)
        and adapters[role].adapter_id == entrypoint
        and adapters[role].argv == (entrypoint,)
        for role, entrypoint in subscription_entrypoints.items()
    ):
        path = env.get("PATH", os.defpath)
        discovered = {
            role: shutil.which(entrypoint, path=path)
            for role, entrypoint in subscription_entrypoints.items()
        }
        if not all(discovered.values()):
            missing_role = next(role for role, value in discovered.items() if value is None)
            adapter = adapters[missing_role]
            raise AdapterUnavailableError(
                f"{missing_role}: local command unavailable: {adapter.adapter_id}"
            )
        bin_dirs = {
            str(Path(value).absolute().parent)
            for value in discovered.values()
            if value is not None
        }
        if len(bin_dirs) != 1:
            raise AdapterUnavailableError(
                "subscription role entrypoints do not share one validated host bin directory"
            )
        try:
            host_status = check_host_entrypoints(
                repo_root=command_cwd,
                bin_dir=Path(bin_dirs.pop()),
                python=Path(sys.executable),
                path=path,
            )
        except HostInstallError as exc:
            raise AdapterUnavailableError(
                "subscription role entrypoints failed installed-lineage preflight"
            ) from exc
        if not host_status["ok"]:
            raise AdapterUnavailableError(
                "subscription role entrypoints failed installed-lineage preflight"
            )
    for role, adapter in adapters.items():
        if not isinstance(adapter, LocalCommandAdapter):
            continue
        executable = adapter.argv[0] if adapter.argv else ""
        path = (adapter.environment or {}).get("PATH", env.get("PATH", os.defpath))
        if not _command_available(executable, path=path, cwd=command_cwd):
            raise AdapterUnavailableError(
                f"{role}: local command unavailable: {adapter.adapter_id}"
            )
    return {
        "vault": "available",
        "adapters": {
            role: sanitized_adapter_identity(adapter)
            for role, adapter in sorted(adapters.items())
        },
    }


def _command_available(executable: str, *, path: str, cwd: Path) -> bool:
    if not executable:
        return False
    if os.sep in executable:
        candidate = Path(executable)
        if not candidate.is_absolute():
            candidate = cwd / candidate
        return candidate.is_file() and os.access(candidate, os.X_OK)
    return shutil.which(executable, path=path) is not None


def launch(
    question: str,
    *,
    max_rounds: int,
    env: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    question = question.strip()
    if not question:
        raise LauncherError("question must not be empty")
    source_env = dict(os.environ if env is None else env)
    root = (repo_root or Path(__file__).resolve().parents[1]).resolve()
    cli = root / "scripts" / "builderops_cli.sh"
    if not cli.is_file() or not os.access(cli, os.X_OK):
        raise LauncherError(
            "BuilderOps launcher is unavailable; run from an accessible agentic-pkm-mvp checkout"
        )

    preflight = preflight_dependencies(source_env, command_cwd=root)
    with tempfile.TemporaryDirectory(prefix="builderops-inquiry-") as temp_dir:
        question_file = Path(temp_dir) / "question.md"
        question_file.write_text(question + "\n", encoding="utf-8")
        question_file.chmod(0o600)
        started = _run_cli(
            cli,
            [
                "builderops",
                "inquiry",
                "start",
                "--question-file",
                str(question_file),
                "--workflow",
                WORKFLOW,
                "--source-ref",
                SOURCE_REF,
                "--created-by",
                "desktop-skill",
                "--json",
            ],
            env=source_env,
        )

    try:
        inquiry_id = str(started["inquiry"]["inquiry_id"])
    except (KeyError, TypeError) as exc:
        raise LauncherError("BuilderOps start response omitted inquiry_id") from exc
    completed = _run_cli(
        cli,
        [
            "builderops",
            "inquiry",
            "run",
            inquiry_id,
            "--max-rounds",
            str(max_rounds),
            "--json",
        ],
        env=source_env,
    )
    outcome = completed.get("outcome")
    if not isinstance(outcome, str) or not outcome:
        raise LauncherError("BuilderOps run response omitted final outcome")
    result = {
        "schema": "builderops.model-inquiry-desktop-launch.v1",
        "inquiry_id": inquiry_id,
        "final_state": outcome,
        "terminal_receipt_id": completed.get("terminal_receipt_id"),
        "human_readable_report": completed.get("human_readable_report"),
        "preflight": preflight,
    }
    diagnostic = _desktop_diagnostic(completed.get("details"))
    if diagnostic is not None:
        result["diagnostic"] = diagnostic
    return result


def _run_cli(
    cli: Path,
    arguments: Sequence[str],
    *,
    env: Mapping[str, str],
) -> dict[str, Any]:
    result = subprocess.run(
        [str(cli), *arguments],
        cwd=cli.parents[1],
        env=dict(env),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (
            result.stderr.strip().splitlines()[-1]
            if result.stderr.strip()
            else "unknown error"
        )
        raise LauncherError(f"BuilderOps command failed: {detail}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise LauncherError("BuilderOps command returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise LauncherError("BuilderOps command returned a non-object response")
    return payload


def _desktop_diagnostic(value: Any) -> dict[str, str | int] | None:
    """Expose only the adapter diagnostic contract, never generic receipt details."""
    if not isinstance(value, Mapping):
        return None
    candidate = value.get("diagnostic")
    if not isinstance(candidate, Mapping):
        return None
    adapter_id = candidate.get("adapter_id")
    failure_class = candidate.get("adapter_failure_class")
    if (
        not isinstance(adapter_id, str)
        or not adapter_id
        or not isinstance(failure_class, str)
        or failure_class not in ADAPTER_FAILURE_CLASSES
    ):
        return None
    result: dict[str, str | int] = {
        "adapter_id": adapter_id,
        "adapter_failure_class": failure_class,
    }
    exit_code = candidate.get("adapter_exit_code")
    if isinstance(exit_code, int) and not isinstance(exit_code, bool) and 1 <= exit_code <= 255:
        result["adapter_exit_code"] = exit_code
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("question", nargs="?", help="Question text (prefer --question-file)")
    source.add_argument(
        "--question-file",
        type=Path,
        help="UTF-8 file containing the question; avoids exposing it in process arguments",
    )
    parser.add_argument("--max-rounds", type=int, default=3, choices=range(1, 21))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        question = (
            args.question_file.read_text(encoding="utf-8")
            if args.question_file is not None
            else args.question
        )
        result = launch(question, max_rounds=args.max_rounds)
    except (AdapterUnavailableError, BuilderOpsValidationError, LauncherError, OSError) as exc:
        print(f"ERROR: model inquiry preflight/launch failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
