"""Curation — the graduated-curation finding pipeline (G2).

Spec: ``docs/MIMER_CAPABILITY_HARDENING/GRADUATED_CURATION.md``.
This slice (G2-1) ships the finding pipeline core (``CurationFinding``, the
closed class enum, content-derived ``finding_id``) plus the vault-health lint
checks and a read-only, WriteGuard-gated report note. Propose-only: this
package never writes note bodies except the report note itself.
"""
from __future__ import annotations

from app.curation.findings import (
    CurationFinding,
    FindingClass,
    FindingTrack,
    InvalidFindingClassError,
    LanguageVerdict,
    MECHANICAL_ALLOWLIST,
    compute_finding_id,
    track_for_class,
)
from app.curation.lint import LintReport, run_vault_lint, write_lint_report

__all__ = [
    "CurationFinding",
    "FindingClass",
    "FindingTrack",
    "InvalidFindingClassError",
    "LanguageVerdict",
    "MECHANICAL_ALLOWLIST",
    "compute_finding_id",
    "track_for_class",
    "LintReport",
    "run_vault_lint",
    "write_lint_report",
]
