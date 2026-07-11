"""Capability Knowledge Model (CKM / Kvasir) — store and object model.

Builder System subsystem (BuilderOps plane, ADR-0057). This package holds the
Capability Evidence Graph (CEG): capabilities, artifacts, evidence edges,
bitemporal assessments, and findings. It is additive to the existing
BuilderOps SQLite substrate (``app/builderops/store.py``) and carries no
runtime/product authority (INV-CKM-2).

Orthogonality (INV-CKM-6, OD-K3): nothing in this package may import runtime
semantic-dimension modules or reference the runtime ``evidence_role`` field.
Enforced by ``tests/builderops/ckm/test_evidence_kind_orthogonality.py``.
"""

from __future__ import annotations
