"""Pull nflverse data into the database.

`download` talks to the network. The `transform_*` functions are pure and unit-tested.
`refresh` wires them together one feed at a time: a feed that fails to download or parse
leaves the data it replaced untouched and records why in `feed_status`.

Run by hand with:  python -m app.ingest [--season 2026]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import polars as pl
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from . import scoring
from .config import settings
from .db import SessionLocal, upgrade_db
from .models import FeedStatus, Game, GameResult, RosterWeek, TouchdownCredit
from .rules import GONE_STATUSES, SLOTS

log = logging.getLogger(__name__)

EASTERN = ZoneInfo("America/New_York")  # nflverse gameday/gametime are US Eastern
POSITIONS = {p for positions in SLOTS.values() for p in positions}
# How stale a feed may get before the timer reloads it, and how soon to retry a failure.
MAX_AGE = {
    "schedule": timedelta(hours=1),
    "rosters": timedelta(hours=24),
    "touchdowns": timedelta(hours=24),
}
# Touchdowns are reloaded this often while a recent game is still waiting for its final.
TOUCHDOWNS_AWAITING = timedelta(hours=1)
RECENT_GAME = timedelta(days=4)
RETRY_AFTER = timedelta(minutes=10)
CHECK_EVERY_SECONDS = 300

_refreshing = threading.Lock()


# --- fetch ------------------------------------------------------------------
def download(path: str) -> pl.DataFrame | None:
    """One nflverse-data release asset, uncached; None when it isn't published (404)."""
    from nflreadpy.config import CacheMode, get_config, update_config
    from nflreadpy.downloader import get_downloader

    previous = get_config().cache_mode
    update_config(cache_mode=CacheMode.OFF)
    try:
        return get_downloader().download("nflverse-data", path)
    except Exception as exc:  # nflreadpy wraps HTTP errors in ConnectionError
        if "404" in str(exc):
            return None
        raise
    finally:
        update_config(cache_mode=previous)


# --- transform --------------------------------------------------------------
def kickoff_utc(gameday: str, gametime: str | None) -> datetime | None:
    """Eastern wall-clock date and time to a UTC instant; None while the time is TBD."""
    if not gametime or not re.fullmatch(r"\d{2}:\d{2}", gametime):
        return None
    local = datetime.fromisoformat(f"{gameday}T{gametime}").replace(tzinfo=EASTERN)
    return local.astimezone(timezone.utc)


def _int(value) -> int | None:
    return None if value is None else int(value)


def transform_schedule(raw: pl.DataFrame, season: int) -> list[dict]:
    games = raw.filter((pl.col("season") == season) & (pl.col("game_type") == "REG"))
    return [
        dict(
            game_id=g["game_id"],
            season=season,
            week=int(g["week"]),
            home_team=g["home_team"],
            away_team=g["away_team"],
            gameday=g["gameday"],
            kickoff=kickoff_utc(g["gameday"], g["gametime"]),
            home_score=_int(g["home_score"]),
            away_score=_int(g["away_score"]),
        )
        for g in games.to_dicts()
    ]


def transform_rosters(raw: pl.DataFrame, season: int) -> list[dict]:
    """One row per player per week, at pool positions, on the team he is actually with.

    A player traded or cut mid-week appears once per team; rows that say he has left are
    dropped, and among the rest an active row wins.
    """
    rows = raw.filter(
        (pl.col("season") == season)
        & pl.col("position").is_in(sorted(POSITIONS))
        & pl.col("gsis_id").is_not_null()
        & pl.col("team").is_not_null()
    )
    if "game_type" in rows.columns:
        rows = rows.filter(pl.col("game_type").fill_null("REG") == "REG")
    best: dict[tuple[int, str], dict] = {}
    for r in rows.to_dicts():
        if r["status"] in GONE_STATUSES:
            continue
        week = int(r["week"]) if r.get("week") is not None else 1  # season roster has no week
        key = (week, r["gsis_id"])
        if key in best and (best[key]["status"] == "ACT" or r["status"] != "ACT"):
            continue
        best[key] = dict(
            season=season,
            week=week,
            player_id=r["gsis_id"],
            name=r["full_name"],
            position=r["position"],
            team=r["team"],
            status=r["status"],
        )
    return list(best.values())


# --- load -------------------------------------------------------------------
def load_schedule(season: int) -> list[dict]:
    raw = download("schedules/games")
    if raw is None:
        raise FileNotFoundError("schedule is not published")
    return transform_schedule(raw, season)


def load_rosters(season: int) -> list[dict]:
    raw = download(f"weekly_rosters/roster_weekly_{season}")
    if raw is None:  # before week 1 only the season roster exists
        raw = download(f"rosters/roster_{season}")
    if raw is None:
        raise FileNotFoundError(f"{season} rosters are not published yet")
    return transform_rosters(raw, season)


def load_touchdowns(season: int) -> list[dict]:
    raw = download(f"pbp/play_by_play_{season}")
    if raw is None:
        raise FileNotFoundError(f"{season} play-by-play is not published yet")
    wanted = scoring.PBP_REQUIRED | scoring.PBP_OPTIONAL
    return raw.select([c for c in raw.columns if c in wanted]).to_dicts()


def write_schedule(db: Session, season: int, rows: list[dict]) -> None:
    # Upsert rather than replace: picks will point at games.
    keep = {r["game_id"] for r in rows}
    for row in rows:
        db.merge(Game(**row))
    for game in db.scalars(select(Game).where(Game.season == season)):
        if game.game_id not in keep:
            db.delete(game)


def write_rosters(db: Session, season: int, rows: list[dict]) -> None:
    db.execute(delete(RosterWeek).where(RosterWeek.season == season))
    db.execute(insert(RosterWeek), rows)


def write_touchdowns(db: Session, season: int, plays: list[dict]) -> int:
    """Replace the season's credits and results; a game no longer in the feed goes pending."""
    schedule = {
        g.game_id: (g.home_score, g.away_score)
        for g in db.scalars(select(Game).where(Game.season == season))
    }
    if not schedule:
        raise ValueError(f"no {season} schedule loaded; touchdowns need it first")
    credits, results = scoring.transform_touchdowns(plays, schedule)
    if not results:
        raise ValueError("play-by-play has no matching regular-season games")
    db.execute(delete(TouchdownCredit).where(TouchdownCredit.season == season))
    db.execute(delete(GameResult).where(GameResult.season == season))
    if credits:
        db.execute(insert(TouchdownCredit), [c | {"season": season} for c in credits])
    db.execute(insert(GameResult), [r | {"season": season} for r in results])
    return len(credits)


# feed -> (load from the network, write to the database). Order matters: touchdowns are
# checked against the schedule's final scores, so the schedule loads first.
FEEDS: dict[str, tuple[Callable[[int], list[dict]], Callable[[Session, int, list[dict]], int | None]]]
FEEDS = {
    "schedule": (load_schedule, write_schedule),
    "rosters": (load_rosters, write_rosters),
    "touchdowns": (load_touchdowns, write_touchdowns),
}


# --- refresh ----------------------------------------------------------------
def _utcnow() -> datetime:
    # Feed freshness is about the real world, so this ignores the DEV_NOW clock.
    return datetime.now(timezone.utc)


def refresh_feed(db: Session, feed: str, season: int) -> FeedStatus:
    """Reload one feed. On any failure the previous data stays and the error is recorded."""
    load, write = FEEDS[feed]
    started = _utcnow()
    error = rows = None
    try:
        data = load(season)
        if not data:
            raise ValueError("feed returned no rows")
        written = write(db, season, data)
        db.flush()
        rows = len(data) if written is None else written
    except Exception as exc:
        db.rollback()
        error = f"{type(exc).__name__}: {exc}"
        log.warning("refresh %s %s failed: %s; previous data kept", feed, season, error)
    status = db.get(FeedStatus, (feed, season)) or FeedStatus(feed=feed, season=season)
    status.attempted_at = started
    status.error = error
    if error is None:
        status.ok_at, status.rows = started, rows
    db.add(status)
    db.commit()
    return status


def awaiting_finals(db: Session, season: int, now: datetime) -> bool:
    """True while a game that kicked off in the last few days has no trusted final."""
    recent = db.scalars(
        select(Game.game_id).where(
            Game.season == season, Game.kickoff <= now, Game.kickoff >= now - RECENT_GAME
        )
    ).all()
    pending = scoring.load_board(db, season).pending
    return any(game_id in pending for game_id in recent)


def is_due(
    status: FeedStatus | None, feed: str, now: datetime, *, awaiting: bool = False
) -> bool:
    if status is None:
        return True
    if status.error:
        return now - status.attempted_at >= RETRY_AFTER
    max_age = TOUCHDOWNS_AWAITING if feed == "touchdowns" and awaiting else MAX_AGE[feed]
    return status.ok_at is None or now - status.ok_at >= max_age


def refresh(season: int, *, only_due: bool = False) -> list[FeedStatus]:
    """Reload every feed (or only the stale ones). Returns the status of each feed.

    If another refresh is already running, this one does nothing and reports the
    statuses as they stand.
    """
    with SessionLocal() as db:
        if _refreshing.acquire(blocking=False):
            try:
                for feed in FEEDS:
                    status = db.get(FeedStatus, (feed, season))
                    now = _utcnow()
                    awaiting = feed == "touchdowns" and awaiting_finals(db, season, now)
                    if not only_due or is_due(status, feed, now, awaiting=awaiting):
                        refresh_feed(db, feed, season)
            finally:
                _refreshing.release()
        return list(
            db.scalars(select(FeedStatus).where(FeedStatus.season == season).order_by(FeedStatus.feed))
        )


async def refresh_loop() -> None:
    """Keep the data fresh while the server runs. Started from the app's lifespan."""
    while True:
        try:
            await asyncio.to_thread(refresh, settings.season, only_due=True)
        except Exception:
            log.exception("scheduled refresh failed")
        await asyncio.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load NFL schedule, rosters and touchdowns.")
    parser.add_argument("--season", type=int, default=settings.season)
    args = parser.parse_args()
    upgrade_db()
    failed = False
    for s in refresh(args.season):
        print(f"{s.feed} {s.season}: " + (f"FAILED: {s.error}" if s.error else f"{s.rows} rows"))
        failed |= bool(s.error)
    raise SystemExit(1 if failed else 0)
