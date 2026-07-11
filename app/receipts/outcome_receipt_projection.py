"""Postgres projection writer for canonical decision outcome receipts.

The vault JSONL receipt is canonical; this module owns only the rebuildable
``decision_outcomes`` projection boundary.
"""
from __future__ import annotations

from typing import Any

from app.db.db import conn_rw


def insert_outcome_receipt_projection(receipt: dict[str, Any]) -> None:
    """Insert a receipt into the idempotent derived Postgres projection."""
    with conn_rw() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO decision_outcomes
                    (decision_object_id, decision_uuid, rung_index, outcome, note, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (decision_uuid, rung_index) DO NOTHING
                """,
                (
                    receipt["decision_object_id"],
                    receipt["decision_uuid"],
                    receipt["rung_index"],
                    receipt["outcome"],
                    receipt.get("note"),
                    receipt["created_at"],
                ),
            )


__all__ = ["insert_outcome_receipt_projection"]
