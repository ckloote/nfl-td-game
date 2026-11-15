"""seasons

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seasons",
        sa.Column("year", sa.Integer(), primary_key=True),
        sa.Column("invite_token", sa.String(64), nullable=False, unique=True),
    )


def downgrade() -> None:
    op.drop_table("seasons")
