"""Create the Gemini call log, model cooldowns and learned quotas.

Revision ID: 0001
Revises:
Create Date: 2026-11-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Datetimes are stored as naive UTC; db.UTCDateTime converts at the edges
    op.create_table(
        "gemini_calls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("task", sa.String(length=50), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("thought_tokens", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("gemini_calls") as batch_op:
        batch_op.create_index("ix_gemini_calls_started_at", ["started_at"])
        batch_op.create_index("ix_gemini_calls_model_started_at", ["model", "started_at"])

    op.create_table(
        "model_cooldowns",
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("until", sa.DateTime(), nullable=False),
        sa.Column("hard", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("strikes", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("model"),
    )
    op.create_table(
        "model_quotas",
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("daily_limit", sa.Integer(), nullable=False),
        sa.Column("learned_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("model"),
    )


def downgrade() -> None:
    op.drop_table("model_quotas")
    op.drop_table("model_cooldowns")
    with op.batch_alter_table("gemini_calls") as batch_op:
        batch_op.drop_index("ix_gemini_calls_model_started_at")
        batch_op.drop_index("ix_gemini_calls_started_at")
    op.drop_table("gemini_calls")
