from __future__ import annotations

import json
from pathlib import Path
from typing import List

from app.reasoning.provider import MockReasoner
from app.reasoning.schema import ReasoningInput, RelationSnapshot

DATASET_PATH = Path("data") / "golden" / "reasoning_samples.jsonl"


def _load_samples() -> List[dict]:
    records: List[dict] = []
    if not DATASET_PATH.exists():
        return records
    with DATASET_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def reasoning_metrics(flag_enabled: bool) -> dict[str, float]:
    if not flag_enabled:
        return {"claims_avg": 0.0, "inferences_avg": 0.0, "conflicts": 0.0}
    samples = _load_samples()
    if not samples:
        return {"claims_avg": 0.0, "inferences_avg": 0.0, "conflicts": 0.0}
    reasoner = MockReasoner()
    claims_total = 0
    inference_total = 0
    conflicts = 0
    for sample in samples:
        relations = [
            RelationSnapshot.model_validate(rel) for rel in sample.get("relations") or []
        ]
        reasoning_input = ReasoningInput(
            object_uuid=sample.get("object_uuid", ""),
            text=sample.get("text", ""),
            metadata={},
            relations=relations,
        )
        output = reasoner.reason(reasoning_input)
        claims_total += len(output.claims)
        inference_total += len(output.inferences)
        conflicts += sum(1 for inf in output.inferences if inf.type == "contradiction")
    count = len(samples)
    return {
        "claims_avg": claims_total / count if count else 0.0,
        "inferences_avg": inference_total / count if count else 0.0,
        "conflicts": float(conflicts),
    }


__all__ = ["reasoning_metrics", "DATASET_PATH"]
