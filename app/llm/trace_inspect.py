from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from app.llm.trace import TRACE_PATH


@dataclass
class LLMTraceRecord:
    timestamp: float
    trace_id: str
    provider: str
    model: str
    agent: str
    kind: str
    prompt_preview: str
    response_preview: str


def _as_path(path: Optional[Path] = None) -> Path:
    if path is not None:
        return path
    env_path = os.getenv("LLM_TRACE_PATH")
    if env_path:
        return Path(env_path)
    return TRACE_PATH


def load_trace(path: Optional[Path] = None) -> List[LLMTraceRecord]:
    resolved = _as_path(path)
    if not resolved.exists():
        return []
    records: List[LLMTraceRecord] = []
    try:
        with resolved.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                try:
                    records.append(
                        LLMTraceRecord(
                            timestamp=float(obj.get("timestamp") or 0.0),
                            trace_id=str(obj.get("trace_id") or ""),
                            provider=str(obj.get("provider") or ""),
                            model=str(obj.get("model") or ""),
                            agent=str(obj.get("agent") or ""),
                            kind=str(obj.get("kind") or ""),
                            prompt_preview=str(obj.get("prompt_preview") or ""),
                            response_preview=str(obj.get("response_preview") or ""),
                        )
                    )
                except Exception:
                    continue
    except FileNotFoundError:
        return []
    return records


def group_by_trace_id(records: List[LLMTraceRecord]) -> Dict[str, List[LLMTraceRecord]]:
    grouped: Dict[str, List[LLMTraceRecord]] = {}
    for rec in records:
        grouped.setdefault(rec.trace_id, []).append(rec)
    for recs in grouped.values():
        recs.sort(key=lambda r: r.timestamp)
    sorted_items = sorted(grouped.items(), key=lambda item: item[1][0].timestamp if item[1] else 0.0)
    return {trace_id: recs for trace_id, recs in sorted_items}


def filter_flows(
    records: List[LLMTraceRecord],
    agent: Optional[str] = None,
    kind_prefix: Optional[str] = None,
) -> List[LLMTraceRecord]:
    filtered: List[LLMTraceRecord] = []
    for rec in records:
        if agent and rec.agent != agent:
            continue
        if kind_prefix and not rec.kind.startswith(kind_prefix):
            continue
        filtered.append(rec)
    return filtered


__all__ = ["LLMTraceRecord", "load_trace", "group_by_trace_id", "filter_flows"]
