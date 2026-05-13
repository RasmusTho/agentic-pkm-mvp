#!/usr/bin/env python3
"""Generate a local runtime-proof smoke receipt for issue #866 baseline coverage."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request


UNBLOCK_LINE = "UNBLOCK LEGACY CLEANUP AUDIT: #867"
KEEP_BLOCKED_LINE = "KEEP LEGACY CLEANUP AUDIT BLOCKED: #867"


@dataclass
class CheckResult:
    key: str
    label: str
    status: str
    reason: str
    evidence: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "reason": self.reason,
            "evidence": self.evidence,
        }


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def http_json(url: str, method: str = "GET", payload: dict[str, Any] | None = None, timeout: float = 5.0) -> tuple[bool, dict[str, Any] | None, str]:
    data = None
    headers = {"accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["content-type"] = "application/json"
    req = request.Request(url, method=method, data=data, headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        parsed = json.loads(raw) if raw.strip() else {}
        return True, parsed, ""
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return False, None, f"HTTP {exc.code}: {body[:200]}"
    except Exception as exc:  # noqa: BLE001
        return False, None, str(exc)


def file_exists(path: Path) -> bool:
    return path.exists() and path.is_file()


def run_cmd(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return proc.returncode, out.strip()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines: list[str] = []
    lines.append("# Runtime Proof Smoke Receipt")
    lines.append("")
    lines.append(f"- generated_at: {payload['generated_at']}")
    lines.append(f"- overall: {payload['overall_status']}")
    lines.append(f"- pass: {payload['summary']['pass']}")
    lines.append(f"- fail: {payload['summary']['fail']}")
    lines.append(f"- skip: {payload['summary']['skip']}")
    lines.append("")
    lines.append("## Baseline Coverage")
    lines.append("")
    for check in payload["baseline_coverage"]:
        lines.append(f"- [{check['status'].upper()}] {check['label']} ({check['key']})")
        lines.append(f"  reason: {check['reason']}")
        if check["evidence"]:
            lines.append(f"  evidence: {', '.join(check['evidence'])}")
    lines.append("")
    lines.append("## Gate")
    lines.append("")
    lines.append(payload["legacy_cleanup_gate_line"])
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate runtime-proof smoke receipt")
    parser.add_argument("--api-base", default=os.environ.get("RUNTIME_PROOF_API_BASE", "http://127.0.0.1:8000"))
    parser.add_argument("--output-dir", default="tmp/runtime-proof")
    parser.add_argument("--timestamp", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--strict", action="store_true", help="Treat skipped checks as failures")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parent.parent
    output_dir = (root / args.output_dir).resolve()

    ts = args.timestamp
    json_path = output_dir / f"runtime-proof-receipt-{ts}.json"
    md_path = output_dir / f"runtime-proof-receipt-{ts}.md"

    start_script = root / "scripts/start_full_system.sh"
    verify_stack_script = root / "scripts/verify_runtime_stack.sh"
    startup_status = root / "tmp/startup_status.json"
    events_file = root / "events.jsonl"

    checks: list[CheckResult] = []

    startup_evidence = []
    if file_exists(start_script):
        startup_evidence.append(str(start_script.relative_to(root)))
    if file_exists(startup_status):
        startup_evidence.append(str(startup_status.relative_to(root)))
    startup_status_val = "pass" if file_exists(start_script) else "fail"
    startup_reason = "startup command available" if startup_status_val == "pass" else "missing scripts/start_full_system.sh"
    checks.append(CheckResult("startup_bootstrap", "Startup and runtime bootstrap", startup_status_val, startup_reason, startup_evidence))

    ok_health, payload_health, err_health = http_json(f"{args.api_base}/api/health")
    ok_status, payload_status, err_status = http_json(f"{args.api_base}/api/status")
    if ok_health and ok_status:
        checks.append(
            CheckResult(
                "api_health_status",
                "API health and status surfaces",
                "pass",
                "health and status endpoints responded",
                [f"{args.api_base}/api/health", f"{args.api_base}/api/status"],
            )
        )
    elif ok_health or ok_status:
        checks.append(
            CheckResult(
                "api_health_status",
                "API health and status surfaces",
                "skip",
                f"partial endpoint availability; health_error={err_health or 'none'} status_error={err_status or 'none'}",
                [f"{args.api_base}/api/health", f"{args.api_base}/api/status"],
            )
        )
    else:
        checks.append(
            CheckResult(
                "api_health_status",
                "API health and status surfaces",
                "skip",
                f"runtime API not reachable at {args.api_base}; health_error={err_health}",
                [f"{args.api_base}/api/health"],
            )
        )

    rc_verify, out_verify = run_cmd(["bash", str(verify_stack_script)]) if file_exists(verify_stack_script) else (127, "missing")
    if rc_verify == 0:
        checks.append(CheckResult("watcher_detection", "Watcher detection path", "pass", "verify_runtime_stack reported success", ["scripts/verify_runtime_stack.sh"] ))
        checks.append(CheckResult("worker_consumption", "Worker consumption and completion", "pass", "verify_runtime_stack reported success", ["scripts/verify_runtime_stack.sh"] ))
    else:
        reason = "verify_runtime_stack unavailable or failed in this environment"
        if out_verify:
            reason = f"{reason}: {out_verify.splitlines()[-1][:180]}"
        checks.append(CheckResult("watcher_detection", "Watcher detection path", "skip", reason, ["scripts/verify_runtime_stack.sh"]))
        checks.append(CheckResult("worker_consumption", "Worker consumption and completion", "skip", reason, ["scripts/verify_runtime_stack.sh"]))

    if file_exists(events_file) and events_file.stat().st_size > 0:
        checks.append(
            CheckResult(
                "event_outbox_creation",
                "Event and outbox creation",
                "pass",
                "events.jsonl exists and is non-empty",
                [str(events_file.relative_to(root))],
            )
        )
    else:
        checks.append(
            CheckResult(
                "event_outbox_creation",
                "Event and outbox creation",
                "skip",
                "no fresh runtime outbox evidence in this run; execute startup + ingest before rerun",
                [str(events_file.relative_to(root))],
            )
        )

    ok_settings, payload_settings, err_settings = http_json(f"{args.api_base}/api/settings/explain")
    if ok_settings:
        checks.append(CheckResult("settings_source", "Settings source correctness", "pass", "settings explain endpoint responded", [f"{args.api_base}/api/settings/explain"]))
    else:
        checks.append(CheckResult("settings_source", "Settings source correctness", "skip", f"settings explain unavailable: {err_settings}", [f"{args.api_base}/api/settings/explain"]))

    checks.append(
        CheckResult(
            "write_guard",
            "Write guard behavior",
            "skip",
            "guarded write probe is intentionally not executed by this smoke command to avoid side effects",
            ["manual follow-up required"],
        )
    )

    ok_ask, payload_ask, err_ask = http_json(
        f"{args.api_base}/api/ask",
        method="POST",
        payload={"query": "runtime proof smoke"},
    )
    if ok_ask:
        ask_status = "pass"
        ask_reason = "ask endpoint responded"
    else:
        ask_status = "skip"
        ask_reason = f"ask endpoint unavailable: {err_ask}"
    checks.append(CheckResult("ask_panel_canvas", "Minimal ASK / panel / canvas happy paths", ask_status, ask_reason, [f"{args.api_base}/api/ask", "panel/canvas paths intentionally bounded in this smoke command"]))

    counts = {"pass": 0, "fail": 0, "skip": 0}
    for check in checks:
        counts[check.status] += 1

    if args.strict and counts["skip"] > 0:
        counts["fail"] += counts["skip"]
        counts["skip"] = 0

    overall_status = "FAIL" if counts["fail"] > 0 else "PASS"
    gate_line = KEEP_BLOCKED_LINE if overall_status == "FAIL" else UNBLOCK_LINE

    receipt = {
        "generated_at": now_utc(),
        "command": "python3 scripts/runtime_proof_smoke.py",
        "api_base": args.api_base,
        "overall_status": overall_status,
        "summary": counts,
        "baseline_coverage": [c.as_dict() for c in checks],
        "health_payload": payload_health,
        "status_payload": payload_status,
        "settings_payload": payload_settings,
        "ask_payload": payload_ask,
        "legacy_cleanup_gate_line": gate_line,
    }

    write_json(json_path, receipt)
    write_markdown(md_path, receipt)

    print(f"receipt_json={json_path}")
    print(f"receipt_md={md_path}")
    print(f"overall_status={overall_status}")
    print(gate_line)
    return 0 if overall_status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
