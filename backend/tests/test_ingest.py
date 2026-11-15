from datetime import datetime, timedelta, timezone

import polars as pl
import pytest
from sqlalchemy import func, select

from app import ingest
from app.models import FeedStatus, Game, RosterWeek

UTC = timezone.utc


def schedule_frame(**overrides):
    rows = [
        # A Thursday night game in September (EDT, UTC-4).
        dict(game_id="2026_01_NE_SEA", season=2026, week=1, game_type="REG", gameday="2026-09-10",
             gametime="20:20", home_team="SEA", away_team="NE", home_score=13, away_score=10),
        # A Sunday 1pm game after the clocks go back (EST, UTC-5), not yet played.
        dict(game_id="2026_10_BUF_MIA", season=2026, week=10, game_type="REG", gameday="2026-11-15",
             gametime="13:00", home_team="MIA", away_team="BUF", home_score=None, away_score=None),
        # Time not announced yet.
        dict(game_id="2026_18_DAL_NYG", season=2026, week=18, game_type="REG", gameday="2027-01-10",
             gametime=None, home_team="NYG", away_team="DAL", home_score=None, away_score=None),
        # Not ours: a playoff game and another season.
        dict(game_id="2026_19_X_Y", season=2026, week=19, game_type="WC", gameday="2027-01-16",
             gametime="13:00", home_team="KC", away_team="BUF", home_score=None, away_score=None),
        dict(game_id="2025_01_A_B", season=2025, week=1, game_type="REG", gameday="2025-09-07",
             gametime="13:00", home_team="KC", away_team="BUF", home_score=1, away_score=2),
    ]
    return pl.DataFrame(rows, schema_overrides={"home_score": pl.Int32, "away_score": pl.Int32})


def roster_frame():
    def row(week, pid, name, pos, team, status, game_type="REG"):
        return dict(season=2026, week=week, game_type=game_type, gsis_id=pid, full_name=name,
                    position=pos, team=team, status=status)

    return pl.DataFrame([
        row(1, "00-1", "Quinn Back", "QB", "SEA", "ACT"),
        row(1, "00-2", "Lenny Lineman", "OL", "SEA", "ACT"),      # not a pool position
        row(1, None, "No Id", "WR", "SEA", "ACT"),                # unusable without an id
        row(1, "00-3", "Rex Runner", "RB", "NE", "CUT"),          # gone
        row(2, "00-4", "Wes Wideout", "WR", "NE", "TRD"),         # traded away from NE...
        row(2, "00-4", "Wes Wideout", "WR", "MIA", "ACT"),        # ...to MIA
        row(2, "00-5", "Tate End", "TE", "BUF", "RES"),
        row(2, "00-5", "Tate End", "TE", "BUF", "ACT"),           # active row wins
        row(19, "00-1", "Quinn Back", "QB", "SEA", "ACT", "WC"),  # playoffs
    ])


def test_kickoff_is_converted_from_eastern_to_utc():
    games = {g["game_id"]: g for g in ingest.transform_schedule(schedule_frame(), 2026)}
    assert set(games) == {"2026_01_NE_SEA", "2026_10_BUF_MIA", "2026_18_DAL_NYG"}
    assert games["2026_01_NE_SEA"]["kickoff"] == datetime(2026, 9, 11, 0, 20, tzinfo=UTC)
    assert games["2026_10_BUF_MIA"]["kickoff"] == datetime(2026, 11, 15, 18, 0, tzinfo=UTC)
    assert games["2026_18_DAL_NYG"]["kickoff"] is None
    assert games["2026_01_NE_SEA"]["home_score"] == 13
    assert games["2026_10_BUF_MIA"]["home_score"] is None


def test_rosters_keep_pool_positions_on_current_team():
    rows = {(r["week"], r["player_id"]): r for r in ingest.transform_rosters(roster_frame(), 2026)}
    assert set(rows) == {(1, "00-1"), (2, "00-4"), (2, "00-5")}
    assert rows[(2, "00-4")]["team"] == "MIA"
    assert rows[(2, "00-5")]["status"] == "ACT"


def test_season_roster_without_weeks_loads_as_week_one():
    raw = roster_frame().drop("week", "game_type").unique(subset=["gsis_id"], keep="first")
    assert {r["week"] for r in ingest.transform_rosters(raw, 2026)} == {1}


@pytest.fixture()
def feeds(monkeypatch):
    """Serve frames instead of the network; set a path to an Exception to fail it."""
    files = {
        "schedules/games": schedule_frame(),
        "weekly_rosters/roster_weekly_2026": roster_frame(),
    }

    def fake_download(path):
        value = files.get(path)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(ingest, "download", fake_download)
    return files


def counts(db):
    db.expire_all()
    return (
        db.scalar(select(func.count()).select_from(Game)),
        db.scalar(select(func.count()).select_from(RosterWeek)),
    )


def test_refresh_loads_both_feeds(db, feeds):
    statuses = {s.feed: s for s in ingest.refresh(2026)}
    assert counts(db) == (3, 3)
    assert statuses["schedule"].rows == 3 and statuses["schedule"].error is None
    assert statuses["rosters"].rows == 3 and statuses["rosters"].ok_at is not None
    assert db.get(Game, "2026_01_NE_SEA").kickoff == datetime(2026, 9, 11, 0, 20, tzinfo=UTC)


def test_failed_feed_keeps_previous_data_and_records_why(db, feeds):
    ingest.refresh(2026)
    feeds["schedules/games"] = ConnectionError("boom")
    feeds["weekly_rosters/roster_weekly_2026"] = roster_frame().head(1)

    statuses = {s.feed: s for s in ingest.refresh(2026)}
    assert counts(db) == (3, 1)  # schedule untouched; rosters replaced independently
    assert "boom" in statuses["schedule"].error
    assert statuses["schedule"].rows == 3 and statuses["schedule"].ok_at is not None
    assert statuses["rosters"].error is None


def test_unpublished_or_empty_feed_is_a_failure_not_a_wipe(db, feeds):
    ingest.refresh(2026)
    feeds["weekly_rosters/roster_weekly_2026"] = None  # 404, and no season roster either
    feeds["schedules/games"] = schedule_frame().filter(pl.col("season") == 1999)

    statuses = {s.feed: s for s in ingest.refresh(2026)}
    assert counts(db) == (3, 3)
    assert "not published" in statuses["rosters"].error
    assert "no rows" in statuses["schedule"].error


def test_rosters_fall_back_to_season_roster_before_week_one(db, feeds):
    feeds["weekly_rosters/roster_weekly_2026"] = None
    feeds["rosters/roster_2026"] = roster_frame().drop("week", "game_type").head(1)
    ingest.refresh(2026)
    assert db.scalars(select(RosterWeek.week)).all() == [1]


def test_schedule_refresh_updates_and_removes_games(db, feeds):
    ingest.refresh(2026)
    feeds["schedules/games"] = schedule_frame().filter(
        pl.col("game_id") != "2026_18_DAL_NYG"
    ).with_columns(
        pl.when(pl.col("game_id") == "2026_10_BUF_MIA").then(pl.lit("16:25"))
        .otherwise(pl.col("gametime")).alias("gametime")
    )
    ingest.refresh(2026)
    db.expire_all()
    assert db.get(Game, "2026_18_DAL_NYG") is None
    assert db.get(Game, "2026_10_BUF_MIA").kickoff == datetime(2026, 11, 15, 21, 25, tzinfo=UTC)


def test_only_due_feeds_are_reloaded():
    now = datetime(2026, 11, 14, 12, tzinfo=UTC)
    fresh = FeedStatus(feed="schedule", season=2026, attempted_at=now, ok_at=now)
    assert ingest.is_due(None, "schedule", now)
    assert not ingest.is_due(fresh, "schedule", now + timedelta(minutes=59))
    assert ingest.is_due(fresh, "schedule", now + timedelta(hours=1))
    assert not ingest.is_due(fresh, "rosters", now + timedelta(hours=23))
    failed = FeedStatus(feed="schedule", season=2026, attempted_at=now, ok_at=now, error="x")
    assert not ingest.is_due(failed, "schedule", now + timedelta(minutes=9))
    assert ingest.is_due(failed, "schedule", now + timedelta(minutes=10))
