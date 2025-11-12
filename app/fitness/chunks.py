from __future__ import annotations

import json
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any, Dict, List, Tuple

from app.ingest.chunk_policy import build_chunks

DATASET_PATH = Path("data") / "golden" / "diarization_sample.jsonl"


def _percentile(values: List[int], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = max(min(int(round((pct / 100.0) * len(ordered))) - 1, len(ordered) - 1), 0)
    return float(ordered[rank])


def _load_samples() -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []
    if not DATASET_PATH.exists():
        return docs
    with DATASET_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            docs.append(json.loads(line))
    return docs


def _chunk_documents(flag_enabled: bool) -> Tuple[List[int], List[int]]:
    lengths: List[int] = []
    speaker_counts: List[int] = []
    for doc in _load_samples():
        segments = doc.get("segments") if flag_enabled else None
        chunks = build_chunks(
            doc.get("text", ""),
            max_chars=int(doc.get("max_chars", 3000)),
            segments=segments,
        )
        if flag_enabled:
            speakers = {chunk.get("speaker") for chunk in chunks if chunk.get("speaker")}
        else:
            speakers = set()
        speaker_counts.append(len(speakers))
        for chunk in chunks:
            lengths.append(len(chunk.get("text", "")))
    return lengths, speaker_counts


def diarization_metrics(*, flag_enabled: bool) -> Dict[str, float]:
    lengths, speaker_counts = _chunk_documents(flag_enabled)
    chunk_p95 = _percentile(lengths, 95)
    avg_speakers = fmean(speaker_counts) if speaker_counts else 0.0
    std_speakers = pstdev(speaker_counts) if len(speaker_counts) > 1 else 0.0
    return {
        "flag": "on" if flag_enabled else "off",
        "chunk_p95": chunk_p95,
        "speaker_avg": avg_speakers,
        "speaker_std": std_speakers,
    }


__all__ = ["diarization_metrics", "DATASET_PATH"]
