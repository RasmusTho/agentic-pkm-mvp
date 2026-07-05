"""Cognitive Expansion -- Connect + Create (north-star capabilities).

Spec: ``docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md``.
This slice (EXP-1, #2994) ships the Connect pass: `connect.*` findings
(related-unlinked, thematic links) surfaced as propose-track
``CurationFinding``s through the existing G2 pipeline and G2 writer.
Candidate-only by construction -- see ``app.expansion.connect``.
"""
from __future__ import annotations

from app.expansion.connect import (
    ConnectPassConfig,
    ConnectPassReport,
    DeclinedLedgerPort,
    run_connect_pass,
)

__all__ = [
    "ConnectPassConfig",
    "ConnectPassReport",
    "DeclinedLedgerPort",
    "run_connect_pass",
]
