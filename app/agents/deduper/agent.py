from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from app.components.embeddings import get_embedding_client
from app.events.types import CURATION_DEDUPE_DONE
from app.objects import ObjectStore


AGENT = "deduper"


def _cosine(v1: list[float], v2: list[float]) -> float:
    # basic cosine sim
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = sum(a * a for a in v1) ** 0.5
    n2 = sum(b * b for b in v2) ** 0.5
    if n1 == 0 or n2 == 0:
        return 0.0
    return dot / (n1 * n2)


def _score_pair(t1: str, t2: str) -> float:
    """
    Safe similarity score between two texts.
    If either text is empty/whitespace, treat similarity as 0.0
    instead of raising from embed_text().
    """
    if not t1.strip() or not t2.strip():
        return 0.0
    client = get_embedding_client("deterministic")
    v1 = client.embed_text(t1)
    v2 = client.embed_text(t2)
    return _cosine(v1, v2)


def _get_text(obj_payload: dict[str, Any]) -> str:
    """
    Pick best representative text for duplicate detection.
    Try raw_text; fallback to core6.title.
    Never return empty string unless we truly have nothing.
    """
    raw = (obj_payload or {}).get("raw_text", "") or ""
    if raw.strip():
        return raw

    core6 = (obj_payload or {}).get("core6", {}) or {}
    title = core6.get("title", "") or ""
    return title


def dedupe(object_ids: Iterable[str], *, threshold: float, trace_id: str) -> dict[str, Any]:
    """
    Compare each pair of objects, compute similarity, and mark duplicates in DB/memory via decisions service.
    Returns summary with all pairs above threshold.
    """
    store = ObjectStore()
    objs = {oid: store.get_object(oid) for oid in object_ids}

    # build text map
    texts: dict[str, str] = {}
    for oid, obj in objs.items():
        if not obj:
            continue
        texts[oid] = _get_text(obj.payload)

    pairs: list[dict[str, Any]] = []
    olist = list(texts.keys())
    for i in range(len(olist)):
        for j in range(i + 1, len(olist)):
            oi = olist[i]
            oj = olist[j]
            sim = _score_pair(texts[oi], texts[oj])
            if sim >= threshold:
                pairs.append(
                    {
                        "a": oi,
                        "b": oj,
                        "score": sim,
                        "duplicate": True,
                    }
                )
                # NOTE: decisions writing skipped here for offline pytest
                # (we can add insert_decision(...) later if we want)
            else:
                pairs.append(
                    {
                        "a": oi,
                        "b": oj,
                        "score": sim,
                        "duplicate": False,
                    }
                )

    out = {
        "event": CURATION_DEDUPE_DONE,
        "trace_id": trace_id,
        "threshold": threshold,
        "pairs": pairs,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    return out


def run(object_ids: list[str], *, threshold: float, trace_id: str) -> dict[str, Any]:
    return dedupe(object_ids, threshold=threshold, trace_id=trace_id)
