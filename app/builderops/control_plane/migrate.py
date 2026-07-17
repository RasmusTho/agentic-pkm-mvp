"""Explicit migration-gate entrypoint; never imported by service startup."""

from __future__ import annotations

import json
import os

from app.builderops.control_plane.selection import database_environment, production_store


def main() -> int:
    store = production_store(database_environment(os.environ))
    store.initialize()
    print(json.dumps(store.readiness(), sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - container entrypoint
    raise SystemExit(main())
