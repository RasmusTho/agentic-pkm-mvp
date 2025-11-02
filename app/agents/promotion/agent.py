from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from app.observability.tracing import current_trace_id, span, start_tracer
from app.promotion.queue import LOG as _LOG
from app.promotion.queue import run_once as _worker_run_once


def _append_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


class PromotionAgent:
    name = "promotion-agent"

    def plan(self) -> None:
        with span("agent.plan"):
            _append_jsonl(
                _LOG,
                {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "level": "debug",
                    "event": "promote.agent.plan",
                    "agent": self.name,
                    "trace_id": current_trace_id(),
                },
            )

    def act(self) -> int:
        with span("agent.act"):
            return _worker_run_once()

    def reflect(self, processed: int) -> None:
        with span("agent.reflect"):
            _append_jsonl(
                _LOG,
                {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "level": "info",
                    "event": "promote.agent.run",
                    "agent": self.name,
                    "processed": processed,
                    "trace_id": current_trace_id(),
                },
            )

    def run_once(self) -> int:
        with span("agent.run_once"):
            self.plan()
            processed = self.act()
            self.reflect(processed)
            return processed


def main() -> None:
    start_tracer("promotion-agent")
    parser = argparse.ArgumentParser(prog="agents.promotion")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run")
    args = parser.parse_args()
    if args.cmd == "run":
        PromotionAgent().run_once()


if __name__ == "__main__":
    main()
