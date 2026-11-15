"""The 2026 replay: reading reports, entering picks, comparing with the selector."""

from datetime import datetime, timezone

import pytest

from app import replay
from app.models import Game, GameResult, Pick, TouchdownCredit
from app.replay import ReportPick, Scored
from app.standings import compute_standings

AFTER_WEEK_1 = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)

WIDE = "week,entrant,QB,RB,FLEX\n1,Ada,Sam Seattle,Ned England,Mia Wideout\n1,Bo B.,Bo Buffalo,,al tightend\n"
LONG = "entrant,slot,player_name\nAda,QB,Sam Seattle\nAda,RB,Ned England\nAda,WR,Mia Wideout\n"


# --- reading ------------------------------------------------------------------
def test_wide_and_long_layouts_read_the_same():
    wide = [p for p in replay.parse_report(WIDE) if p.entrant == "Ada"]
    assert wide == replay.parse_report(LONG, week=1)
    assert wide[2] == ReportPick(1, "Ada", "FLEX", "Mia Wideout")


def test_an_empty_cell_is_a_no_pick():
    picks = {(p.entrant, p.slot): p.player_name for p in replay.parse_report(WIDE)}
    assert picks[("Bo B.", "RB")] is None


@pytest.mark.parametrize(
    "text, week, message",
    [
        (LONG, None, "no week column"),
        (WIDE, 2, "named for week 2"),
        ("entrant,slot,player_name\nAda,QB,Sam Seattle\n", 1, "missing slots"),
        (LONG + "Ada,TE,Al Tightend\n", 1, "FLEX appears twice"),
        ("week,entrant,QB,RB\n1,Ada,a,b\n", None, "exactly one column"),
        ("week,entrant,QB,RB,FLEX\n1,Ada,a,b\n", None, "expected 5 fields"),
    ],
)
def test_malformed_reports_are_refused(text, week, message):
    with pytest.raises(ValueError, match=message):
        replay.parse_report(text, week)


def test_reports_are_read_in_week_order_and_other_files_ignored(tmp_path):
    (tmp_path / "week10.csv").write_text(WIDE.replace("\n1,", "\n10,"))
    (tmp_path / "week2.csv").write_text(WIDE.replace("\n1,", "\n2,"))
    (tmp_path / "week2.csv~").write_text("junk")
    assert [p.week for p in replay.read_reports(tmp_path)][::6] == [2, 10]


# --- entering -----------------------------------------------------------------
def test_picks_are_entered_for_placeholder_entrants(db, season):
    imported = replay.import_reports(db, replay.parse_report(WIDE), AFTER_WEEK_1)
    assert not imported.problems
    assert (imported.picks, imported.no_picks) == (5, 1)
    assert sorted(e.display_name for e in imported.entries.values()) == ["Ada", "Bo B."]
    bo = imported.entries["bo b"]
    assert {p.slot: p.player_id for p in db.query(Pick).filter_by(entry_id=bo.id)} == {
        "QB": "q2", "FLEX": "t1",  # matched ignoring case
    }


@pytest.mark.parametrize(
    "name, slot, message",
    [
        ("Nobody Atall", "QB", "matches no player"),
        ("Kip Kansas", "QB", "matches no player"),  # KC has a bye in week 1
    ],
)
def test_a_name_that_does_not_resolve_is_a_problem_not_a_guess(db, season, name, slot, message):
    imported = replay.import_reports(db, [ReportPick(1, "Ada", slot, name)], AFTER_WEEK_1)
    assert imported.picks == 0
    assert len(imported.problems) == 1 and message in imported.problems[0]
    assert imported.problems[0].startswith(f"week 1 Ada {slot}:")


def test_a_player_named_in_the_wrong_slot_scores_zero_without_being_entered(db, season):
    reported = [ReportPick(1, "Ada", "RB", "Mia Wideout")]
    imported = replay.import_reports(db, reported, AFTER_WEEK_1)
    assert not imported.problems and imported.picks == 0 and db.query(Pick).count() == 0
    assert imported.misplaced[("ada", 1, "RB")] == ("w1", "week 1 Ada RB: Mia Wideout is a WR (MIA)")
    # Zero at once, though his game has no result yet.
    assert replay.app_scores(db, imported, reported, AFTER_WEEK_1) == [
        Scored("ada", 1, "RB", "w1", 0, "misplaced")
    ]


def test_a_misplaced_player_is_spent(db, season):
    wrong, right = ReportPick(1, "Ada", "QB", "Al Tightend"), ReportPick(2, "Ada", "FLEX", "Al Tightend")
    after = replay.import_reports(db, [wrong, right], AFTER_WEEK_1)
    assert "spent by a misplaced pick in week 1" in after.problems[0]
    replay.reset_pool(db)
    before = replay.import_reports(db, [right, wrong], AFTER_WEEK_1)
    assert "already used in week 2" in before.problems[0] and not before.misplaced


def test_a_player_reported_twice_is_a_problem(db, season):
    picks = [ReportPick(1, "Ada", "QB", "Sam Seattle"), ReportPick(2, "Ada", "QB", "Sam Seattle")]
    imported = replay.import_reports(db, picks, AFTER_WEEK_1)
    assert imported.picks == 1
    assert "already used in week 1" in imported.problems[0]


def test_reset_pool_removes_people_but_not_nfl_data(db, season):
    replay.import_reports(db, replay.parse_report(WIDE), AFTER_WEEK_1)
    replay.reset_pool(db)
    assert db.query(Pick).count() == 0
    assert not replay.import_reports(db, replay.parse_report(WIDE), AFTER_WEEK_1).problems


# --- scoring and comparing ----------------------------------------------------
def final(db, game_id, **tds):
    game = db.get(Game, game_id)
    game.home_score = game.away_score = 0
    db.add(GameResult(game_id=game_id, season=2026, complete=True, reason="complete",
                      home_score=0, away_score=0))
    for n, (player_id, count) in enumerate(tds.items()):
        for i in range(count):
            db.add(TouchdownCredit(game_id=game_id, play_id=n * 10 + i, player_id=player_id,
                                   kind="scoring", season=2026))
    db.commit()


def test_scores_and_standings_come_from_the_apps_own_code(db, season):
    reported = replay.parse_report(WIDE)
    imported = replay.import_reports(db, reported, AFTER_WEEK_1)
    final(db, "w1_thu", q1=2, t1=1)

    scores = {(s.entrant, s.slot): s for s in replay.app_scores(db, imported, reported, AFTER_WEEK_1)}
    assert scores[("ada", "QB")] == Scored("ada", 1, "QB", "q1", 2)
    assert scores[("ada", "RB")].tds == 0  # final game, no touchdowns
    assert scores[("ada", "FLEX")].tds is None  # w1_sun has no result yet
    assert scores[("bo b", "RB")] == Scored("bo b", 1, "RB", None, 0)  # no-pick

    table = replay.standings_table(compute_standings(db, AFTER_WEEK_1))
    assert table.splitlines()[1].split()[:3] == ["1", "Ada", "2"]
    assert "(1 pending)" in table


def test_compare_reports_every_kind_of_difference():
    ours = [
        Scored("ada", 1, "QB", "q1", 2),
        Scored("ada", 1, "RB", "r1", 1),
        Scored("ada", 1, "FLEX", None, None, "not entered"),
        Scored("bo", 1, "QB", "q2", None, "not final yet"),
        Scored("bo", 2, "QB", "q3", 0),
    ]
    theirs = [
        Scored("ada", 1, "QB", "q1", 2),
        Scored("ada", 1, "RB", "r1", 0),
        Scored("ada", 1, "FLEX", "w1", 0, "misplaced"),
        Scored("bo", 1, "QB", "q2", 3),
        Scored("cy", 1, "QB", "q9", 1),
    ]
    assert replay.compare(ours, ours) == []
    assert replay.compare(ours, theirs) == [
        "week 1 ada FLEX: app has player None, selector has w1 (not entered) (misplaced)",
        "week 1 ada RB: app scores 1 TD, selector scores 0 TD",
        "week 1 bo QB: app scores pending (not final yet), selector scores 3 TD",
        "week 1 cy QB: in the selector but not in the reports replayed",
        "week 2 bo QB: not in the selector; import that report there",
    ]
