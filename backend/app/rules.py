"""The pool's rules as code: slots, locks and the calendar. See docs/DESIGN.md §1."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Game

# Slot -> roster positions eligible for it. nflverse lists fullbacks as RB.
SLOTS: dict[str, tuple[str, ...]] = {"QB": ("QB",), "RB": ("RB",), "FLEX": ("WR", "TE")}

LOCK_BEFORE_KICKOFF = timedelta(minutes=60)
# A week is over this long after its last kickoff.
GAME_LENGTH = timedelta(hours=4)

# Roster statuses that mean the player is no longer with that team.
GONE_STATUSES = {"CUT", "RET", "TRD", "TRC", "TRT"}


def lock_at(game: Game) -> datetime | None:
    """When picks on players in this game lock; None while kickoff is unpublished."""
    return game.kickoff - LOCK_BEFORE_KICKOFF if game.kickoff else None


def is_locked(game: Game, now: datetime) -> bool:
    lock = lock_at(game)
    return lock is not None and now >= lock


def weeks(db: Session, season: int) -> list[int]:
    return list(
        db.scalars(select(Game.week).where(Game.season == season).distinct().order_by(Game.week))
    )


def current_week(db: Session, season: int, now: datetime) -> int | None:
    """First week whose games haven't all finished; the last week once the season is over.

    A week with an unpublished kickoff has not finished. None when no schedule is loaded.
    """
    by_week: dict[int, list[datetime | None]] = {}
    for week, kickoff in db.execute(select(Game.week, Game.kickoff).where(Game.season == season)):
        by_week.setdefault(week, []).append(kickoff)
    for week in sorted(by_week):
        kickoffs = by_week[week]
        if None in kickoffs or max(kickoffs) + GAME_LENGTH > now:
            return week
    return max(by_week, default=None)
