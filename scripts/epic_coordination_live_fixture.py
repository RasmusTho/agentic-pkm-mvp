#!/usr/bin/env python3
"""Owned, single-worker fixture for independently qualifying #6619 on the trusted controller.

This does not launch or stop a worker. Set up a separate fixture epic with the existing epicws
commands, start its OpenHands conversation with the printed prompt, then apply and observe below.
It uses the controller's existing session capability, does not print credentials or contact GitHub,
and its evidence is not a production acceptance receipt. Its Issue/PR authority is an explicitly
simulated port; it is read before every session contact and before any success result.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.builderops import epic_coordination as coord  # noqa: E402
from app.builderops import epic_coordination_effects as effects  # noqa: E402
from app.builderops import epic_workspace as ew  # noqa: E402

RESULT = "coordination-live-fixture-result.md"


def _token(value: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{24,64}", value):
        raise argparse.ArgumentTypeError("token must be 24-64 lowercase hexadecimal characters")
    return value


def _bound(root: Path, epic: int, issue: int, worker: str) -> tuple[ew.Layout, Path]:
    root = root.resolve(strict=True)
    if root.stat().st_uid != os.geteuid() or epic < 9_000_000 or issue < 9_000_000 or not worker.startswith("fixture-"):
        raise ValueError("require an owned fixture root, synthetic epic/issue numbers >= 9000000, and fixture- worker")
    layout = ew.Layout(root, epic)
    state = ew._load_state(layout)
    mappings = state.get("issue_mappings", {})
    if set(mappings) != {str(issue)}:
        raise ValueError("fixture epic must contain exactly the designated worker")
    mapping = mappings[str(issue)]
    checkout = layout.checkout(worker)
    if (mapping.get("worker") != worker or mapping.get("runtime") != "openhands" or mapping.get("state") != "running"
            or ew._checkout_mount_identity(layout, worker, mapping) is None):
        raise ValueError("fixture worker and assigned checkout are not bound and running")
    return layout, checkout


def _fixture_fetch(issue: int):
    """EXPLICITLY SIMULATED authority port for synthetic Issue numbers: never a real Issue readback."""
    def fetch(path: str, timeout: float) -> tuple[int, bytes]:
        if "/pulls?" in path:
            return 200, b"[]"
        if path.endswith(f"/issues/{issue}"):
            return 200, json.dumps({"number": issue, "state": "open", "labels": []}).encode()
        raise ValueError("unexpected fixture authority request")
    return fetch


def _require_authority(layout: ew.Layout, issue: int, fetch: Any) -> None:
    """Read the fixture's current (simulated) authority; called before every session contact and success."""
    mapping = ew._load_state(layout)["issue_mappings"][str(issue)]
    if not effects._fresh_authority(layout, issue, mapping, fetch):
        raise ValueError("fixture source authority is stopped or unavailable; no session access and no success")


def _run(argv: list[str] | None = None, *, runner: ew.Runner = subprocess.run, http=ew._http) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prompt", "baseline", "apply", "verify"))
    parser.add_argument("--token", required=True, type=_token)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--epic", type=int)
    parser.add_argument("--issue", type=int)
    parser.add_argument("--worker")
    args = parser.parse_args(argv)
    token = args.token
    if args.phase == "prompt":
        return {"prompt": ("This is a synthetic coordinator fixture in your assigned checkout. Remain idle now; "
                           "do not create the result file yet. Only after a later coordinator message asks you "
                           "to change approach, copy the complete coordination-directive marker from that message "
                           "into " + RESULT + " in your checkout, then finish. Do not modify other files or contact external services.")}
    if args.root is None or args.epic is None or args.issue is None or args.worker is None:
        parser.error("baseline, apply and verify require --root, --epic, --issue and --worker")
    layout, checkout = _bound(args.root, args.epic, args.issue, args.worker)
    result_path = checkout / RESULT
    prefix = "fixture-" + hashlib.sha256(token.encode()).hexdigest()[:24]
    if args.phase in ("baseline", "apply"):
        if result_path.exists() or result_path.is_symlink():
            raise ValueError("fixture result already exists before the directive")
    fetch = _fixture_fetch(args.issue)
    source = "simulated fixture authority port (synthetic Issue); not a GitHub readback"
    if args.phase == "baseline":
        baseline = coord.coordinate(layout, tick=prefix + "-baseline", stall_limit=1, runner=runner, http=http, fetch=fetch)
        return {"boundary": "live owned fixture; wait for the coordinator backoff before apply", "authority_source": source,
                "baseline": baseline}
    if args.phase == "apply":
        state = ew._load_state(layout)
        coordination = state["issue_mappings"][str(args.issue)].get("coordination", {})
        if prefix + "-baseline" not in coordination.get("seen_ticks", []):
            raise ValueError("fixture baseline has not been observed")
        since = coordination.get("unchanged_since")
        try:
            _require_authority(layout, args.issue, fetch)
        except ValueError:
            # Record the stop through the production pass, which contacts no session under it.
            held = coord.coordinate(layout, tick=prefix + "-directive", stall_limit=1, apply=True,
                                    runner=runner, http=http, fetch=fetch)
            return {"boundary": "live owned fixture; source authority stops the directive", "authority_source": source,
                    "result_absent_before": True, "directive_pass": held}
        status = ew.conversation_status(layout, args.worker, runner=runner, http=http)
        if (not isinstance(since, (int, float)) or time.time() - since < coord.STALL_SECONDS
                or str(status.get("execution_status") or "").lower() not in {"idle", "finished", "error", "stuck"}):
            raise ValueError("fixture worker is active or the backoff has not elapsed")
        directed = coord.coordinate(layout, tick=prefix + "-directive", stall_limit=1, apply=True,
                                    runner=runner, http=http, fetch=fetch)
        return {"boundary": "live owned fixture; independent acceptance still required", "authority_source": source,
                "result_absent_before": True, "directive_pass": directed}
    contents, gap = coord._read_bounded(checkout, RESULT, 256)
    if gap or contents is None:
        raise ValueError("fixture result is unavailable or not a bounded regular file")
    _require_authority(layout, args.issue, fetch)
    observed = coord.coordinate(layout, tick=prefix + "-observe", stall_limit=1, runner=runner, http=http, fetch=fetch)
    if args.issue in observed["held"] or any("authority" in (item.get("evidence_gaps") or {}) for item in observed["items"]):
        raise ValueError("the observation pass is held or its authority is unavailable; no fixture success")
    state = ew._load_state(layout)
    deliveries = [r for r in state["dispatch_decisions"] if isinstance(r, dict)
               and r.get("kind") == "epic_coordination_effect" and r.get("issue") == args.issue
               and r.get("worker") == args.worker and r.get("tick") == prefix + "-directive"]
    if (len(deliveries) != 1 or deliveries[0].get("outcome") != "delivered"
            or not deliveries[0].get("event_id") or not deliveries[0].get("result")
            or contents.strip() != str(deliveries[0].get("marker")).encode()):
        raise ValueError("directive event or later changed work evidence has not been observed")
    mapping = state["issue_mappings"][str(args.issue)]
    _require_authority(layout, args.issue, fetch)
    with effects._session(layout, args.issue, args.worker, mapping, runner=runner, http=http) as (port, key, cid, _, identity):
        event_id, _, event_timestamp = effects._observe(port, key, cid, deliveries[0]["marker"], http,
                                                         layout=layout, issue=args.issue, worker=args.worker)
    try:
        event_time = datetime.fromisoformat(str(event_timestamp).replace("Z", "+00:00")).timestamp()
        result_stat = os.stat(result_path, follow_symlinks=False)
    except (ValueError, OSError) as exc:
        raise ValueError("directive event ordering is unavailable") from exc
    work = ew.inspect_checkout(layout, args.worker, runner=runner)
    if (event_id != deliveries[0]["event_id"] or not stat.S_ISREG(result_stat.st_mode)
            or result_stat.st_mtime_ns <= int(event_time * 1_000_000_000)
            or RESULT not in work.get("uncommitted_paths", [])
            or ew._checkout_mount_identity(layout, args.worker, mapping) != identity):
        raise ValueError("fixture result is not current checkout evidence after the directive event")
    _require_authority(layout, args.issue, fetch)
    return {"boundary": "fixture evidence only; independent acceptance still required", "authority_source": source,
            "result_file": str(result_path),
            "directive_event_id": deliveries[0]["event_id"], "result_evidence": deliveries[0]["result"], "observation_pass": observed}


def main() -> int:
    try:
        result = _run()
        print(result["prompt"] if set(result) == {"prompt"} else json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ValueError, OSError, ew.EpicWorkspaceError) as exc:
        print(f"fixture refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
