from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

_DEFAULT_VAULT = Path("tmp/vault_smoke")
_DEFAULT_OUTBOX = Path("tmp/index-outbox.smoke.jsonl")

_EXPECTED_EVENTS = {"mcp.vault.append_note", "promote.intent.created", "panel.intent.created"}


def _env(outbox: Path) -> Dict[str, str]:
    env = os.environ.copy()
    env.setdefault("STORE_BACKEND", "memory")
    env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    env.setdefault("POLICY_ENFORCE", "1")
    env["INDEX_OUTBOX_PATH"] = str(outbox)
    return env


def _run_smoke(vault: Path, outbox: Path) -> tuple[Dict[str, Any], subprocess.CompletedProcess[str]]:
    cmd = [
        sys.executable,
        "-m",
        "app.cli",
        "smoke",
        "reality",
        "--vault",
        str(vault),
        "--outbox",
        str(outbox),
        "--json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=_env(outbox))
    stdout = proc.stdout.strip().splitlines()
    payload = stdout[-1] if stdout else ""
    summary = json.loads(payload) if payload else {}
    return summary, proc


def _load_outbox(outbox: Path) -> List[Dict[str, Any]]:
    if not outbox.exists():
        return []
    events: List[Dict[str, Any]] = []
    for line in outbox.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _fail(message: str, proc: subprocess.CompletedProcess[str]) -> None:
    sys.stderr.write(message + "\n")
    sys.stderr.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    raise SystemExit(1)


def _assert_events(outbox_events: List[Dict[str, Any]]) -> None:
    seen = {evt.get("event") for evt in outbox_events if isinstance(evt, dict)}
    if not (_EXPECTED_EVENTS & seen):
        raise AssertionError("expected panel/promotion or mcp append event in outbox")


def _assert_note_written(created_notes: List[str]) -> None:
    if not created_notes:
        raise AssertionError("no notes created during smoke run")
    for path in created_notes:
        p = Path(path)
        if not p.exists():
            raise AssertionError(f"expected note to exist: {p}")
        if not p.read_text(encoding="utf-8").strip():
            raise AssertionError(f"note is empty: {p}")


def _check_stdout(proc: subprocess.CompletedProcess[str]) -> None:
    haystack = (proc.stdout + proc.stderr).lower()
    if "traceback" in haystack or "error" in haystack:
        raise AssertionError("stderr/stdout contained error markers")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify reality smoke run")
    parser.add_argument("--vault", type=Path, default=_DEFAULT_VAULT, help="Vault root used for smoke run")
    parser.add_argument("--outbox", type=Path, default=_DEFAULT_OUTBOX, help="Outbox path used for smoke run")
    args = parser.parse_args()

    args.vault.mkdir(parents=True, exist_ok=True)
    args.outbox.parent.mkdir(parents=True, exist_ok=True)
    if args.outbox.exists():
        args.outbox.write_text("", encoding="utf-8")

    summary, proc = _run_smoke(args.vault, args.outbox)
    if proc.returncode != 0:
        _fail("smoke run failed", proc)

    outbox_events = _load_outbox(args.outbox)
    try:
        _assert_note_written(summary.get("created_notes") or [])
        _assert_events(outbox_events)
        _check_stdout(proc)
    except AssertionError as exc:
        _fail(str(exc), proc)

    print("Reality smoke: OK")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
