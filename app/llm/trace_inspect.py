from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.llm.trace import TRACE_PATH


@dataclass
class LLMTraceRecord:
    timestamp: float
    trace_id: str
    provider: str
    model: str
    agent: str
    kind: str
    prompt_preview: Any = None
    response_preview: Any = None
    mode: str = ""
    status: str = ""
    raw_response_preview: Any = None
    response_text_preview: Any = None


@dataclass
class LLMSequenceStep:
    index: int
    timestamp: float
    agent: str
    kind: str
    prompt_preview: Any = None
    response_preview: Any = None
    mode: str = ""
    status: str = ""


@dataclass
class LLMSequence:
    trace_id: str
    steps: List[LLMSequenceStep]


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
                            mode=str(obj.get("mode") or ""),
                            status=str(obj.get("status") or ""),
                            prompt_preview=obj.get("prompt_preview"),
                            response_preview=obj.get("response_preview"),
                            raw_response_preview=obj.get("raw_response_preview"),
                            response_text_preview=obj.get("response_text_preview"),
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


def build_sequence_for_trace(records: List[LLMTraceRecord], trace_id: str) -> LLMSequence:
    """Filter records by trace_id and build a sorted sequence."""
    selected = [r for r in records if r.trace_id == trace_id]
    if not selected:
        raise ValueError(f"No trace records found for trace_id={trace_id!r}")
    selected.sort(key=lambda r: r.timestamp)
    steps: List[LLMSequenceStep] = []
    for idx, rec in enumerate(selected, start=1):
        steps.append(
            LLMSequenceStep(
                index=idx,
                timestamp=rec.timestamp,
                agent=rec.agent,
                kind=rec.kind,
                mode=getattr(rec, "mode", ""),
                status=getattr(rec, "status", ""),
                prompt_preview=rec.prompt_preview,
                response_preview=rec.response_preview,
            )
        )
    return LLMSequence(trace_id=trace_id, steps=steps)


def list_agents_in_sequence(seq: LLMSequence) -> List[str]:
    """Return distinct agents in order of first appearance."""
    seen = set()
    ordered: List[str] = []
    for step in seq.steps:
        if step.agent not in seen:
            seen.add(step.agent)
            ordered.append(step.agent)
    return ordered


__all__ = [
    "LLMTraceRecord",
    "LLMSequence",
    "LLMSequenceStep",
    "build_sequence_for_trace",
    "load_trace",
    "group_by_trace_id",
    "filter_flows",
    "list_agents_in_sequence",
]
