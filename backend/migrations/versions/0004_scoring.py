"""touchdown_credits, game_results

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "touchdown_credits",
        sa.Column("game_id", sa.String(32), primary_key=True),
        sa.Column("play_id", sa.Integer(), primary_key=True),
        sa.Column("player_id", sa.String(16), primary_key=True),
        sa.Column("kind", sa.String(8), primary_key=True),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("player_name", sa.String(128)),
        sa.Column("team", sa.String(8)),
    )
    op.create_index("ix_touchdown_credits_season", "touchdown_credits", ["season"])
    op.create_table(
        "game_results",
        sa.Column("game_id", sa.String(32), primary_key=True),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("home_score", sa.Integer()),
        sa.Column("away_score", sa.Integer()),
    )
    op.create_index("ix_game_results_season", "game_results", ["season"])


def downgrade() -> None:
    op.drop_table("game_results")
    op.drop_table("touchdown_credits")
