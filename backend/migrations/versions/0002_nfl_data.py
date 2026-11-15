"""games, roster_weeks, feed_status

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "games",
        sa.Column("game_id", sa.String(32), primary_key=True),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("week", sa.Integer(), nullable=False),
        sa.Column("home_team", sa.String(8), nullable=False),
        sa.Column("away_team", sa.String(8), nullable=False),
        sa.Column("gameday", sa.String(10), nullable=False),
        sa.Column("kickoff", sa.DateTime()),
        sa.Column("home_score", sa.Integer()),
        sa.Column("away_score", sa.Integer()),
    )
    op.create_index("ix_games_season_week", "games", ["season", "week"])
    op.create_table(
        "roster_weeks",
        sa.Column("season", sa.Integer(), primary_key=True),
        sa.Column("week", sa.Integer(), primary_key=True),
        sa.Column("player_id", sa.String(16), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("position", sa.String(8), nullable=False),
        sa.Column("team", sa.String(8), nullable=False),
        sa.Column("status", sa.String(8)),
    )
    op.create_index(
        "ix_roster_weeks_season_week_team", "roster_weeks", ["season", "week", "team"]
    )
    op.create_table(
        "feed_status",
        sa.Column("feed", sa.String(32), primary_key=True),
        sa.Column("season", sa.Integer(), primary_key=True),
        sa.Column("attempted_at", sa.DateTime(), nullable=False),
        sa.Column("ok_at", sa.DateTime()),
        sa.Column("rows", sa.Integer()),
        sa.Column("error", sa.Text()),
    )


def downgrade() -> None:
    op.drop_table("feed_status")
    op.drop_table("roster_weeks")
    op.drop_table("games")
