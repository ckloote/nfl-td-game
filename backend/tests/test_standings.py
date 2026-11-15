"""Standings, a week's picks and the entrant page: scores, ranks, and who sees what.

Week 1: NE@SEA locks Thu 2026-09-10 23:20Z; BUF@MIA locks Sun 2026-09-13 16:00Z.
"""

import pytest

from app.models import Game, GameResult, TouchdownCredit

CSRF = {"X-Requested-With": "fetch"}
EARLY = "2026-09-09T12:00:00+00:00"
THURSDAY_LOCK = "2026-09-10T23:20:00+00:00"
SUNDAY_LOCK = "2026-09-13T16:00:00+00:00"
LATER = "2026-09-15T12:00:00+00:00"


@pytest.fixture()
def pool(client, login, at, season, db):
    class Pool:
        def as_(self, name):
            login(f"{name}@example.com")
            return self

        def pick(self, week, slot, player_id):
            r = client.put(f"/api/weeks/{week}/picks/{slot}", json={"player_id": player_id},
                           headers=CSRF)
            assert r.status_code == 200, r.text

        def final(self, game_id, home, away, **tds):
            """Mark a game final with touchdowns per player, e.g. q1=2."""
            game = db.get(Game, game_id)
            game.home_score, game.away_score = home, away
            db.merge(GameResult(game_id=game_id, season=2026, complete=True, reason="complete",
                                home_score=home, away_score=away))
            play = 0
            for player_id, count in tds.items():
                for _ in range(count):
                    play += 1
                    db.add(TouchdownCredit(game_id=game_id, play_id=play, player_id=player_id,
                                           kind="scoring", season=2026))
            db.commit()

        def week(self, week=1):
            body = client.get(f"/api/weeks/{week}/picks").json()
            return {
                e["name"]: [s["pick"]["name"] if s["pick"] else s["state"] for s in e["slots"]]
                for e in body["entries"]
            }

        def standings(self):
            return client.get("/api/standings").json()

        def entry_id(self, name):
            return next(s["entry_id"] for s in self.standings()["standings"] if s["name"] == name)

    at(EARLY)
    return Pool()


# --- visibility --------------------------------------------------------------
def test_other_entrants_see_a_pick_only_once_it_has_locked(pool, at, client):
    pool.as_("ada")
    pool.pick(1, "QB", "q1")     # Thursday
    pool.pick(1, "FLEX", "w1")   # Sunday
    pool.as_("grace")
    ada = pool.entry_id("ada")

    # Before any lock: nothing of ada's, and no way to tell which slots she has filled.
    assert pool.week()["ada"] == ["hidden", "hidden", "hidden"]
    assert client.get(f"/api/entries/{ada}").json()["picks"] == []
    assert pool.standings()["standings"][0]["used"] == 0

    at(THURSDAY_LOCK)
    assert pool.week()["ada"] == ["Sam Seattle", "hidden", "hidden"]
    assert [p["name"] for p in client.get(f"/api/entries/{ada}").json()["picks"]] == ["Sam Seattle"]

    at(SUNDAY_LOCK)  # the week has locked: an unfilled slot is now known to be empty
    assert pool.week()["ada"] == ["Sam Seattle", "empty", "Mia Wideout"]
    assert len(client.get(f"/api/entries/{ada}").json()["picks"]) == 2
    assert {s["name"]: s["used"] for s in pool.standings()["standings"]} == {"ada": 2, "grace": 0}


def test_an_unlocked_pick_never_appears_in_any_response_to_someone_else(pool, client):
    pool.as_("ada")
    pool.pick(1, "QB", "q1")
    pool.pick(2, "QB", "q3")
    pool.as_("grace")
    ada = pool.entry_id("ada")
    for path in ("/api/standings", "/api/weeks/1/picks", "/api/weeks/2/picks",
                 f"/api/entries/{ada}", "/api/picks/me", "/api/weeks/1/picks/me",
                 "/api/weeks/1/players?slot=QB", "/api/weeks/2/players?slot=QB"):
        text = client.get(path).text
        assert "Sam Seattle" not in text or "players" in path, path
        assert '"used_week":1' not in text and '"used_week":2' not in text, path
    assert "Sam Seattle" not in client.get("/api/weeks/1/picks").text
    assert "Kip Kansas" not in client.get("/api/weeks/2/picks").text


def test_i_always_see_my_own_picks(pool, client):
    pool.as_("ada")
    pool.pick(1, "QB", "q1")
    assert pool.week()["ada"] == ["Sam Seattle", "empty", "empty"]
    me = client.get(f"/api/entries/{pool.entry_id('ada')}").json()
    assert me["is_me"] and [p["name"] for p in me["picks"]] == ["Sam Seattle"]


def test_unknown_week_and_entrant(pool, client):
    pool.as_("ada")
    assert client.get("/api/weeks/9/picks").status_code == 404
    assert client.get("/api/entries/999").status_code == 404
    client.post("/api/auth/logout", headers=CSRF)
    assert client.get("/api/standings").status_code == 401


# --- scores and ranks --------------------------------------------------------
def test_scores_appear_when_a_game_is_final_and_are_pending_before(pool, at, client):
    pool.as_("ada")
    pool.pick(1, "QB", "q1")     # Thursday, SEA
    pool.pick(1, "RB", "r1")     # Thursday, NE
    pool.pick(1, "FLEX", "w1")   # Sunday, MIA

    def mine():
        return {s["slot"]: (s["pick"]["tds"], s["pick"]["pending"])
                for s in client.get("/api/weeks/1/picks/me").json()}

    assert mine() == {"QB": (None, None), "RB": (None, None), "FLEX": (None, None)}  # not locked

    at(SUNDAY_LOCK)
    assert mine()["QB"] == (None, "not final yet")
    board = pool.standings()
    assert board["provisional"] and board["final_through"] == 0
    assert (board["standings"][0]["total"], board["standings"][0]["pending"]) == (0, 3)

    pool.final("w1_thu", 21, 14, q1=3)   # Sam threw/scored three; Ned England none
    assert mine() == {"QB": (3, None), "RB": (0, None), "FLEX": (None, "not final yet")}
    row = pool.standings()["standings"][0]
    assert (row["total"], row["weeks"], row["pending"]) == (3, {"1": 3}, 1)

    pool.final("w1_sun", 10, 3, w1=1)
    at(LATER)
    board = pool.standings()
    assert not board["provisional"] and board["final_through"] == 1
    assert board["standings"][0]["total"] == 4
    week = client.get("/api/weeks/1/picks").json()
    assert week["final"] and (week["entries"][0]["tds"], week["entries"][0]["pending"]) == (4, 0)
    season = {(p["week"], p["slot"]): p["tds"] for p in client.get("/api/picks/me").json()}
    assert season == {(1, "QB"): 3, (1, "RB"): 0, (1, "FLEX"): 1}


def test_ranks_share_ties_and_skip_after_them(pool, at):
    for name, qb in (("ada", "q1"), ("grace", "q1"), ("linus", "q2"), ("zed", None)):
        pool.as_(name)
        if qb:
            pool.pick(1, "QB", qb)
    pool.as_("zed").standings()  # zed has an entry but never picks
    at(LATER)
    pool.final("w1_thu", 21, 14, q1=2)
    pool.final("w1_sun", 10, 3, q2=1)

    rows = pool.standings()["standings"]
    assert [(r["rank"], r["name"], r["total"]) for r in rows] == [
        (1, "ada", 2), (1, "grace", 2), (3, "linus", 1), (4, "zed", 0),
    ]
    assert [r["is_me"] for r in rows] == [False, False, False, True]
    # The week view lists the same people, best week first.
    assert list(pool.week()) == ["ada", "grace", "linus", "zed"]
    assert pool.week()["zed"] == ["empty", "empty", "empty"]
