"""Locks and one-use, exercised by moving the app's clock around a two-week season.

Week 1: NE@SEA locks Thu 2026-09-10 23:20Z; BUF@MIA locks Sun 2026-09-13 16:00Z.
Week 2: KC vs SEA, kickoff unpublished, so nothing there locks.
"""

import pytest
from sqlalchemy import select

from app.models import Pick, PickEvent

CSRF = {"X-Requested-With": "fetch"}
BEFORE_THURSDAY_LOCK = "2026-09-10T23:19:59+00:00"
THURSDAY_LOCK = "2026-09-10T23:20:00+00:00"
SUNDAY_LOCK = "2026-09-13T16:00:00+00:00"


@pytest.fixture()
def pool(client, login, at, season):
    """Signed in before any lock, with helpers that return the response."""
    login()
    at("2026-09-09T12:00:00+00:00")

    class Pool:
        def put(self, week, slot, player_id):
            return client.put(
                f"/api/weeks/{week}/picks/{slot}", json={"player_id": player_id}, headers=CSRF
            )

        def clear(self, week, slot):
            return client.delete(f"/api/weeks/{week}/picks/{slot}", headers=CSRF)

        def week(self, week):
            slots = client.get(f"/api/weeks/{week}/picks/me").json()
            return {s["slot"]: s["pick"] and s["pick"]["name"] for s in slots}

    return Pool()


def test_set_read_change_and_clear_a_pick(pool, client, db):
    assert pool.week(1) == {"QB": None, "RB": None, "FLEX": None}

    made = pool.put(1, "QB", "q1")
    assert made.status_code == 200
    body = made.json()
    assert (body["name"], body["team"], body["opponent"], body["home"]) == (
        "Sam Seattle", "SEA", "NE", True,
    )
    assert body["lock_at"].startswith("2026-09-10T23:20:00") and not body["locked"]
    assert pool.week(1) == {"QB": "Sam Seattle", "RB": None, "FLEX": None}

    assert pool.put(1, "QB", "q2").status_code == 200  # change of mind before any lock
    assert pool.week(1)["QB"] == "Bo Buffalo"
    assert pool.clear(1, "QB").status_code == 204
    assert pool.clear(1, "QB").status_code == 204  # clearing an empty slot is fine
    assert pool.week(1)["QB"] is None

    # Every change is in the log, in order, with who made it.
    events = db.scalars(select(PickEvent).order_by(PickEvent.id)).all()
    assert [(e.old_player_id, e.new_player_id) for e in events] == [
        (None, "q1"), ("q1", "q2"), ("q2", None),
    ]
    assert {e.actor_user_id for e in events} == {client.get("/api/me").json()["id"]}


def test_repeating_the_same_pick_changes_nothing(pool, db):
    pool.put(1, "QB", "q1")
    assert pool.put(1, "QB", "q1").status_code == 200
    assert len(db.scalars(select(PickEvent)).all()) == 1


def test_all_three_slots_and_the_season_list(pool, client):
    for slot, player in (("QB", "q2"), ("RB", "r1"), ("FLEX", "t1")):
        assert pool.put(1, slot, player).status_code == 200
    pool.put(2, "QB", "q1")
    assert pool.week(1) == {"QB": "Bo Buffalo", "RB": "Ned England", "FLEX": "Al Tightend"}
    mine = client.get("/api/picks/me").json()
    assert [(p["week"], p["slot"], p["name"]) for p in mine] == [
        (1, "QB", "Bo Buffalo"), (1, "RB", "Ned England"), (1, "FLEX", "Al Tightend"),
        (2, "QB", "Sam Seattle"),
    ]


def test_wrong_position_bye_week_and_unknowns_are_refused(pool):
    assert pool.put(1, "RB", "q1").status_code == 400    # a QB in the RB slot
    assert pool.put(1, "QB", "w1").status_code == 400    # a WR in the QB slot
    assert pool.put(1, "QB", "q3").status_code == 400    # KC has no game in week 1
    assert pool.put(1, "QB", "nobody").status_code == 400
    assert pool.put(9, "QB", "q1").status_code == 404    # no such week
    assert pool.put(1, "K", "q1").status_code == 422     # no such slot
    assert pool.clear(9, "QB").status_code == 404
    assert pool.week(1) == {"QB": None, "RB": None, "FLEX": None}


def test_writes_need_the_csrf_header_and_a_session(pool, client):
    assert client.put("/api/weeks/1/picks/QB", json={"player_id": "q1"}).status_code == 403
    assert client.delete("/api/weeks/1/picks/QB").status_code == 403
    client.post("/api/auth/logout", headers=CSRF)
    assert pool.put(1, "QB", "q1").status_code == 401
    assert client.get("/api/picks/me").status_code == 401


# --- locks -------------------------------------------------------------------
def test_a_player_can_be_picked_until_exactly_an_hour_before_his_kickoff(pool, at):
    at(BEFORE_THURSDAY_LOCK)
    assert pool.put(1, "QB", "q1").status_code == 200
    assert pool.clear(1, "QB").status_code == 204

    at(THURSDAY_LOCK)
    refused = pool.put(1, "QB", "q1")
    assert refused.status_code == 409 and "locked" in refused.json()["detail"]
    assert pool.put(1, "QB", "q2").status_code == 200  # Sunday's players are still open

    at(SUNDAY_LOCK)
    assert pool.put(1, "FLEX", "w1").status_code == 409


def test_a_locked_pick_cannot_be_changed_or_cleared(pool, at, client):
    pool.put(1, "QB", "q1")  # Thursday player
    at(THURSDAY_LOCK)
    assert client.get("/api/weeks/1/picks/me").json()[0]["pick"]["locked"] is True
    # Not even for a player whose own game is still open.
    assert pool.put(1, "QB", "q2").status_code == 409
    assert pool.clear(1, "QB").status_code == 409
    assert pool.week(1)["QB"] == "Sam Seattle"


def test_an_open_pick_cannot_be_swapped_for_a_locked_player(pool, at):
    pool.put(1, "QB", "q2")  # Sunday player
    at(THURSDAY_LOCK)
    assert pool.put(1, "QB", "q1").status_code == 409
    assert pool.week(1)["QB"] == "Bo Buffalo"
    assert pool.clear(1, "QB").status_code == 204  # still free to change his mind


def test_slots_lock_independently(pool, at):
    pool.put(1, "RB", "r1")  # Thursday
    at(THURSDAY_LOCK)
    assert pool.put(1, "QB", "q2").status_code == 200   # Sunday QB after the RB locked
    assert pool.put(1, "FLEX", "w1").status_code == 200
    assert pool.put(1, "FLEX", "t1").status_code == 409  # Thursday TE is gone
    assert pool.week(1) == {"QB": "Bo Buffalo", "RB": "Ned England", "FLEX": "Mia Wideout"}


def test_an_empty_slot_closes_when_the_last_game_locks(pool, at, client):
    def is_open():
        return [s["open"] for s in client.get("/api/weeks/1/picks/me").json()]

    at(THURSDAY_LOCK)
    assert is_open() == [True, True, True]
    at(SUNDAY_LOCK)
    assert is_open() == [False, False, False]


def test_a_game_without_a_kickoff_time_does_not_lock(pool, at):
    at("2027-01-01T00:00:00+00:00")
    assert pool.put(2, "QB", "q3").status_code == 200
    assert pool.clear(2, "QB").status_code == 204


# --- one use per season ------------------------------------------------------
def test_a_player_can_be_used_only_once_a_season(pool, at):
    pool.put(1, "QB", "q1")
    refused = pool.put(2, "QB", "q1")
    assert refused.status_code == 409 and "week 1" in refused.json()["detail"]

    at(SUNDAY_LOCK)  # still spent once week 1 has locked
    assert pool.put(2, "QB", "q1").status_code == 409
    assert pool.week(2)["QB"] is None


def test_clearing_or_replacing_before_the_lock_frees_the_player(pool):
    pool.put(1, "QB", "q1")
    pool.put(1, "QB", "q2")                             # replaced: q1 is free again
    assert pool.put(2, "QB", "q1").status_code == 200
    pool.clear(2, "QB")                                 # cleared: free again
    pool.clear(1, "QB")
    assert pool.put(1, "QB", "q1").status_code == 200


def test_the_database_itself_refuses_a_second_use(pool, db):
    """The rule holds even if a request slips past the checks (two at once)."""
    from sqlalchemy.exc import IntegrityError

    pool.put(1, "QB", "q1")
    first = db.scalars(select(Pick)).one()
    db.add(Pick(entry_id=first.entry_id, week=2, slot="QB", player_id="q1", player_name="x",
                position="QB", team="SEA", game_id="w2_tbd", updated_at=first.updated_at))
    with pytest.raises(IntegrityError):
        db.commit()


def test_players_list_shows_which_week_i_used_someone(pool, client):
    pool.put(1, "QB", "q1")
    week2 = {p["name"]: p["used_week"] for p in client.get("/api/weeks/2/players?slot=QB").json()}
    assert week2 == {"Kip Kansas": None, "Sam Seattle": 1}


def test_entrants_are_independent(pool, client, login):
    pool.put(1, "QB", "q1")
    login("grace@example.com")
    assert pool.week(1)["QB"] is None                   # doesn't see or share ada's pick
    assert pool.put(1, "QB", "q1").status_code == 200   # same player, different entrant
    assert pool.put(1, "QB", "q2").status_code == 200
    login("ada@example.com")
    assert pool.week(1)["QB"] == "Sam Seattle"
