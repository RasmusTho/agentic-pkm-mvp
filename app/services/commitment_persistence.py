"""Durable vault-backed persistence for ``CommitmentRecord``s.

Slice 1 of the Commitment Surfacing capability (parent #1960, issue #2073).

Spec: ``docs/COMMITMENT_SURFACING/PERSIST_COMMITMENTS_AS_VAULT_ARTEFACTS.md``

Substrate decision (pinned): commitments persist as **their own** agent-maintained
vault artefacts in the companion-note family, one file per commitment:

    vault/<system_dir>/commitments/<commitment_id>.md

This own-artefact shape (rather than a section inside a related note's companion note)
follows ``docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md :: Relation to artifacts``: a
commitment is not reducible to a note, and *the absence of one canonical note must not
mean the commitment does not exist*. Binding a commitment to a host note's companion
section would re-tie the commitment's existence to that note's lifecycle — exactly what
the contract forbids. A standalone artefact keeps the commitment durable independent of
any note.

State posture (pinned): the ``CommitmentState`` family is persisted in a dedicated
``commitment_state`` frontmatter field and never collapsed into the artifact state axes
``review_state`` / ``maturity`` (``docs/CONCEPTS/STATE_AXES_CONTRACT.md``,
``docs/COMMITMENT_AS_FIRST_CLASS/DEFINE_COMMITMENT_STATE_TRANSITIONS.md``).

Write posture: read/proposal-only and WriteGuard-governed. Every write asserts the
WriteGuard at this production call site *before* any filesystem mutation, so a
write-blocked runtime state raises ``WritesBlockedError`` and leaves no artefact on disk
(atomic-or-absent), mirroring ``app/agent_memory/materialization.py`` and
``app/services/companion_note.py``. This slice does NOT perform commitment state
transitions or auto-closure (governed elsewhere); it only persists and reads.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from app.domain.commitments import (
    CommitmentRecord,
    normalize_commitment_kind,
    normalize_commitment_state,
)
from app.knowledge.write_ops import write_note_relative
from app.vault.manager import VaultContext
from app.vault.paths import get_vault_system_dir_rel
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter

COMMITMENT_PERSIST_ACTION = "commitment.persist"
COMMITMENTS_DIR_NAME = "commitments"

# Marks the artefact as an agent-maintained commitment record in the companion-note
# family. These are descriptive identity keys (like materialization's artifact_class),
# NOT the artifact state axes (review_state / maturity).
COMMITMENT_ARTIFACT_CLASS = "commitment"


class CommitmentPersistenceError(RuntimeError):
    """Raised when a commitment cannot be persisted or read through governance."""


def _vault_root(context: VaultContext) -> Path:
    if not context.active_vault_path:
        raise CommitmentPersistenceError("vault_context.active_vault_path is required")
    return Path(context.active_vault_path).expanduser().resolve()


def _commitments_dir_rel(vault_root: Path) -> PurePosixPath:
    system_dir = get_vault_system_dir_rel(vault_root)
    return PurePosixPath(system_dir) / COMMITMENTS_DIR_NAME


def _safe_id(commitment_id: str) -> str:
    """Filesystem-safe slug for a commitment_id, preserving readability.

    The slug is only the on-disk filename; the canonical ``commitment_id`` is always
    re-read from frontmatter, so collisions between distinct ids that slug identically
    are avoided by embedding the raw id in the artefact body/frontmatter.
    """
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", commitment_id.strip()).strip("-._")
    return cleaned or "commitment"


def commitment_artifact_path(commitment_id: str, vault_root: Path) -> str:
    """Return the vault-relative path for a commitment's own-artefact."""
    rel = _commitments_dir_rel(vault_root) / f"{_safe_id(commitment_id)}.md"
    return rel.as_posix()


def _render_commitment_artifact(record: CommitmentRecord) -> str:
    # Commitment semantics live in dedicated commitment_* fields. No review_state /
    # maturity keys are ever written here (STATE_AXES_CONTRACT.md).
    frontmatter: dict[str, object] = {
        "artifact_class": COMMITMENT_ARTIFACT_CLASS,
        "agent_maintained": True,
        "commitment_id": record.commitment_id,
        "commitment_kind": record.commitment_kind,
        "commitment_state": record.state,
    }
    if record.target_ref:
        frontmatter["target_ref"] = record.target_ref
    if record.summary:
        frontmatter["summary"] = record.summary
    if record.source_goal:
        frontmatter["source_goal"] = record.source_goal
    body = record.summary or record.commitment_id
    return dump_frontmatter(frontmatter, body)


def persist_commitment(
    record: CommitmentRecord,
    *,
    vault_context: VaultContext,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> str:
    """Persist one ``CommitmentRecord`` as a durable vault artefact.

    Asserts the WriteGuard at this production call site before any filesystem mutation;
    a write-blocked runtime state raises ``WritesBlockedError`` and leaves no artefact
    on disk (atomic-or-absent). Returns the vault-relative artefact path on success.
    """
    vault_root = _vault_root(vault_context)
    artifact_path = commitment_artifact_path(record.commitment_id, vault_root)
    content = _render_commitment_artifact(record)

    # WriteGuard first: nothing on disk is created when the guard blocks.
    write_guard.assert_writes_allowed(COMMITMENT_PERSIST_ACTION)
    # Single complete file write (write_note_relative writes the whole artefact atomically
    # via the knowledge port, creating parent dirs as needed).
    write_note_relative(artifact_path, content, vault_root=vault_root)
    return artifact_path


def _record_from_frontmatter(fm: dict[str, object]) -> CommitmentRecord | None:
    raw_id = str(fm.get("commitment_id", "")).strip()
    if not raw_id:
        return None
    try:
        kind = normalize_commitment_kind(fm.get("commitment_kind"))
        state = normalize_commitment_state(fm.get("commitment_state"))
    except ValueError:
        return None

    def _opt(key: str) -> str | None:
        value = fm.get(key)
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    return CommitmentRecord(
        commitment_id=raw_id,
        commitment_kind=kind,
        state=state,
        target_ref=_opt("target_ref"),
        summary=_opt("summary"),
        source_goal=_opt("source_goal"),
    )


def load_commitments(*, vault_context: VaultContext) -> list[CommitmentRecord]:
    """Return all persisted ``CommitmentRecord``s from the vault.

    Reads from the durable artefacts only (never from in-memory ``AgentState``), so the
    result is stable across a process restart. Malformed or non-commitment files in the
    folder are skipped rather than failing the whole read.
    """
    vault_root = _vault_root(vault_context)
    commitments_dir = vault_root / _commitments_dir_rel(vault_root).as_posix()
    if not commitments_dir.exists():
        return []

    records: list[CommitmentRecord] = []
    for path in sorted(commitments_dir.glob("*.md")):
        try:
            fm, _body = load_frontmatter(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(fm, dict):
            continue
        record = _record_from_frontmatter(fm)
        if record is not None:
            records.append(record)
    return records


__all__ = [
    "COMMITMENTS_DIR_NAME",
    "COMMITMENT_ARTIFACT_CLASS",
    "COMMITMENT_PERSIST_ACTION",
    "CommitmentPersistenceError",
    "commitment_artifact_path",
    "load_commitments",
    "persist_commitment",
]
