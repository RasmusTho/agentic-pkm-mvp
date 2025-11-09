#!/usr/bin/env python3
"""
pkm CLI – kör agent-pipelinen från terminalen.

Exempel:
  # Kör hela pipen på en fil (normalize -> classify) och skriv resultat som JSON
  python -m app.cli pipe ./notes/foo.md

  # Bara normalisera fil och få object_id
  python -m app.cli normalize ./notes/foo.md

  # Klassificera ett befintligt object_id
  python -m app.cli classify 00000000-0000-0000-0000-000000000000
"""
from __future__ import annotations
import os, sys, json, argparse, uuid
from pathlib import Path
from typing import Any, Dict

# Fail-safe: om ingen backend är satt, forsa minnesläge för lokal körning.
os.environ.setdefault("STORE_BACKEND", "memory")

# Mocka LLM som default (kan överskridas via env)
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault(
    "LLM_MOCK_RESPONSE",
    '{"type":"note","trust":"own","tags":["topic/cli"],"confidence":0.95}'
)

# Importera agenterna enligt repo-layouten (ref: tests använde dessa symboler)
from app.agents.normalizer.agent import run as normalize_run
from app.agents.classifier.agent import run as classify_run

def _trace(prefix: str) -> str:
    return f"cli-{prefix}-{uuid.uuid4()}"

def _print_json(obj: Dict[str, Any]) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2)
    print()

def cmd_normalize(args: argparse.Namespace) -> int:
    src = Path(args.path)
    if not src.exists():
        print(f"Fel: fil saknas: {src}", file=sys.stderr)
        return 2
    res = normalize_run(str(src), trace_id=_trace("normalize"))
    # res bör innehålla bl a object_id (enligt testerna)
    _print_json({"stage":"normalize", **res})
    return 0

def cmd_classify(args: argparse.Namespace) -> int:
    oid = str(args.object_id)
    res = classify_run(oid, trace_id=_trace("classify"))
    _print_json({"stage":"classify", "object_id": oid, **res})
    return 0

def cmd_pipe(args: argparse.Namespace) -> int:
    src = Path(args.path)
    if not src.exists():
        print(f"Fel: fil saknas: {src}", file=sys.stderr)
        return 2
    # 1) normalize
    nres = normalize_run(str(src), trace_id=_trace("pipe-norm"))
    oid = nres.get("object_id")
    # 2) classify (på normalized object)
    cres = classify_run(oid, trace_id=_trace("pipe-class"))
    out = {
        "stage": "pipe",
        "source": str(src),
        "object_id": oid,
        "normalize": nres,
        "classify": cres,
    }
    _print_json(out)
    # Skriv även en JSONL-rad till outbox om env är satt (ingen skada i memory-läge)
    outbox = os.environ.get("INDEX_OUTBOX_PATH")
    if outbox:
        line = {
            "event": "pipe_result",
            "object_id": oid,
            "source_ref": f"cli:{src.name}",
            "payload": out,
        }
        Path(outbox).parent.mkdir(parents=True, exist_ok=True)
        with open(outbox, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    return 0

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pkm", description="Agentisk PKM CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_norm = sub.add_parser("normalize", help="Normalisera en fil")
    p_norm.add_argument("path", help="Sökväg till källa (fil)")
    p_norm.set_defaults(func=cmd_normalize)

    p_cls = sub.add_parser("classify", help="Klassificera ett object_id")
    p_cls.add_argument("object_id", help="UUID för objektet")
    p_cls.set_defaults(func=cmd_classify)

    p_pipe = sub.add_parser("pipe", help="Kör normalize -> classify på en fil")
    p_pipe.add_argument("path", help="Sökväg till källa (fil)")
    p_pipe.set_defaults(func=cmd_pipe)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        return 130

if __name__ == "__main__":
    raise SystemExit(main())
