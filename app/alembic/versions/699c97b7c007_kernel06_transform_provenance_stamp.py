"""KERNEL-06 (#2768): transform provenance stamp — content_hash lookup index.

Every ``store_vector_index`` upsert now carries a ``provenance`` object
(``source_ref``, ``content_hash``, ``chunk_policy_version``,
``pipeline_version``, ``embedding_identity``) inside the existing ``payload``
JSONB column — no new hard column, since the stamp rides the same upsert
statement as the vector (cross-task invariant #4; no separate "stamp later"
write). This migration adds a read-path index so the doctor's staleness scan
(comparing stored vs. current ``content_hash``) and future lookups by hash
do not require a sequential scan of ``store_vector_index`` at scale.

``IF NOT EXISTS`` / ``IF EXISTS`` semantics: safe to run repeatedly, no data
movement, no table lock beyond standard `CREATE INDEX` (non-concurrent, in
line with the other DDL in this migration chain — the store tables are small
enough in every current deployment that a brief lock is acceptable; revisit
with `CREATE INDEX CONCURRENTLY` in a follow-up if that changes).

Reversible: the index is purely additive and can be dropped without any loss
of durable data (the provenance fields remain in `payload` regardless).

Revision ID: 699c97b7c007
Revises: 1a739d9494af
Create Date: 2026-07-04 16:15:08.879619

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '699c97b7c007'
down_revision: Union[str, None] = '1a739d9494af'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Reversibility classification — required for pre-promotion checks.
# See docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md
# Allowed values: "reversible" | "forward-only"
reversibility: str = "reversible"


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_store_vector_index_content_hash
        ON store_vector_index ((payload ->> 'content_hash'))
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_store_vector_index_content_hash")
