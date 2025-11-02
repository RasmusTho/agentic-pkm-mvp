from __future__ import annotations

import json
from uuid import uuid4
from datetime import datetime, timezone
from typing import Any

from app.db import conn_rw

UTC = timezone.utc


def put_decision(
    object_id: str,
    key: str,
    value: dict[str, Any],
    *,
    agent: str | None = None,
    kind: str | None = None,
) -> dict[str, str]:
    # Öppna en transaktion, INSERT ... RETURNING id, commit-a, returnera id
    with conn_rw() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO decisions (id, object_id, agent, kind, key, value, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s) RETURNING id",
                (str(uuid4()), object_id, agent, kind, key, json.dumps(value), datetime.now(UTC)),
            )
            row = cur.fetchone()
        conn.commit()

    if row is None:
        return {"id": ""}

    try:
        decision_id = row["id"]
    except Exception:
        decision_id = row[0]
    return {"id": str(decision_id)}
