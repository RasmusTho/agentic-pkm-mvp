"""Typed, read-only evidence for rebuildable Product mirror integrity.

The doctor consumes caller-provided inventory and provenance snapshots.  It
does not discover paths, open stores, or attempt repair: callers keep both
environment selection and all mutation authority.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class DurablePathClass(str, Enum):
    """The bounded inventory classes accepted by the rebuildability doctor."""

    DERIVED = "derived"
    RUNTIME_DISCARDABLE = "runtime_discardable"
    RECEIPT_TRACE = "receipt_trace"
    OPERATIONAL_EXCEPTION = "operational_exception"


class MirrorFindingCode(str, Enum):
    """Stable, content-free finding codes for diagnostic callers."""

    UNCLASSIFIED_PATH = "unclassified_path"
    MISSING_PROVENANCE = "missing_provenance"
    STALE_GENERATION = "stale_generation"
    ORPHANED_PROJECTION = "orphaned_projection"
    INDEX_IDENTITY_DRIFT = "index_identity_drift"
    DB_SOURCE_MISMATCH = "db_source_mismatch"
    HIDDEN_AUTHORITY = "hidden_authority"
    INCOMPLETE_SNAPSHOT = "incomplete_snapshot"


@dataclass(frozen=True)
class DurablePath:
    """A declared non-document durable path, never a filesystem path to scan."""

    path: str
    classification: DurablePathClass | None = None
    owner: str | None = None
    rebuild_or_retention_source: str | None = None
    sole_meaning_authority: bool = False
    sole_action_authority: bool = False


@dataclass(frozen=True)
class SourceRecord:
    """Digest-bearing source authority supplied by an owner-native reader."""

    identity: str
    generation: str


@dataclass(frozen=True)
class ProjectionRecord:
    """One caller-supplied projection provenance snapshot."""

    projection_id: str
    source_identity: str | None
    source_generation: str | None
    recipe_version: str | None
    index_identity: str | None = None
    expected_index_identity: str | None = None
    db_source_generation: str | None = None
    sole_meaning_authority: bool = False
    sole_action_authority: bool = False


@dataclass(frozen=True)
class MirrorFinding:
    """A stable typed observation with digest-only subject evidence."""

    code: MirrorFindingCode
    subject_digest: str

    @property
    def sort_key(self) -> tuple[str, str]:
        return (self.code.value, self.subject_digest)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject_digest": self.subject_digest}


@dataclass(frozen=True)
class MirrorDoctorReport:
    """Read-only report whose evidence deliberately excludes raw source content."""

    findings: tuple[MirrorFinding, ...]

    @property
    def healthy(self) -> bool:
        return not self.findings

    def as_dict(self) -> dict[str, object]:
        return {
            "healthy": self.healthy,
            "findings": [finding.as_dict() for finding in self.findings],
        }


def _digest(*parts: object) -> str:
    """Return a stable evidence digest without exposing caller-supplied values."""

    material = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _missing(value: str | None) -> bool:
    return not value or not value.strip()


def diagnose_mirror_corruption(
    *,
    inventory: Iterable[DurablePath],
    sources: Iterable[SourceRecord],
    projections: Iterable[ProjectionRecord],
    snapshot_complete: bool = True,
) -> MirrorDoctorReport:
    """Classify supplied mirrors without reading, writing, or authorizing state.

    Callers provide already-bounded snapshots from their owner-native seams. A
    missing or inconsistent snapshot is a finding, never a reason to repair,
    activate, restore, or infer a replacement source.
    """

    findings: list[MirrorFinding] = []
    if not snapshot_complete:
        findings.append(MirrorFinding(MirrorFindingCode.INCOMPLETE_SNAPSHOT, _digest("snapshot")))
    source_generations: dict[str, str] = {}
    for source in sources:
        if not _missing(source.identity) and not _missing(source.generation):
            source_generations[source.identity] = source.generation

    for path in inventory:
        if (
            path.classification is None
            or _missing(path.owner)
            or _missing(path.rebuild_or_retention_source)
        ):
            findings.append(
                MirrorFinding(MirrorFindingCode.UNCLASSIFIED_PATH, _digest("path", path.path))
            )
        if path.sole_meaning_authority or path.sole_action_authority:
            findings.append(
                MirrorFinding(MirrorFindingCode.HIDDEN_AUTHORITY, _digest("path", path.path))
            )

    for projection in projections:
        subject = _digest("projection", projection.projection_id)
        if (
            _missing(projection.source_identity)
            or _missing(projection.source_generation)
            or _missing(projection.recipe_version)
            or _missing(projection.db_source_generation)
        ):
            findings.append(MirrorFinding(MirrorFindingCode.MISSING_PROVENANCE, subject))
        if not _missing(projection.source_identity):
            source_identity = projection.source_identity
            assert source_identity is not None
            source_generation = source_generations.get(source_identity)
            if source_generation is None:
                findings.append(MirrorFinding(MirrorFindingCode.ORPHANED_PROJECTION, subject))
            else:
                if (
                    not _missing(projection.source_generation)
                    and projection.source_generation != source_generation
                ):
                    findings.append(MirrorFinding(MirrorFindingCode.STALE_GENERATION, subject))
                if (
                    not _missing(projection.db_source_generation)
                    and projection.db_source_generation != source_generation
                ):
                    findings.append(MirrorFinding(MirrorFindingCode.DB_SOURCE_MISMATCH, subject))
        if (
            not _missing(projection.expected_index_identity)
            and projection.index_identity != projection.expected_index_identity
        ):
            findings.append(MirrorFinding(MirrorFindingCode.INDEX_IDENTITY_DRIFT, subject))
        if projection.sole_meaning_authority or projection.sole_action_authority:
            findings.append(MirrorFinding(MirrorFindingCode.HIDDEN_AUTHORITY, subject))

    return MirrorDoctorReport(tuple(sorted(set(findings), key=lambda finding: finding.sort_key)))


__all__ = [
    "DurablePath",
    "DurablePathClass",
    "MirrorDoctorReport",
    "MirrorFinding",
    "MirrorFindingCode",
    "ProjectionRecord",
    "SourceRecord",
    "diagnose_mirror_corruption",
]
