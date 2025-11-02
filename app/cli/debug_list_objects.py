from __future__ import annotations
from typing import Any
from app.stores.provider import get_stores

def main() -> None:
    objects, _ = get_stores()
    try:
        rows = list(objects.list(limit=50))  # typ-agnostisk listning
    except Exception:
        # Fallback om din store inte har list(): försök iterera över allting
        rows = []
        try:
            for r in objects:  # type: ignore[attr-defined]
                rows.append(r)
        except Exception:
            pass

    for r in rows:
        d: dict[str, Any] = dict(r) if not isinstance(r, dict) else r
        oid = d.get("id") or d.get("uuid")
        kind = d.get("kind")
        created = d.get("created_at")
        print(f"{oid}\t{kind}\t{created}")

if __name__ == "__main__":
    main()
