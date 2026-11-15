"""entries, picks, pick_events

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "season"),
    )
    op.create_index("ix_entries_user_id", "entries", ["user_id"])
    op.create_table(
        "picks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entry_id", sa.Integer(), sa.ForeignKey("entries.id"), nullable=False),
        sa.Column("week", sa.Integer(), nullable=False),
        sa.Column("slot", sa.String(8), nullable=False),
        sa.Column("player_id", sa.String(16), nullable=False),
        sa.Column("player_name", sa.String(128), nullable=False),
        sa.Column("position", sa.String(8), nullable=False),
        sa.Column("team", sa.String(8), nullable=False),
        sa.Column("game_id", sa.String(32), sa.ForeignKey("games.game_id"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("entry_id", "week", "slot"),
        sa.UniqueConstraint("entry_id", "player_id"),
    )
    op.create_index("ix_picks_entry_id", "picks", ["entry_id"])
    op.create_table(
        "pick_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entry_id", sa.Integer(), sa.ForeignKey("entries.id"), nullable=False),
        sa.Column("week", sa.Integer(), nullable=False),
        sa.Column("slot", sa.String(8), nullable=False),
        sa.Column("old_player_id", sa.String(16)),
        sa.Column("new_player_id", sa.String(16)),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_pick_events_entry_id", "pick_events", ["entry_id"])


def downgrade() -> None:
    op.drop_table("pick_events")
    op.drop_table("picks")
    op.drop_table("entries")
