"""Episode note store + rebuildable projection (ERE-02, ADR-0051 OD-1/OD-2).

Episode notes are vault-canonical (SoR); ``app/jobs/episodes_projection.py`` builds a
rebuildable PG projection for query only -- the projection is never authoritative.
"""

from __future__ import annotations
