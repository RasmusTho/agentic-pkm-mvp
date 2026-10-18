#!/usr/bin/env python3
"""Plan the fixed BOB-1 native keyring installation; explicit apply is separately gated."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ALIAS = "bob-1-builder-system"
MODULE = "app/ops/builder_executor_keyring.py"
TEMPLATE = "config/systemd/yggdrasil-builder-executor-keyring.service"
_RUN = subprocess.run


class InstallerRefusal(ValueError):
    """Only fixed value-free diagnostic codes are emitted."""


def git(*args: str) -> str:
    return _RUN(["git", *args], cwd=ROOT, capture_output=True, text=True,
                check=True, timeout=30).stdout.strip()


def payload() -> dict[str, str]:
    head = git("rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", head) or git("status", "--porcelain"):
        raise InstallerRefusal("clean_committed_source_required")
    def blob(path: str) -> str:
        return _RUN(["git", "show", f"{head}:{path}"], cwd=ROOT, capture_output=True,
                    text=True, check=True, timeout=30).stdout
    return {"source_sha": head, "module": blob(MODULE), "unit": blob(TEMPLATE)}


def merged_source(head: str) -> None:
    allowed = {"https://github.com/RasmusTho/agentic-pkm-mvp.git",
               "git@github.com:RasmusTho/agentic-pkm-mvp.git"}
    if git("remote", "get-url", "--all", "origin") not in allowed or git(
            "remote", "get-url", "--push", "--all", "origin") not in allowed:
        raise InstallerRefusal("source_repository_identity_refused")
    remote = git("ls-remote", "--exit-code", "origin", "refs/heads/main").split()
    if len(remote) != 2 or remote != [head, "refs/heads/main"] or git("rev-parse", "origin/main") != head:
        raise InstallerRefusal("exact_live_merged_main_required")


def dispatch(request: dict[str, Any]) -> dict[str, Any]:
    # Even plan/status execute this source under sudo. Authenticate every
    # privileged dispatch before constructing or sending the remote program.
    merged_source(request["payload"]["source_sha"])
    source = request["payload"]["module"]
    program = "import json\nnamespace={'__name__':'executor_keyring_remote'}\n"
    program += f"exec(compile({source!r},'<reviewed-executor-keyring>','exec'),namespace)\n"
    program += f"print(json.dumps(namespace['remote']({request!r}),sort_keys=True))\n"
    try:
        result = _RUN(["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                       "-o", "ConnectTimeout=10", ALIAS, "sudo -n /usr/bin/python3 -I -"],
                      input=program, capture_output=True, text=True, timeout=90, check=False)
    except subprocess.TimeoutExpired as exc:
        raise InstallerRefusal("remote_outcome_unproven_use_status_before_retry") from exc
    if result.returncode:
        raise InstallerRefusal("remote_outcome_unproven_use_status_before_retry")
    response = json.loads(result.stdout)
    if not isinstance(response, dict):
        raise InstallerRefusal("remote_result_invalid")
    return response


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", default="plan", choices=("plan", "apply", "status"))
    parser.add_argument("--operation", default="apply", choices=("apply", "start", "disable"))
    parser.add_argument("--plan-file", type=Path)
    parser.add_argument("--expected-plan-sha256")
    args = parser.parse_args(argv)
    try:
        package = payload()
        request: dict[str, Any] = {"action": args.action, "payload": package, "operation": args.operation}
        if args.action == "apply":
            if args.plan_file is None or args.expected_plan_sha256 is None:
                raise InstallerRefusal("explicit_reviewed_plan_required")
            approved = json.loads(args.plan_file.read_text())
            if approved.get("plan_sha256") != args.expected_plan_sha256:
                raise InstallerRefusal("operator_plan_mismatch")
            if approved.get("action") != args.operation:
                raise InstallerRefusal("operator_action_mismatch")
            request["plan"] = approved
        response = dispatch(request)
        print(json.dumps(response, indent=2, sort_keys=True))
        return 78 if response.get("result") == "refused" else 0
    except InstallerRefusal as exc:
        print(json.dumps({"result": "refused", "reason": str(exc)}))
        return 78
    except (OSError, ValueError, subprocess.SubprocessError):
        print(json.dumps({"result": "refused", "reason": "installation_input_or_transport_unavailable"}))
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
