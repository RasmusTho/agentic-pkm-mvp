"""Migration reversibility classification for pre-promotion checks.

Per docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md:
- Two classifications: "reversible" and "forward-only".
- Marker is mandatory in every migration file; absent or invalid marker fails the check.
- Classification is about reversal-path existence, not migration success.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REVERSIBLE = "reversible"
FORWARD_ONLY = "forward-only"
VALID_MARKERS: frozenset[str] = frozenset({REVERSIBLE, FORWARD_ONLY})
HEIMDAL_RAW_REPRESENTATION_MIGRATION = (
    "e7b4c9d2a6f1_heimdal_raw_representation.py"
)

# Matches `reversibility = "..."` or `reversibility: str = "..."` at line start.
_MARKER_RE = re.compile(
    r'^reversibility\s*(?::\s*str\s*)?\s*=\s*["\']([^"\']+)["\']',
    re.MULTILINE,
)


class MigrationMarkerError(ValueError):
    """Raised when a migration file is missing or has an invalid reversibility marker."""


@dataclass(frozen=True)
class MigrationClassificationResult:
    migration: str
    classification: str
    is_forward_only: bool

    def to_receipt(self) -> dict:
        return {
            "migration": self.migration,
            "classification": self.classification,
            "is_forward_only": self.is_forward_only,
        }


def read_migration_marker(path: Path) -> str:
    """Extract and validate the reversibility marker from a migration file.

    Raises MigrationMarkerError if the marker is absent or not one of VALID_MARKERS.
    """
    text = path.read_text(encoding="utf-8")
    match = _MARKER_RE.search(text)
    if not match:
        raise MigrationMarkerError(
            f"Migration {path.name!r} is missing a 'reversibility' marker. "
            f"Add `reversibility = \"{REVERSIBLE}\"` or `reversibility = \"{FORWARD_ONLY}\"` "
            f"to the migration file."
        )
    value = match.group(1)
    if value not in VALID_MARKERS:
        raise MigrationMarkerError(
            f"Migration {path.name!r} has an invalid reversibility marker {value!r}. "
            f"Allowed values: {sorted(VALID_MARKERS)}."
        )
    return value


def classify_migration(path: Path) -> MigrationClassificationResult:
    """Read, validate, and classify a single migration file."""
    classification = read_migration_marker(path)
    return MigrationClassificationResult(
        migration=path.name,
        classification=classification,
        is_forward_only=(classification == FORWARD_ONLY),
    )


def check_all_migrations(paths: Iterable[Path]) -> dict:
    """Validate reversibility markers for all migration files and return a receipt.

    Raises MigrationMarkerError on the first missing or invalid marker so the
    pre-promotion check fails visibly before any ref is moved.

    Returns a receipt dict suitable for inclusion in the promotion plan:
    {
        "migrations_checked": int,
        "reversible": [name, ...],
        "forward_only": [name, ...],
        "classification_decisions": [{"migration": ..., "classification": ..., "is_forward_only": ...}, ...],
    }
    """
    results: list[MigrationClassificationResult] = []
    for path in paths:
        results.append(classify_migration(path))

    return {
        "migrations_checked": len(results),
        "reversible": [r.migration for r in results if not r.is_forward_only],
        "forward_only": [r.migration for r in results if r.is_forward_only],
        "classification_decisions": [r.to_receipt() for r in results],
    }


def heimdal_raw_representation_migration_pending(receipt: object) -> bool:
    """Select the HAR-02 migration from a complete classification receipt.

    The deploy path uses this value-free predicate to decide whether the
    migration-only raw-store key consumer must be preflighted.  Receipt shape,
    filenames, classifications, and duplicate entries are all checked before
    the selector is trusted so malformed or ambiguous input fails closed.
    """

    def invalid() -> MigrationMarkerError:
        return MigrationMarkerError("invalid migration receipt")

    def valid_filename(value: object) -> bool:
        return (
            isinstance(value, str)
            and bool(value)
            and value.endswith(".py")
            and "/" not in value
            and "\\" not in value
            and value not in {".", ".."}
        )

    if not isinstance(receipt, dict):
        raise invalid()

    expected_count = receipt.get("migrations_checked")
    decisions = receipt.get("classification_decisions")
    reversible = receipt.get("reversible")
    forward_only = receipt.get("forward_only")
    if (
        type(expected_count) is not int
        or expected_count < 0
        or not isinstance(decisions, list)
        or not isinstance(reversible, list)
        or not isinstance(forward_only, list)
        or expected_count != len(decisions)
    ):
        raise invalid()

    names: list[str] = []
    expected_reversible: list[str] = []
    expected_forward_only: list[str] = []
    for decision in decisions:
        if not isinstance(decision, dict):
            raise invalid()
        migration = decision.get("migration")
        classification = decision.get("classification")
        is_forward_only = decision.get("is_forward_only")
        if (
            not valid_filename(migration)
            or classification not in VALID_MARKERS
            or type(is_forward_only) is not bool
            or is_forward_only != (classification == FORWARD_ONLY)
        ):
            raise invalid()
        assert isinstance(migration, str)
        names.append(migration)
        if is_forward_only:
            expected_forward_only.append(migration)
        else:
            expected_reversible.append(migration)

    if len(names) != len(set(names)):
        raise invalid()
    if reversible != expected_reversible or forward_only != expected_forward_only:
        raise invalid()

    return HEIMDAL_RAW_REPRESENTATION_MIGRATION in names
