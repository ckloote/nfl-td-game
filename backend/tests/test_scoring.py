"""The scoring rule, with the selector's test cases carried over.

Source: ../nfl-player-selector/tests/test_workflow.py and tests/support/local.py.
"""

from datetime import datetime, timezone

import polars as pl
import pytest
from sqlalchemy import func, select

from app import ingest, scoring
from app.models import Game, GameResult, Pick, TouchdownCredit

SCHEDULE = {"g1": (28, 7), "g2": (0, 0)}


def play(gid="g1", pid="r1", play_id=1, **kw):
    row = dict(
        game_id=gid, play_id=play_id, touchdown=1, pass_touchdown=0, td_player_id=pid,
        passer_player_id=None, two_point_attempt=0, extra_point_attempt=0, play_type="run",
        desc="TOUCHDOWN", total_home_score=28, total_away_score=7, td_team="A",
        td_player_name=pid, posteam="A",
    )
    return row | kw


def end(gid="g1", home=28, away=7, **kw):
    return play(gid, None, 999, touchdown=0, desc="END GAME", play_type=None,
                total_home_score=home, total_away_score=away) | kw


def totals(credits):
    out = {}
    for c in credits:
        out[c["player_id"]] = out.get(c["player_id"], 0) + 1
    return out


def test_all_touchdown_kinds_deduplicate_ignore_conversions_and_negation():
    rows = [
        play(pid="receiver", pass_touchdown=1, passer_player_id="q1", play_type="pass"),
        play(pid="rusher", play_id=2),
        play(pid="kickreturn", play_id=3, play_type="kickoff", special_teams_tds=1),
        play(pid="puntreturn", play_id=4, play_type="punt"),
        play(pid="offrecover", play_id=5, fumble_recovery_1_player_id="offrecover"),
        play(pid="defrecover", play_id=6, return_touchdown=1, td_team="B"),
        # A lateral: the scorer is td_player_id, not the receiver of the pass.
        play(pid="lateral", play_id=7, receiver_player_id="wrong_receiver", pass_touchdown=1,
             passer_player_id="q1", play_type="pass"),
        play(pid="conversion", play_id=8, two_point_attempt=1, pass_touchdown=1,
             passer_player_id="q1"),
        play(pid="pat", play_id=9, extra_point_attempt=1),
        play(pid="negated", play_id=10, play_type="no_play"),
        play(pid="negated2", play_id=11, no_play=1),
        end(),
    ]
    rows = [{"no_play": 0, **r} for r in rows]
    rows.append(rows[2].copy())  # an exact duplicate row is not a conflict
    credits, results = scoring.transform_touchdowns(rows, SCHEDULE)
    assert len(credits) == 9  # seven scorers + two throwing credits
    assert totals(credits) == dict(
        q1=2, receiver=1, rusher=1, kickreturn=1, puntreturn=1, offrecover=1, defrecover=1,
        lateral=1,
    )
    assert results == [
        dict(game_id="g1", complete=True, reason="complete", home_score=28, away_score=7)
    ]


@pytest.mark.parametrize(
    "rows, reason",
    [
        ([play()], "end-of-game"),
        ([play(), end(home=27)], "terminal scores"),
        ([play(pid=None), end()], "identities unresolved"),
        ([play(pass_touchdown=1), end()], "identities unresolved"),  # passer missing
        ([play(), play(pid="other"), end()], "conflicting duplicate"),
    ],
)
def test_incomplete_game_is_not_complete(rows, reason):
    _, results = scoring.transform_touchdowns(rows, SCHEDULE)
    assert results[0]["complete"] is False and reason in results[0]["reason"]


def test_final_marker_is_authoritative_over_late_inserted_play_id():
    timeout = play(play_id=1001, touchdown=0, play_type="no_play", desc="Timeout #3",
                   total_home_score=7)
    credits, results = scoring.transform_touchdowns([timeout, play(), end()], SCHEDULE)
    assert results[0]["complete"] and len(credits) == 1


def test_games_outside_the_schedule_and_float_columns():
    rows = [play(gid="playoff"), end(gid="playoff"),
            play(touchdown=1.0, play_id=1.0, total_home_score=28.0), end()]
    credits, results = scoring.transform_touchdowns(rows, SCHEDULE)
    assert [r["game_id"] for r in results] == ["g1"] and totals(credits) == {"r1": 1}


def test_bad_input_is_rejected_rather_than_scored():
    with pytest.raises(ValueError, match="missing required columns"):
        scoring.transform_touchdowns([{"game_id": "g1", "play_id": 1}], SCHEDULE)
    with pytest.raises(ValueError, match="invalid touchdown"):
        scoring.transform_touchdowns([play(touchdown=2)], SCHEDULE)
    with pytest.raises(ValueError, match="unresolved game/play"):
        scoring.transform_touchdowns([play(play_id=None)], SCHEDULE)


# --- through the database ------------------------------------------------------
@pytest.fixture()
def games(db):
    kickoff = datetime(2026, 9, 10, 17, tzinfo=timezone.utc)
    db.add_all([
        Game(game_id="g1", season=2026, week=1, home_team="A", away_team="B",
             gameday="2026-09-10", kickoff=kickoff, home_score=28, away_score=7),
        Game(game_id="g2", season=2026, week=1, home_team="C", away_team="D",
             gameday="2026-09-13", kickoff=kickoff, home_score=0, away_score=0),
        Game(game_id="g3", season=2026, week=2, home_team="A", away_team="B",
             gameday="2026-09-20", kickoff=None),
    ])
    db.commit()


def pick(player_id, game_id="g1", week=1):
    return Pick(entry_id=1, week=week, slot="RB", player_id=player_id, player_name=player_id,
                position="RB", team="A", game_id=game_id)


def load(db, rows):
    ingest.write_touchdowns(db, 2026, rows)
    db.commit()
    return scoring.load_board(db, 2026)


def test_final_zero_is_a_score_and_incomplete_is_pending(db, games):
    board = load(db, [play(), play(pid="q1", play_id=2), play(pid="r1", play_id=3), end(),
                      end("g2", 0, 0, desc="in progress")])
    assert scoring.score_pick(board, pick("r1")) == (2, None)
    assert scoring.score_pick(board, pick("nobody")) == (0, None)   # played or not: zero
    assert scoring.score_pick(board, pick("x", "g2")) == (None, "no end-of-game marker")
    assert scoring.score_pick(board, pick("x", "g3", 2)) == (None, "not final yet")
    assert not board.week_is_final(1) and board.final_through() == 0

    board = load(db, [play(), end(), end("g2", 0, 0)])
    assert scoring.score_pick(board, pick("x", "g2")) == (0, None)
    assert board.week_is_final(1) and board.final_through() == 1


def test_a_correction_shows_on_the_next_load_and_removed_games_go_pending(db, games):
    assert scoring.score_pick(load(db, [play(), end()]), pick("r1")) == (1, None)
    assert scoring.score_pick(load(db, [play(), play(play_id=2), end()]), pick("r1")) == (2, None)
    board = load(db, [end("g2", 0, 0)])  # g1 dropped out of the feed
    assert scoring.score_pick(board, pick("r1")) == (None, "not final yet")
    assert db.scalar(select(func.count()).select_from(TouchdownCredit)) == 0


def test_a_schedule_correction_unfinalizes_old_coverage(db, games):
    load(db, [play(), end()])
    db.get(Game, "g1").home_score = 31
    db.commit()
    board = scoring.load_board(db, 2026)
    assert scoring.score_pick(board, pick("r1")) == (None, "terminal scores do not match schedule")


def test_a_player_is_scored_where_he_actually_played(db, games):
    """Picked with team A (g1), then traded and scored for team C in g2."""
    board = load(db, [end(), play("g2", "traded", total_home_score=0, total_away_score=0),
                      end("g2", 0, 0, desc="in progress")])
    assert scoring.score_pick(board, pick("traded", "g1")) == (None, "no end-of-game marker")


def test_touchdowns_need_a_schedule_and_matching_games(db):
    with pytest.raises(ValueError, match="schedule"):
        ingest.write_touchdowns(db, 2026, [play(), end()])


def test_touchdown_feed_loads_and_failure_keeps_previous_credits(db, games, monkeypatch):
    frames = {"pbp/play_by_play_2026": pl.DataFrame([play(), end()], infer_schema_length=None)}
    monkeypatch.setattr(ingest, "download", lambda path: frames.get(path))
    status = ingest.refresh_feed(db, "touchdowns", 2026)
    assert status.error is None and status.rows == 1
    assert db.get(GameResult, "g1").complete

    frames["pbp/play_by_play_2026"] = pl.DataFrame([play(gid="other"), end(gid="other")],
                                                   infer_schema_length=None)
    status = ingest.refresh_feed(db, "touchdowns", 2026)
    assert "no matching" in status.error and status.rows == 1
    assert db.scalar(select(func.count()).select_from(TouchdownCredit)) == 1


def test_touchdowns_reload_hourly_only_while_a_recent_game_awaits_its_final(db, games):
    now = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)
    assert ingest.awaiting_finals(db, 2026, now)            # g1 and g2 kicked off, no results
    load(db, [play(), end(), end("g2", 0, 0)])
    assert not ingest.awaiting_finals(db, 2026, now)
    assert not ingest.awaiting_finals(db, 2026, datetime(2026, 9, 9, tzinfo=timezone.utc))

    from datetime import timedelta

    from app.models import FeedStatus
    fresh = FeedStatus(feed="touchdowns", season=2026, attempted_at=now, ok_at=now)
    later = now + timedelta(hours=2)
    assert ingest.is_due(fresh, "touchdowns", later, awaiting=True)
    assert not ingest.is_due(fresh, "touchdowns", later, awaiting=False)
