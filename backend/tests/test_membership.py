"""The invite link, approval, the organizer's overrides, and the weekly export."""

import pytest
from sqlalchemy import select

from app import auth
from app.models import PickEvent

CSRF = {"X-Requested-With": "fetch"}
EARLY = "2026-09-09T12:00:00+00:00"
THURSDAY_LOCK = "2026-09-10T23:20:00+00:00"
SUNDAY_LOCK = "2026-09-13T16:00:00+00:00"


@pytest.fixture()
def invite(client, login):
    """The invite token, fetched as the admin."""
    login("boss@example.com", entry=False)
    url = client.get("/api/admin/invite").json()["url"]
    assert url.startswith("http://localhost:5173/join/")
    return url.rsplit("/", 1)[1]


def join(client, token, **body):
    return client.post(f"/api/join/{token}", json=body or None, headers=CSRF)


def my_status(client):
    entry = client.get("/api/season").json()["entry"]
    return entry and entry["status"]


def admin_entries(client):
    return {e["display_name"]: e for e in client.get("/api/admin/entries").json()}


# --- joining -----------------------------------------------------------------
def test_a_newcomer_cannot_pick_until_invited_and_approved(client, login, invite, season, at):
    at(EARLY)
    login("ada@example.com", entry=False)
    assert my_status(client) is None
    assert client.get("/api/standings").status_code == 403
    assert client.put("/api/weeks/1/picks/QB", json={"player_id": "q1"}, headers=CSRF).status_code == 403

    assert join(client, "wrong-token").status_code == 404
    assert client.post(f"/api/join/{invite}").status_code == 403  # CSRF header required
    joined = join(client, invite)
    assert joined.status_code == 200 and joined.json()["status"] == "pending"
    assert my_status(client) == "pending"
    assert client.get("/api/weeks/1/players?slot=QB").status_code == 403   # still waiting
    assert join(client, invite).json()["entry_id"] == joined.json()["entry_id"]  # no duplicate

    login("boss@example.com", entry=False)
    pending = admin_entries(client)["ada"]
    assert (pending["status"], pending["email"], pending["picks"]) == ("pending", "ada@example.com", 0)
    approved = client.patch(f"/api/admin/entries/{pending['entry_id']}", json={"status": "approved"},
                            headers=CSRF)
    assert approved.json()["status"] == "approved"

    login("ada@example.com", entry=False)
    assert my_status(client) == "approved"
    assert client.put("/api/weeks/1/picks/QB", json={"player_id": "q1"}, headers=CSRF).status_code == 200
    assert [s["name"] for s in client.get("/api/standings").json()["standings"]] == ["ada"]


def test_an_admin_joins_already_approved_and_names_are_kept_distinct(client, login, invite):
    assert join(client, invite, display_name="  The Boss ").json() == {
        "entry_id": 1, "display_name": "The Boss", "status": "approved",
    }
    login("ada@example.com", entry=False)
    assert join(client, invite, display_name="the boss").json()["display_name"] == "the boss 2"


def test_a_removed_entrant_is_locked_out_and_leaves_the_standings(client, login, invite, season, at):
    at(EARLY)
    login("ada@example.com")
    client.put("/api/weeks/1/picks/QB", json={"player_id": "q1"}, headers=CSRF)
    login("boss@example.com", entry=False)
    ada = admin_entries(client)["ada"]["entry_id"]
    client.patch(f"/api/admin/entries/{ada}", json={"status": "removed"}, headers=CSRF)

    login("ada@example.com", entry=False)
    assert my_status(client) == "removed"
    assert client.get("/api/picks/me").status_code == 403
    assert join(client, invite).json()["status"] == "removed"   # the link does not reinstate

    login("grace@example.com")
    assert [s["name"] for s in client.get("/api/standings").json()["standings"]] == ["grace"]
    assert client.get(f"/api/entries/{ada}").status_code == 404

    login("boss@example.com", entry=False)   # reinstating restores the picks
    restored = client.patch(f"/api/admin/entries/{ada}", json={"status": "approved"}, headers=CSRF)
    assert restored.json()["picks"] == 1


def test_rotating_the_invite_link_kills_the_old_one(client, login, invite):
    new = client.post("/api/admin/invite/rotate", headers=CSRF).json()["url"].rsplit("/", 1)[1]
    assert new != invite
    login("ada@example.com", entry=False)
    assert join(client, invite).status_code == 404
    assert join(client, new).status_code == 200


def test_admin_can_rename_but_not_onto_a_taken_name(client, login, invite):
    login("ada@example.com")
    login("grace@example.com")
    login("boss@example.com", entry=False)
    ada = admin_entries(client)["ada"]["entry_id"]
    renamed = client.patch(f"/api/admin/entries/{ada}", json={"display_name": "Ada L."}, headers=CSRF)
    assert renamed.json()["display_name"] == "Ada L."
    clash = client.patch(f"/api/admin/entries/{ada}", json={"display_name": "GRACE"}, headers=CSRF)
    assert clash.status_code == 409
    assert client.patch("/api/admin/entries/999", json={"status": "approved"}, headers=CSRF).status_code == 404


def test_membership_admin_endpoints_are_admin_only(client, login):
    login("ada@example.com")
    assert client.get("/api/admin/invite").status_code == 403
    assert client.get("/api/admin/entries").status_code == 403
    assert client.post("/api/admin/invite/rotate", headers=CSRF).status_code == 403
    assert client.patch("/api/admin/entries/1", json={"status": "removed"}, headers=CSRF).status_code == 403
    assert client.get("/api/admin/entries/1/weeks/1/picks").status_code == 403
    assert client.put("/api/admin/entries/1/weeks/1/picks/QB", json={"player_id": "q1"},
                      headers=CSRF).status_code == 403


def test_login_returns_to_the_invite_link(client, monkeypatch):
    google = auth.oauth.create_client("google")

    async def fake_redirect(request, redirect_uri):
        from fastapi.responses import RedirectResponse
        return RedirectResponse("https://accounts.google.com/x")

    async def fake_token(request):
        return {"userinfo": {"sub": "s", "email": "ada@example.com", "email_verified": True}}

    monkeypatch.setattr(google, "authorize_redirect", fake_redirect)
    monkeypatch.setattr(google, "authorize_access_token", fake_token)

    client.get("/api/auth/google/login?next=/join/abc")
    assert client.get("/api/auth/google/callback?code=x&state=y").headers["location"] == "/join/abc"
    # Only same-site paths are honoured.
    for bad in ("https://evil.example/", "//evil.example/", "join/abc"):
        client.get("/api/auth/google/login", params={"next": bad})
        assert client.get("/api/auth/google/callback?code=x&state=y").headers["location"] == "/"


# --- organizer's pick overrides ----------------------------------------------
def test_admin_can_set_and_clear_a_pick_after_it_has_locked(client, login, season, at, db):
    at(EARLY)
    login("ada@example.com")
    client.put("/api/weeks/1/picks/QB", json={"player_id": "q1"}, headers=CSRF)   # Thursday
    at(SUNDAY_LOCK)
    assert client.put("/api/weeks/1/picks/RB", json={"player_id": "r1"}, headers=CSRF).status_code == 409

    login("boss@example.com", entry=False)
    ada = admin_entries(client)["ada"]["entry_id"]
    base = f"/api/admin/entries/{ada}/weeks/1"
    assert [s["pick"] and s["pick"]["name"] for s in client.get(f"{base}/picks").json()] == [
        "Sam Seattle", None, None,
    ]
    # Ada's used players are marked in the list the admin picks from.
    assert {p["name"]: p["used_week"] for p in client.get(f"{base}/players?slot=QB").json()} == {
        "Bo Buffalo": None, "Sam Seattle": 1,
    }
    assert client.put(f"{base}/picks/RB", json={"player_id": "r1"}, headers=CSRF).status_code == 200
    assert client.put(f"{base}/picks/QB", json={"player_id": "q2"}, headers=CSRF).status_code == 200
    assert client.delete(f"{base}/picks/RB", headers=CSRF).status_code == 204
    assert client.put(f"{base}/picks/RB", json={"player_id": "r1"}).status_code == 403  # CSRF

    # The other rules still hold for the admin.
    assert client.put(f"{base}/picks/RB", json={"player_id": "q1"}, headers=CSRF).status_code == 400
    assert client.put(f"/api/admin/entries/{ada}/weeks/2/picks/QB", json={"player_id": "q1"},
                      headers=CSRF).status_code == 200
    assert client.put(f"{base}/picks/QB", json={"player_id": "q1"},
                      headers=CSRF).status_code == 409   # already used in week 2
    assert client.delete(f"/api/admin/entries/{ada}/weeks/2/picks/QB", headers=CSRF).status_code == 204
    assert client.put("/api/admin/entries/999/weeks/1/picks/QB", json={"player_id": "q1"},
                      headers=CSRF).status_code == 404

    # The log shows who made each change.
    boss = client.get("/api/me").json()["id"]
    events = db.scalars(select(PickEvent).order_by(PickEvent.id)).all()
    assert [(e.slot, e.old_player_id, e.new_player_id, e.actor_user_id == boss) for e in events] == [
        ("QB", None, "q1", False), ("RB", None, "r1", True), ("QB", "q1", "q2", True),
        ("RB", "r1", None, True), ("QB", None, "q1", True), ("QB", "q1", None, True),
    ]
    login("ada@example.com")
    assert client.get("/api/weeks/1/picks/me").json()[0]["pick"]["name"] == "Bo Buffalo"


# --- export ------------------------------------------------------------------
def test_week_export_lists_locked_picks_in_the_selectors_layout(client, login, season, at):
    at(EARLY)
    login("ada@example.com")
    client.put("/api/weeks/1/picks/QB", json={"player_id": "q1"}, headers=CSRF)    # Thursday
    client.put("/api/weeks/1/picks/FLEX", json={"player_id": "w1"}, headers=CSRF)  # Sunday
    login("grace@example.com")
    client.put("/api/weeks/1/picks/RB", json={"player_id": "r1"}, headers=CSRF)    # Thursday

    assert client.get("/api/export/week/1.csv").text == "week,entrant,QB,RB,FLEX\n1,ada,,,\n1,grace,,,\n"
    at(THURSDAY_LOCK)
    response = client.get("/api/export/week/1.csv")
    assert response.headers["content-type"].startswith("text/csv")
    assert 'filename="week1.csv"' in response.headers["content-disposition"]
    assert response.text == "week,entrant,QB,RB,FLEX\n1,ada,Sam Seattle,,\n1,grace,,Ned England,\n"
    at(SUNDAY_LOCK)
    assert client.get("/api/export/week/1.csv").text == (
        "week,entrant,QB,RB,FLEX\n1,ada,Sam Seattle,,Mia Wideout\n1,grace,,Ned England,\n"
    )
    assert client.get("/api/export/week/9.csv").status_code == 404
    login("zed@example.com", entry=False)
    assert client.get("/api/export/week/1.csv").status_code == 403
