from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

_DEFAULT_VAULT = Path("tmp/vault_smoke")
_DEFAULT_OUTBOX = Path("tmp/index-outbox.smoke.jsonl")
_DEFAULT_NOTE = "Smoke - ASK"


def _env(outbox: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("STORE_BACKEND", "memory")
    env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    env.setdefault("POLICY_ENFORCE", "1")
    env.setdefault("PANEL_AGENT_PIPELINE", "planner")
    env.setdefault("LLM_PROVIDER", "mock")
    env.setdefault("EMBED_DIM", "1536")
    env["INDEX_OUTBOX_PATH"] = str(outbox)
    return env


def _run_smoke(vault: Path, outbox: Path) -> tuple[dict, subprocess.CompletedProcess[str]]:
    cmd = [
        sys.executable,
        "-m",
        "app.cli",
        "smoke",
        "ask",
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


def _fail(message: str, proc: subprocess.CompletedProcess[str]) -> None:
    sys.stderr.write(message + "\n")
    sys.stderr.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    raise SystemExit(1)


def _extract_citations(note_text: str) -> list[str]:
    citations: list[str] = []
    for line in note_text.splitlines():
        match = re.match(r"-\s*object_id:\s*(.+)", line.strip())
        if match:
            citations.append(match.group(1).strip())
    return citations


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify ASK smoke run")
    parser.add_argument(
        "--vault",
        type=Path,
        default=_DEFAULT_VAULT,
        help="Vault root used for smoke run",
    )
    parser.add_argument(
        "--outbox",
        type=Path,
        default=_DEFAULT_OUTBOX,
        help="Outbox path used for smoke run",
    )
    parser.add_argument(
        "--note",
        type=str,
        default=_DEFAULT_NOTE,
        help="Note title used for append",
    )
    args = parser.parse_args()

    args.vault.mkdir(parents=True, exist_ok=True)
    args.outbox.parent.mkdir(parents=True, exist_ok=True)
    if args.outbox.exists():
        args.outbox.write_text("", encoding="utf-8")

    summary, proc = _run_smoke(args.vault, args.outbox)
    if proc.returncode != 0:
        _fail("smoke ask run failed", proc)

    note_path = summary.get("note_path")
    if not note_path:
        _fail("missing note_path in summary", proc)
    note_file = Path(note_path)
    if not note_file.exists():
        _fail(f"note not found: {note_file}", proc)
    text = note_file.read_text(encoding="utf-8")
    if "## ASK Answer" not in text:
        _fail("ASK Answer section missing", proc)
    citations = _extract_citations(text)
    if not citations:
        _fail("no citations found in provenance", proc)
    outbox_lines = []
    if args.outbox.exists():
        outbox_lines = args.outbox.read_text(encoding="utf-8").strip().splitlines()
    if not outbox_lines:
        _fail("outbox was empty", proc)

    print("ASK smoke: OK")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
