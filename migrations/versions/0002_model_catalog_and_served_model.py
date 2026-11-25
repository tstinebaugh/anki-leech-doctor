"""Add the Gemini model catalog and record which model served each call.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Datetimes are stored as naive UTC; db.UTCDateTime converts at the edges
    op.create_table(
        "gemini_models",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=True),
        sa.Column("output_token_limit", sa.Integer(), nullable=True),
        sa.Column("thinking", sa.Boolean(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )
    with op.batch_alter_table("gemini_calls", schema=None) as batch_op:
        batch_op.add_column(sa.Column("model_version", sa.String(length=100), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("gemini_calls", schema=None) as batch_op:
        batch_op.drop_column("model_version")
    op.drop_table("gemini_models")
