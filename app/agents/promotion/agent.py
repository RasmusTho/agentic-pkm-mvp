from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from app.events.types import PROMOTE_AGENT_PLAN, PROMOTE_AGENT_RUN
from app.observability.tracing import current_trace_id, span, start_tracer
from app.promotion.queue import _log_path
from app.promotion.queue import run_once as _worker_run_once


def _append_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _append_agent_log(obj: dict) -> None:
    path = _log_path()
    if path is None:
        return
    _append_jsonl(path, obj)


class PromotionAgent:
    name = "promotion-agent"

    def plan(self) -> None:
        with span("agent.plan"):
            _append_agent_log(
                {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "level": "debug",
                    "event": PROMOTE_AGENT_PLAN,
                    "agent": self.name,
                    "trace_id": current_trace_id(),
                },
            )

    def act(self) -> int:
        with span("agent.act"):
            return _worker_run_once()

    def reflect(self, processed: int) -> None:
        with span("agent.reflect"):
            _append_agent_log(
                {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "level": "info",
                    "event": PROMOTE_AGENT_RUN,
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
