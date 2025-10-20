"""Agent state tables and interestingness scoring."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "202501140001"
down_revision = "8f7a6c6d18c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("config", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("plan_summary", sa.Text()),
        sa.Column("result_summary", sa.Text()),
    )
    op.create_index("ix_agent_runs_started_at", "agent_runs", ["started_at"])

    op.create_table(
        "agent_tasks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result", JSONB),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
    )
    op.create_index("ix_agent_tasks_run_id", "agent_tasks", ["run_id"])
    op.create_index("ix_agent_tasks_kind", "agent_tasks", ["kind"])

    op.create_table(
        "agent_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agent_tasks.id", ondelete="CASCADE"),
        ),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "ts",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_agent_events_run_id_ts", "agent_events", ["run_id", "ts"])

    op.create_table(
        "agent_memories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
        ),
        sa.Column("layer", sa.String(length=32), nullable=False, server_default="short_term"),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("provenance", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_agent_memories_layer", "agent_memories", ["layer"])
    op.create_index(
        "ix_agent_memories_payload",
        "agent_memories",
        ["payload"],
        postgresql_using="gin",
        postgresql_ops={"payload": "jsonb_path_ops"},
    )

    op.create_table(
        "agent_heartbeats",
        sa.Column("agent_name", sa.String(length=64), primary_key=True),
        sa.Column("run_id", UUID(as_uuid=True)),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="idle"),
        sa.Column(
            "last_seen",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "interesting_items",
        sa.Column(
            "object_id",
            UUID(as_uuid=True),
            sa.ForeignKey("objects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
        ),
        sa.Column("novelty", sa.Float(), nullable=False),
        sa.Column("anomaly", sa.Float(), nullable=False),
        sa.Column("uncertainty", sa.Float(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_interesting_items_score", "interesting_items", ["score"])
    op.create_index("ix_interesting_items_created_at", "interesting_items", ["created_at"])

    op.create_table(
        "feature_flags",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("value", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("scope", sa.String(length=64)),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("feature_flags")
    op.drop_index("ix_interesting_items_created_at", table_name="interesting_items")
    op.drop_index("ix_interesting_items_score", table_name="interesting_items")
    op.drop_table("interesting_items")
    op.drop_table("agent_heartbeats")
    op.drop_index("ix_agent_memories_payload", table_name="agent_memories")
    op.drop_index("ix_agent_memories_layer", table_name="agent_memories")
    op.drop_table("agent_memories")
    op.drop_index("ix_agent_events_run_id_ts", table_name="agent_events")
    op.drop_table("agent_events")
    op.drop_index("ix_agent_tasks_kind", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_run_id", table_name="agent_tasks")
    op.drop_table("agent_tasks")
    op.drop_index("ix_agent_runs_started_at", table_name="agent_runs")
    op.drop_table("agent_runs")
