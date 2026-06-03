"""Read-only artifact-scoped projection for agent-memory review posture."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.agent_memory.review_queue import (
    MemoryCandidateReviewQueue,
    ReviewEntry,
    ReviewStatus,
)
from app.receipts.outbox_sources import normalize_note_path


@dataclass(frozen=True)
class AgentMemoryPostureTarget:
    artifact_uuid: str | None
    note_path: str


_SOURCE_NAME = "agent_memory.review_queue"
_NON_AUTHORITY = "non_authoritative"
_STATUS_TO_STATE = {
    ReviewStatus.PENDING: "pending",
    ReviewStatus.PROMOTED: "promoted",
    ReviewStatus.REJECTED: "rejected",
    ReviewStatus.REVISED: "revised",
}
_COUNT_KEYS = ("pending", "promoted", "rejected", "revised")
_UUID_REF_PREFIXES = {"artifact_uuid", "note_uuid", "uuid"}
_PATH_REF_PREFIXES = {"artifact_path", "note_path", "path", "vault", "vault_path"}


def agent_memory_posture_for_artifacts(
    targets: Iterable[AgentMemoryPostureTarget],
    *,
    queue: MemoryCandidateReviewQueue | None,
    vault_root: Path,
) -> dict[str, dict[str, Any]] | None:
    """Return non-authoritative memory posture keyed by target note path.

    ``None`` means no safe posture source is available. A returned empty posture
    for a target means the review-queue source is connected but has no explicit
    candidate reference for that artifact.
    """

    target_list = list(targets)
    if not target_list:
        return {}
    if queue is None:
        return None

    path_targets = {
        normalize_note_path(target.note_path, vault_root=vault_root): target
        for target in target_list
    }
    uuid_targets = {
        str(target.artifact_uuid).strip(): target
        for target in target_list
        if target.artifact_uuid and str(target.artifact_uuid).strip()
    }
    result = {
        target.note_path: _empty_posture()
        for target in target_list
    }

    for entry in queue.pending() + queue.decided():
        refs = _entry_artifact_refs(entry, vault_root=vault_root)
        matched: set[str] = set()
        for artifact_uuid in refs["uuids"]:
            target = uuid_targets.get(artifact_uuid)
            if target is not None:
                matched.add(target.note_path)
        for artifact_path in refs["paths"]:
            target = path_targets.get(artifact_path)
            if target is not None:
                matched.add(target.note_path)
        if not matched:
            continue

        item = _entry_item(entry)
        state = str(item["status"])
        for note_path in matched:
            posture = result[note_path]
            posture["items"].append(item)
            posture["counts"][state] += 1

    for posture in result.values():
        posture["items"].sort(key=lambda item: str(item.get("candidate_id") or ""))
        posture["state"] = _aggregate_state(posture["counts"])
    return result


def _empty_posture() -> dict[str, Any]:
    return {
        "source": _SOURCE_NAME,
        "authority": _NON_AUTHORITY,
        "state": "no_agent_memory",
        "counts": {key: 0 for key in _COUNT_KEYS},
        "items": [],
    }


def _entry_item(entry: ReviewEntry) -> dict[str, Any]:
    candidate = entry.candidate
    return {
        "candidate_id": candidate.candidate_id,
        "title": candidate.title,
        "status": _STATUS_TO_STATE[entry.status],
        "review_state": candidate.review_state.value,
        "memory_type": candidate.memory_type.value,
        "inferred": candidate.inferred,
        "source_refs": list(candidate.source_refs),
        "derived_from": candidate.derived_from,
        "generated_by": candidate.generated_by,
        "revision_of": entry.revision_of,
    }


def _entry_artifact_refs(entry: ReviewEntry, *, vault_root: Path) -> dict[str, set[str]]:
    candidate = entry.candidate
    refs = list(candidate.source_refs)
    if candidate.derived_from:
        refs.append(candidate.derived_from)
    uuids: set[str] = set()
    paths: set[str] = set()
    for ref in refs:
        prefix, value = _split_explicit_ref(ref)
        if prefix in _UUID_REF_PREFIXES and value:
            uuids.add(value)
        elif prefix in _PATH_REF_PREFIXES and value:
            normalized = normalize_note_path(value, vault_root=vault_root)
            if normalized:
                paths.add(normalized)
    return {"uuids": uuids, "paths": paths}


def _split_explicit_ref(ref: str) -> tuple[str, str | None]:
    prefix, separator, value = str(ref or "").partition(":")
    if not separator:
        return "", None
    normalized_prefix = prefix.strip().lower()
    normalized_value = value.strip()
    if not normalized_prefix or not normalized_value:
        return "", None
    return normalized_prefix, normalized_value


def _aggregate_state(counts: dict[str, int]) -> str:
    active = [key for key in _COUNT_KEYS if counts.get(key, 0) > 0]
    if not active:
        return "no_agent_memory"
    if len(active) == 1:
        return active[0]
    return "mixed"


__all__ = [
    "AgentMemoryPostureTarget",
    "agent_memory_posture_for_artifacts",
]
