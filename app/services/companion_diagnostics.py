"""
Companion diagnostics — health summary for companion note integrity.

Reports duplicate companion notes (same UUID in both canonical and legacy locations)
so operators can safely resolve them via an explicit migration path.

Issue #974: prod ingest writes duplicate companion notes in two system locations.
"""
from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from app.services.companion_note import find_duplicate_companions


class CompanionDiagnosticsSummary(TypedDict):
    """Health summary for companion note integrity checks."""
    duplicate_companion_count: int
    duplicate_companion_uuids: list[str]


def companion_diagnostics_summary(vault_root: Path) -> CompanionDiagnosticsSummary:
    """
    Return a health summary for companion notes in the vault.

    Currently reports:
    - duplicate_companion_count: number of UUIDs present in both canonical and legacy locations
    - duplicate_companion_uuids: list of those UUIDs (sorted for determinism)

    This function is read-only. It does not delete, move, or modify any files.

    Args:
        vault_root: Absolute path to the vault root.

    Returns:
        CompanionDiagnosticsSummary with counts and UUIDs of duplicated companions.
    """
    duplicates = find_duplicate_companions(vault_root)
    return CompanionDiagnosticsSummary(
        duplicate_companion_count=len(duplicates),
        duplicate_companion_uuids=[d.uuid for d in duplicates],
    )


__all__ = [
    "CompanionDiagnosticsSummary",
    "companion_diagnostics_summary",
]
