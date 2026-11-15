"""Pool endpoints: the season calendar, pickable players, and admin data controls."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from . import clock, ingest, rules
from .config import settings
from .db import get_db
from .deps import current_entry, current_user, find_entry, require_admin, require_csrf_header
from .models import Entry, FeedStatus, Game, Pick, RosterWeek, User

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


# --- season -----------------------------------------------------------------
class WeekOut(BaseModel):
    week: int
    games: int
    first_kickoff: datetime | None
    last_kickoff: datetime | None


class MyEntryOut(BaseModel):
    entry_id: int
    display_name: str
    status: str  # pending / approved / removed


class SeasonOut(BaseModel):
    season: int
    now: datetime
    entry: MyEntryOut | None  # None: this user has not used an invite link
    current_week: int | None  # None until a schedule is loaded
    weeks: list[WeekOut]


@router.get("/season", response_model=SeasonOut)
def season(
    db: Session = Depends(get_db),
    now: datetime = Depends(clock.now),
    user: User = Depends(current_user),
):
    by_week: dict[int, list[Game]] = {}
    for game in db.scalars(select(Game).where(Game.season == settings.season)):
        by_week.setdefault(game.week, []).append(game)
    out = []
    for week in sorted(by_week):
        kickoffs = [g.kickoff for g in by_week[week] if g.kickoff]
        out.append(
            WeekOut(
                week=week,
                games=len(by_week[week]),
                first_kickoff=min(kickoffs, default=None),
                last_kickoff=max(kickoffs, default=None),
            )
        )
    return SeasonOut(
        season=settings.season,
        now=now,
        entry=my_entry_out(find_entry(db, user)),
        current_week=rules.current_week(db, settings.season, now),
        weeks=out,
    )


def my_entry_out(entry: Entry | None) -> MyEntryOut | None:
    return entry and MyEntryOut(
        entry_id=entry.id, display_name=entry.display_name, status=entry.status
    )


# --- players ----------------------------------------------------------------
class PlayerOut(BaseModel):
    player_id: str
    name: str
    position: str
    team: str
    status: str | None  # roster status: ACT, INA, RES (injured reserve), DEV (practice squad)
    opponent: str
    home: bool
    game_id: str
    kickoff: datetime | None
    lock_at: datetime | None
    locked: bool
    used_week: int | None  # the week I already have this player in, if any


def week_games(db: Session, season: int, week: int) -> dict[str, Game]:
    """Team -> its game that week. Teams on a bye are absent."""
    games = db.scalars(select(Game).where(Game.season == season, Game.week == week)).all()
    if not games:
        raise HTTPException(status_code=404, detail="Unknown week")
    by_team: dict[str, Game] = {}
    for game in games:
        by_team[game.home_team] = game
        by_team[game.away_team] = game
    return by_team


def roster_as_of(db: Session, season: int, week: int) -> list[RosterWeek]:
    """Each team's roster for that week, or its latest earlier one.

    Taken team by team because the weekly feed skips a team in its bye week, and has
    nothing yet for weeks still to come. A player who changed teams since an older
    snapshot is kept only on the team with the newer one.
    """
    latest = (
        select(RosterWeek.team, func.max(RosterWeek.week).label("week"))
        .where(RosterWeek.season == season, RosterWeek.week <= week)
        .group_by(RosterWeek.team)
        .subquery()
    )
    rows = db.scalars(
        select(RosterWeek)
        .join(latest, (RosterWeek.team == latest.c.team) & (RosterWeek.week == latest.c.week))
        .where(RosterWeek.season == season)
        .order_by(RosterWeek.week)
    )
    return list({row.player_id: row for row in rows}.values())


def eligible_players(db: Session, season: int, week: int) -> list[tuple[RosterWeek, Game]]:
    """Every rostered player whose team plays that week, with his game."""
    games = week_games(db, season, week)
    return [(p, games[p.team]) for p in roster_as_of(db, season, week) if p.team in games]


def players_for(
    db: Session, entry: Entry, week: int, slot: str, now: datetime
) -> list[PlayerOut]:
    """Everyone eligible for a slot whose team plays that week, by name."""
    used = dict(
        db.execute(select(Pick.player_id, Pick.week).where(Pick.entry_id == entry.id)).all()
    )
    out = []
    for p, game in eligible_players(db, settings.season, week):
        if p.position not in rules.SLOTS[slot]:
            continue
        home = game.home_team == p.team
        out.append(
            PlayerOut(
                player_id=p.player_id,
                name=p.name,
                position=p.position,
                team=p.team,
                status=p.status,
                opponent=game.away_team if home else game.home_team,
                home=home,
                game_id=game.game_id,
                kickoff=game.kickoff,
                lock_at=rules.lock_at(game),
                locked=rules.is_locked(game, now),
                used_week=used.get(p.player_id),
            )
        )
    return sorted(out, key=lambda p: (p.name, p.player_id))


@router.get("/weeks/{week}/players", response_model=list[PlayerOut])
def players(
    week: int,
    slot: Literal["QB", "RB", "FLEX"],
    db: Session = Depends(get_db),
    now: datetime = Depends(clock.now),
    entry: Entry = Depends(current_entry),
):
    return players_for(db, entry, week, slot, now)


# --- admin ------------------------------------------------------------------
admin = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


class FeedOut(BaseModel):
    feed: str
    season: int
    attempted_at: datetime
    ok_at: datetime | None
    rows: int | None
    error: str | None

    model_config = {"from_attributes": True}


@admin.get("/feeds", response_model=list[FeedOut])
def feeds(db: Session = Depends(get_db)):
    return db.scalars(
        select(FeedStatus).where(FeedStatus.season == settings.season).order_by(FeedStatus.feed)
    ).all()


@admin.post("/refresh", response_model=list[FeedOut], dependencies=[Depends(require_csrf_header)])
async def refresh_now():
    """Reload every feed now. A failed feed keeps its previous data; see `error`."""
    return await run_in_threadpool(ingest.refresh, settings.season)
