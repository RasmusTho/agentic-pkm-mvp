"""Heimdal constituent (the ecosystem's ingestion/sensing organ, ADR-0049).

This package holds Mimer-side integration points and Mimer-owned substrate
that Heimdal's ingestion pipeline depends on. The entity register
(`app/heimdal/entity_register.py`) is Mimer-owned per ADR-0049 §1 / the
2026-07-05 owner ruling (`docs/HEIMDAL/FABLE_COMPANION.md` §9 "Decision run"
item 1): Heimdal emits entity *mentions* only; canonical resolution and the
register itself live here, on Mimer's side of the seam.
"""

from __future__ import annotations
