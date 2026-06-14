from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from scripts.yaml_roundtrip import load_frontmatter

from app.agent_memory.candidate import ActivationPolicy, MemoryCandidate, MemoryType, ReviewState
from app.agent_memory.materialization import (
    DEFAULT_MATERIALIZATION_RECEIPTS_PATH,
    DEFAULT_MEMORY_DIR,
)
from app.agent_memory.promotion import PromotedMemory
from app.receipts.promotion_receipts import (
    PromotionReceiptQuery,
    PromotionReceiptRow,
    query_promotion_receipts,
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "we",
    "with",
}


@dataclass(frozen=True)
class RecallCandidate:
    promoted: PromotedMemory
    score: float
    reason: str
    artifact_path: str | None = None
    receipt_id: str | None = None


def read_promoted_memories(
    *,
    vault_root: str | Path | None = None,
    outbox_path: str | Path | None = None,
    records: Iterable[dict[str, Any]] | None = None,
    memory_dir: str = DEFAULT_MEMORY_DIR,
) -> list[PromotedMemory]:
    """Read materialized promoted memories back into frozen promotion artifacts."""

    resolved_root = _resolve_vault_root(vault_root)
    if resolved_root is None or not resolved_root.exists() or not resolved_root.is_dir():
        return []

    rows = _materialized_rows(
        vault_root=resolved_root,
        outbox_path=_resolve_outbox_path(outbox_path),
        records=records,
    )
    memories: list[PromotedMemory] = []
    for row in rows:
        promoted = _promoted_from_row(
            row,
            vault_root=resolved_root,
            memory_dir=memory_dir,
        )
        if promoted is not None:
            memories.append(promoted)
    return memories


def retrieve_relevant_promoted(
    query: str,
    *,
    k: int = 3,
    vault_root: str | Path | None = None,
    outbox_path: str | Path | None = None,
    records: Iterable[dict[str, Any]] | None = None,
    memory_dir: str = DEFAULT_MEMORY_DIR,
) -> list[RecallCandidate]:
    """Return a scarce, relevance-ranked subset of promoted memories for recall."""

    if k <= 0:
        return []
    query_tokens = _tokens(query)
    if not query_tokens:
        return []

    resolved_root = _resolve_vault_root(vault_root)
    if resolved_root is None or not resolved_root.exists() or not resolved_root.is_dir():
        return []

    rows = _materialized_rows(
        vault_root=resolved_root,
        outbox_path=_resolve_outbox_path(outbox_path),
        records=records,
    )
    candidates: list[RecallCandidate] = []
    for row in rows:
        promoted = _promoted_from_row(
            row,
            vault_root=resolved_root,
            memory_dir=memory_dir,
        )
        if promoted is None:
            continue
        score, reason = _score(promoted, query_tokens)
        if score <= 0:
            continue
        candidates.append(
            RecallCandidate(
                promoted=promoted,
                score=score,
                reason=reason,
                artifact_path=row.artifact_path,
                receipt_id=row.receipt_id,
            )
        )

    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.score,
            candidate.promoted.decided_at,
            candidate.promoted.candidate.title,
        ),
        reverse=True,
    )[:k]


def _resolve_vault_root(vault_root: str | Path | None) -> Path | None:
    if vault_root is not None:
        return Path(vault_root).expanduser().resolve()
    env_root = os.getenv("VAULT_ROOT")
    if not env_root:
        return None
    return Path(env_root).expanduser().resolve()


def _resolve_outbox_path(outbox_path: str | Path | None) -> Path:
    if outbox_path is not None:
        return Path(outbox_path).expanduser()
    return DEFAULT_MATERIALIZATION_RECEIPTS_PATH


def _materialized_rows(
    *,
    vault_root: Path,
    outbox_path: Path | None,
    records: Iterable[dict[str, Any]] | None,
) -> tuple[PromotionReceiptRow, ...]:
    try:
        result = query_promotion_receipts(
            PromotionReceiptQuery(
                transition_family="agent_memory_materialization",
                target_maturity="semantic_memory",
                outcome_status="applied",
            ),
            vault_root=vault_root,
            outbox_path=outbox_path,
            records=records,
        )
    except Exception:
        return ()
    if not result.source_available:
        return ()
    return result.rows


def _promoted_from_row(
    row: PromotionReceiptRow,
    *,
    vault_root: Path,
    memory_dir: str,
) -> PromotedMemory | None:
    if not row.artifact_path:
        return None
    note_path = (vault_root / row.artifact_path).resolve()
    if not _is_relative_to(note_path, vault_root.resolve()) or not note_path.exists():
        return None
    try:
        raw = note_path.read_text(encoding="utf-8")
    except OSError:
        return None
    frontmatter, body = load_frontmatter(raw)
    if not _is_agent_promoted_memory(frontmatter, row=row, memory_dir=memory_dir):
        return None
    title, content = _title_and_content(body, fallback=note_path.stem)
    candidate_id = _first_str(
        frontmatter.get("promoted_from_candidate_id"),
        row.artifact_linkage.get("candidate_id"),
        row.basis.get("candidate_id"),
        row.artifact_uuid,
    )
    if not candidate_id:
        return None
    decided_at = _parse_datetime(
        _first_str(frontmatter.get("decided_at"), row.timestamp)
    )
    promoted_at = _parse_datetime(row.timestamp)
    source_refs = _string_list(frontmatter.get("source_refs"))
    candidate = MemoryCandidate(
        candidate_id=candidate_id,
        title=title,
        memory_type=MemoryType.SEMANTIC_MEMORY,
        artifact_type=_first_str(frontmatter.get("artifact_type")) or "semantic_memory",
        review_state=ReviewState.ACCEPTED,
        activation_policy=ActivationPolicy.EXPLICIT_OR_CONTEXTUAL,
        inferred=_inferred_posture(frontmatter=frontmatter, row=row),
        source_refs=source_refs,
        derived_from=_first_str(frontmatter.get("derived_from")),
        generated_by=_first_str(frontmatter.get("generated_by")),
        content=content,
        observed_at=decided_at,
    )
    return PromotedMemory(
        promotion_id=row.receipt_id,
        outcome=ReviewState.ACCEPTED,
        candidate=candidate,
        decided_by=_first_str(frontmatter.get("decided_by"), row.authority.get("requested_by")) or "unknown",
        decided_at=decided_at,
        decision_notes=_first_str(frontmatter.get("decision_notes")),
        promoted_at=promoted_at,
    )


def _is_agent_promoted_memory(
    frontmatter: dict[str, Any],
    *,
    row: PromotionReceiptRow,
    memory_dir: str,
) -> bool:
    if row.target_maturity != "semantic_memory":
        return False
    if row.outcome_status != "applied":
        return False
    artifact_type = _first_str(frontmatter.get("artifact_type"))
    if artifact_type and artifact_type != "semantic_memory":
        return False
    labels = set(_string_list(frontmatter.get("labels")))
    if frontmatter.get("agent_promoted") is True or "agent-promoted-memory" in labels:
        return True
    return bool(row.artifact_path and row.artifact_path.startswith(f"{memory_dir.rstrip('/')}/"))


def _title_and_content(body: str, *, fallback: str) -> tuple[str, str]:
    lines = body.lstrip().splitlines()
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip() or fallback
        content = "\n".join(lines[1:]).strip()
        return title, content or title
    content = body.strip()
    return fallback, content or fallback


def _score(promoted: PromotedMemory, query_tokens: set[str]) -> tuple[float, str]:
    title_tokens = _tokens(promoted.candidate.title)
    content_tokens = _tokens(promoted.candidate.content or "")
    source_tokens = _tokens(" ".join(promoted.candidate.source_refs))
    title_matches = query_tokens & title_tokens
    content_matches = query_tokens & content_tokens
    source_matches = query_tokens & source_tokens
    score = float((len(title_matches) * 3) + (len(content_matches) * 2) + len(source_matches))
    reason_parts: list[str] = []
    if title_matches:
        reason_parts.append(f"title matched {', '.join(sorted(title_matches))}")
    if content_matches:
        reason_parts.append(f"content matched {', '.join(sorted(content_matches))}")
    if source_matches:
        reason_parts.append(f"source matched {', '.join(sorted(source_matches))}")
    return score, "; ".join(reason_parts) or "no lexical overlap"


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in (match.group(0).lower() for match in _TOKEN_RE.finditer(value))
        if len(token) > 1 and token not in _STOPWORDS
    }


def _first_str(*values: object) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _inferred_posture(*, frontmatter: dict[str, Any], row: PromotionReceiptRow) -> bool:
    inferred = _bool_or_none(frontmatter.get("inferred"))
    if inferred is not None:
        return inferred
    inferred = _bool_or_none(row.basis.get("inferred"))
    if inferred is not None:
        return inferred
    return True


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    return None


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


__all__ = [
    "RecallCandidate",
    "read_promoted_memories",
    "retrieve_relevant_promoted",
]
