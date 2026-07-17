"""Independent migration lineage for the BuilderOps authority database."""

from pathlib import Path

# Bootstrap floor only. The live epoch is database-owned and may advance after
# a restore; application startup must preserve, not cap, that monotonic value.
AUTHORITY_EPOCH = 1
MIGRATIONS = tuple(sorted(Path(__file__).parent.glob("[0-9][0-9][0-9][0-9]_*.sql")))
SCHEMA_VERSION = len(MIGRATIONS)

if not MIGRATIONS:  # pragma: no cover - packaging corruption guard
    raise RuntimeError("BuilderOps control-plane migrations are missing")
