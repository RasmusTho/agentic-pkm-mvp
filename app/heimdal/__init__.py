"""Heimdal constituent (the ecosystem's ingestion/sensing organ, ADR-0049).

This package holds both the Heimdal-owned ingestion substrate and the
Mimer-side integration points that substrate hands off to:

- `app/heimdal/observation_log.py`, `app/heimdal/cursor_store.py`,
  `app/heimdal/publish.py` (#3039, Epic #3019 slice A2) -- the append-only
  observation log and its per-consumer-cursor publish path: the canonical
  Heimdal <-> Mimer constituent seam (ADR-0049 §1; FABLE_COMPANION §4.2/§1.2;
  see `docs/EVENTS.md :: Heimdal observation log`).
- `app/heimdal/entity_register.py` (#3038, Epic #3019 slice A1) is
  Mimer-owned per ADR-0049 §1 / the 2026-07-05 owner ruling
  (`docs/HEIMDAL/FABLE_COMPANION.md` §9 "Decision run" item 1): Heimdal emits
  entity *mentions* only; canonical resolution and the register itself live
  here, on Mimer's side of the seam.
- `app/heimdal/consent_ledger.py` (#3042, Epic #3019 slice A5) -- the
  append-only consent-grant ledger + the HEIM-3 capture-time check
  (`admit_raw_evidence`, the one sanctioned signal->raw admission call),
  seeded with the standing `self_record` grant (ADR-0049 §3 Posture A;
  FABLE_COMPANION §6.1/§6.2; see
  `docs/EVENTS.md :: Heimdal consent ledger v0 + capture-time check`).
"""

from __future__ import annotations
