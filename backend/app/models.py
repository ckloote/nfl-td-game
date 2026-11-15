from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, UTCDateTime


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """An account in *your* app. Contains no credentials.

    `email` only ever holds an email the identity provider marked as verified, so it is
    safe to use for linking additional providers to the same account.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    picture: Mapped[str | None] = mapped_column(String(1024))
    is_admin: Mapped[bool] = mapped_column(default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    identities: Mapped[list["Identity"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Identity(Base):
    """One login method for a user: (provider, provider's stable subject ID)."""

    __tablename__ = "identities"
    __table_args__ = (UniqueConstraint("provider", "subject"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    subject: Mapped[str] = mapped_column(String(255))  # OIDC `sub` claim
    email: Mapped[str | None] = mapped_column(String(320))
    email_verified: Mapped[bool] = mapped_column(default=False)

    user: Mapped[User] = relationship(back_populates="identities")


# --- NFL data (replaced wholesale by app/ingest.py; never edited by hand) -----
class Game(Base):
    """One regular-season game from the nflverse schedule."""

    __tablename__ = "games"
    __table_args__ = (Index("ix_games_season_week", "season", "week"),)

    game_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    season: Mapped[int]
    week: Mapped[int]
    home_team: Mapped[str] = mapped_column(String(8))
    away_team: Mapped[str] = mapped_column(String(8))
    gameday: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD, US Eastern
    # None while the league has not published a time; such a game has no lock yet.
    kickoff: Mapped[datetime | None] = mapped_column(UTCDateTime)
    home_score: Mapped[int | None]
    away_score: Mapped[int | None]


class RosterWeek(Base):
    """Who was on which team, at which position, in a given week."""

    __tablename__ = "roster_weeks"
    __table_args__ = (Index("ix_roster_weeks_season_week_team", "season", "week", "team"),)

    season: Mapped[int] = mapped_column(primary_key=True)
    week: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[str] = mapped_column(String(16), primary_key=True)  # nflverse gsis_id
    name: Mapped[str] = mapped_column(String(128))
    position: Mapped[str] = mapped_column(String(8))
    team: Mapped[str] = mapped_column(String(8))
    status: Mapped[str | None] = mapped_column(String(8))


class FeedStatus(Base):
    """Outcome of the latest attempt to refresh one feed for one season."""

    __tablename__ = "feed_status"

    feed: Mapped[str] = mapped_column(String(32), primary_key=True)
    season: Mapped[int] = mapped_column(primary_key=True)
    attempted_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ok_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # last success
    rows: Mapped[int | None]  # rows loaded by the last success
    error: Mapped[str | None] = mapped_column(Text)  # set when the latest attempt failed
