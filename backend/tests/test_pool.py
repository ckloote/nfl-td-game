import pytest

from app import ingest
from app.models import RosterWeek

CSRF = {"X-Requested-With": "fetch"}


def test_endpoints_need_a_signed_in_user(client, season):
    assert client.get("/api/season").status_code == 401
    assert client.get("/api/weeks/1/players?slot=QB").status_code == 401


def test_season_lists_weeks_and_current_week(client, login, at, season):
    login()
    at("2026-09-09T12:00:00+00:00")
    body = client.get("/api/season").json()
    assert body["season"] == 2026 and body["current_week"] == 1
    assert [w["week"] for w in body["weeks"]] == [1, 2]
    assert body["weeks"][0]["games"] == 2
    assert body["weeks"][0]["first_kickoff"].startswith("2026-09-11T00:20:00")
    assert body["weeks"][1]["first_kickoff"] is None


@pytest.mark.parametrize(
    "now, week",
    [
        ("2026-09-13T20:59:00+00:00", 1),  # Sunday game still within four hours of kickoff
        ("2026-09-13T21:00:00+00:00", 2),  # week 1 is over
        ("2027-03-01T00:00:00+00:00", 2),  # a week with an unpublished kickoff never finishes
    ],
)
def test_current_week_rolls_over_after_the_last_game(client, login, at, season, now, week):
    login()
    at(now)
    assert client.get("/api/season").json()["current_week"] == week


def test_current_week_is_null_without_a_schedule(client, login):
    login()
    body = client.get("/api/season").json()
    assert body["current_week"] is None and body["weeks"] == []


def test_players_for_a_slot_with_opponent_and_lock(client, login, at, season):
    login()
    at("2026-09-09T12:00:00+00:00")
    qbs = client.get("/api/weeks/1/players?slot=QB").json()
    # KC is on a bye, so Kip Kansas is not offered. Sorted by name.
    assert [p["name"] for p in qbs] == ["Bo Buffalo", "Sam Seattle"]
    bo, sam = qbs
    assert (bo["team"], bo["opponent"], bo["home"], bo["status"]) == ("BUF", "MIA", False, "RES")
    assert (sam["opponent"], sam["home"], sam["game_id"]) == ("NE", True, "w1_thu")
    assert sam["kickoff"].startswith("2026-09-11T00:20:00")
    assert sam["lock_at"].startswith("2026-09-10T23:20:00")
    assert not sam["locked"] and not bo["locked"]

    flex = client.get("/api/weeks/1/players?slot=FLEX").json()
    assert [(p["name"], p["position"]) for p in flex] == [("Al Tightend", "TE"), ("Mia Wideout", "WR")]
    assert [p["name"] for p in client.get("/api/weeks/1/players?slot=RB").json()] == ["Ned England"]


def test_lock_is_exactly_one_hour_before_each_players_kickoff(client, login, at, season):
    login()

    def locked():
        return {p["name"]: p["locked"] for p in client.get("/api/weeks/1/players?slot=QB").json()}

    at("2026-09-10T23:19:59+00:00")
    assert locked() == {"Sam Seattle": False, "Bo Buffalo": False}
    at("2026-09-10T23:20:00+00:00")  # Thursday's players lock; Sunday's stay open
    assert locked() == {"Sam Seattle": True, "Bo Buffalo": False}
    at("2026-09-13T16:00:00+00:00")
    assert locked() == {"Sam Seattle": True, "Bo Buffalo": True}


def test_week_without_its_own_roster_uses_the_latest_earlier_one(client, login, at, season):
    login()
    at("2026-09-15T12:00:00+00:00")
    qbs = client.get("/api/weeks/2/players?slot=QB").json()
    assert [p["name"] for p in qbs] == ["Kip Kansas", "Sam Seattle"]
    assert all(p["kickoff"] is None and p["lock_at"] is None and not p["locked"] for p in qbs)


def test_unknown_week_and_slot_are_rejected(client, login, season):
    login()
    assert client.get("/api/weeks/9/players?slot=QB").status_code == 404
    assert client.get("/api/weeks/1/players?slot=K").status_code == 422
    assert client.get("/api/weeks/1/players").status_code == 422


def test_admin_refresh(client, login, monkeypatch, season):
    monkeypatch.setattr(ingest, "download", lambda path: None)  # nothing published

    login("ada@example.com")
    assert client.get("/api/admin/feeds").status_code == 403
    assert client.post("/api/admin/refresh", headers=CSRF).status_code == 403

    login("boss@example.com")
    assert client.get("/api/admin/feeds").json() == []
    assert client.post("/api/admin/refresh").status_code == 403  # CSRF header required
    feeds = client.post("/api/admin/refresh", headers=CSRF).json()
    assert [f["feed"] for f in feeds] == ["rosters", "schedule", "touchdowns"]
    assert all("not published" in f["error"] and f["ok_at"] is None for f in feeds)
    assert client.get("/api/admin/feeds").json() == feeds
    # The failed refresh left the seeded schedule alone.
    assert client.get("/api/season").json()["current_week"] is not None


def test_roster_is_taken_team_by_team(client, login, at, season, db):
    """The weekly feed omits a team on its bye, and a traded player lingers on the old one."""
    db.add_all([
        # Week 2 is published for SEA only (KC's rows stop at week 1).
        RosterWeek(season=2026, week=2, player_id="q1", name="Sam Seattle", position="QB",
                   team="SEA", status="ACT"),
        # Kip Kansas was traded to SEA after week 1; KC has no newer snapshot to say so.
        RosterWeek(season=2026, week=2, player_id="q3", name="Kip Kansas", position="QB",
                   team="SEA", status="ACT"),
        RosterWeek(season=2026, week=1, player_id="q4", name="Kay Chief", position="QB",
                   team="KC", status="ACT"),
    ])
    db.commit()
    login()
    at("2026-09-15T12:00:00+00:00")
    qbs = client.get("/api/weeks/2/players?slot=QB").json()
    assert [(p["name"], p["team"]) for p in qbs] == [
        ("Kay Chief", "KC"), ("Kip Kansas", "SEA"), ("Sam Seattle", "SEA"),
    ]
