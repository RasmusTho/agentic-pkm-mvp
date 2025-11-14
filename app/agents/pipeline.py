from __future__ import annotations

import os
from typing import Any, Dict, List, Set
from uuid import UUID

from app.agents.base.audit import audit_log
from app.ingest.chunk_policy import build_chunks
from app.ingest.deduper import Deduper
from app.orchestrator.runtime import Orchestrator, OrchestratorError, PlanValidationError
from app.reasoning.provider import get_reasoner
from app.reasoning.schema import ReasoningInput, RelationSnapshot, ReasoningValidationError
from app.reasoning.store import get_reasoning_store
from app.stores import get_relation_index
from app.planner.provider import PlannerInput, get_planner
from app.planner.schema import Plan

_deduper = Deduper()
_AGENT = "ingest-pipeline"
_PLANNER_AGENT = "planner-agent"
_ORCHESTRATOR: Orchestrator | None = None


def ingest_and_chunk(obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    text = obj.get("text", "")
    segments = obj.get("segments") if _diarization_enabled() else None
    chunk_records = build_chunks(text, segments=segments)
    out: List[Dict[str, Any]] = []
    speakers: Set[str] = set()
    for idx, record in enumerate(chunk_records):
        chunk_text = record.get("text", "")
        if _deduper.is_dup(chunk_text, obj.get("uuid", "")):
            out.append({"kind": "duplicate", "index": idx})
        else:
            chunk_payload: Dict[str, Any] = {"kind": "chunk", "index": idx, "text": chunk_text}
            if speaker := record.get("speaker"):
                chunk_payload["speaker"] = speaker
                speakers.add(speaker)
            if "start" in record:
                chunk_payload["start"] = record["start"]
            if "end" in record:
                chunk_payload["end"] = record["end"]
            if "speaker_segments" in record:
                chunk_payload["speaker_segments"] = record["speaker_segments"]
            out.append(chunk_payload)
    _audit_chunk_creation(
        object_id=str(obj.get("uuid") or ""),
        trace_id=obj.get("trace_id"),
        chunks=len([entry for entry in out if entry.get("kind") == "chunk"]),
        speaker_count=len(speakers) if _diarization_enabled() and speakers else None,
    )
    _run_reasoning_if_enabled(obj, text)
    maybe_plan_for_object(str(obj.get("uuid") or ""), text, obj.get("trace_id"))
    return out


def _diarization_enabled() -> bool:
    return os.getenv("DIARIZE_ENABLE", "").strip().lower() in {"1", "true", "yes", "on"}


def _reasoning_enabled() -> bool:
    return os.getenv("REASONING_ENABLE", "").strip().lower() in {"1", "true", "yes", "on"}


def _planner_enabled() -> bool:
    return os.getenv("PLANNER_ENABLE", "").strip().lower() in {"1", "true", "yes", "on"}


def _orchestrator_enabled() -> bool:
    return os.getenv("ORCHESTRATOR_ENABLE", "").strip().lower() in {"1", "true", "yes", "on"}


def _audit_chunk_creation(
    *,
    object_id: str | None,
    trace_id: str | None,
    chunks: int,
    speaker_count: int | None,
) -> None:
    if not object_id:
        return
    details: Dict[str, Any] = {"chunks": chunks}
    if speaker_count is not None:
        details["speaker_count"] = speaker_count
    audit_log(
        object_id=object_id,
        agent=_AGENT,
        action="text.chunk.created",
        trace_id=trace_id,
        details=details,
    )


def _run_reasoning_if_enabled(obj: Dict[str, Any], text: str) -> None:
    if not _reasoning_enabled():
        return
    object_id = str(obj.get("uuid") or "").strip()
    if not object_id or not text:
        return
    relations = _collect_relation_snapshots(object_id)
    reasoning_input = ReasoningInput(
        object_uuid=object_id,
        text=text,
        metadata=obj.get("metadata") or obj.get("frontmatter") or {},
        relations=relations,
    )
    reasoner = get_reasoner()
    try:
        output = reasoner.reason(reasoning_input)
    except ReasoningValidationError as exc:
        audit_log(
            object_id=object_id,
            agent=_AGENT,
            action="reasoning.validation.error",
            trace_id=obj.get("trace_id"),
            details={"error": str(exc)},
        )
        return
    stats = get_reasoning_store().upsert(object_id, output)
    if stats["claims"]:
        audit_log(
            object_id=object_id,
            agent=_AGENT,
            action="reasoning.claim.added",
            trace_id=obj.get("trace_id"),
            details={"claims": stats["claims"], "evidence": stats["evidence"]},
        )
    if stats["inferences"]:
        audit_log(
            object_id=object_id,
            agent=_AGENT,
            action="reasoning.inference.added",
            trace_id=obj.get("trace_id"),
            details={"inferences": stats["inferences"]},
        )


def _collect_relation_snapshots(object_id: str) -> List[RelationSnapshot]:
    try:
        uuid = UUID(object_id)
    except Exception:
        return []
    rel_index = get_relation_index()
    relations: List[RelationSnapshot] = []
    for rel_type in ("supports", "extends", "contradicts", "derived_from"):
        try:
            neighbors = rel_index.neighbors(uuid, rel=rel_type, k=50)
        except Exception:
            neighbors = []
        for neighbor in neighbors:
            relations.append(
                RelationSnapshot(
                    source=object_id,
                    target=str(neighbor),
                    type=rel_type,
                )
            )
    return relations


def maybe_plan_for_object(object_id: str, text: str, trace_id: str | None) -> Plan | None:
    if not _planner_enabled():
        return None
    object_id = object_id.strip()
    text = text.strip()
    if not object_id or not text:
        return None
    metadata = {"trace_id": trace_id} if trace_id else {}
    planner_input = PlannerInput(
        object_uuid=object_id,
        goal="Analyze and structure follow-up actions for this note",
        text=text,
        relations=[],
        metadata=metadata,
    )
    planner = get_planner()
    try:
        plan = planner.plan(planner_input)
    except Exception as exc:
        audit_log(
            object_id=object_id,
            agent=_PLANNER_AGENT,
            action="planner.plan.error",
            trace_id=trace_id,
            details={"error": str(exc)},
        )
        return None
    audit_log(
        object_id=object_id,
        agent=_PLANNER_AGENT,
        action="planner.plan.created",
        trace_id=trace_id,
        details={"plan_id": plan.id, "steps": len(plan.steps)},
    )
    maybe_execute_plan(plan)
    return plan


def _get_orchestrator() -> Orchestrator:
    global _ORCHESTRATOR
    if _ORCHESTRATOR is None:
        _ORCHESTRATOR = Orchestrator()
    return _ORCHESTRATOR


def maybe_execute_plan(plan: Plan | None) -> List[Dict[str, Any]] | None:
    if plan is None or not _orchestrator_enabled():
        return None
    orchestrator = _get_orchestrator()
    try:
        return orchestrator.run_plan(plan)
    except PlanValidationError as exc:
        audit_log(
            object_id=plan.meta.source_object_uuid,
            agent=_PLANNER_AGENT,
            action="orchestrator.plan.invalid",
            trace_id=plan.meta.trace_id,
            details={"plan_id": plan.id, "error": str(exc)},
        )
    except OrchestratorError as exc:
        audit_log(
            object_id=plan.meta.source_object_uuid,
            agent=_PLANNER_AGENT,
            action="orchestrator.plan.error",
            trace_id=plan.meta.trace_id,
            details={"plan_id": plan.id, "error": str(exc)},
        )
    return None
