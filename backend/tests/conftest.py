import os
import tempfile

# Must be set before the app is imported (settings are read at import time).
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["GOOGLE_CLIENT_ID"] = "test-client-id"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-client-secret"
os.environ["PUBLIC_BASE_URL"] = "http://localhost:5173"
os.environ["ADMIN_EMAILS"] = "boss@example.com, Second@Example.com"
os.environ["REFRESH_ENABLED"] = "false"
os.environ["SEASON"] = "2026"
os.environ.pop("STATIC_DIR", None)
os.environ.pop("DEV_NOW", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from sqlalchemy import text  # noqa: E402

from app.db import Base, SessionLocal, engine, upgrade_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db():
    # Build the schema the way production does: from the migrations, not the models.
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    upgrade_db()


@pytest.fixture()
def client():
    with TestClient(app, follow_redirects=False) as c:
        yield c


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def login(client, monkeypatch):
    """Sign the test client in as the given email (Google is faked).

    By default the user also gets an approved entry; pass entry=False for a newcomer.
    """
    from app import auth

    def _login(email: str = "ada@example.com", entry: bool = True):
        async def fake(request):
            return {"userinfo": {"sub": email, "email": email, "email_verified": True}}

        monkeypatch.setattr(auth.oauth.create_client("google"), "authorize_access_token", fake)
        assert client.get("/api/auth/google/callback?code=x&state=y").status_code == 303
        if entry:
            from sqlalchemy import select

            from app.models import Entry, User

            with SessionLocal() as session:
                user = session.scalar(select(User).where(User.email == email))
                if not session.scalar(select(Entry).where(Entry.user_id == user.id)):
                    session.add(Entry(user_id=user.id, season=2026, status="approved",
                                      display_name=email.split("@")[0]))
                    session.commit()

    return _login


@pytest.fixture()
def at():
    """Set the app's clock: at(datetime) or at("2026-09-13T16:00:00+00:00")."""
    from datetime import datetime

    from app import clock

    def _at(when):
        moment = datetime.fromisoformat(when) if isinstance(when, str) else when
        app.dependency_overrides[clock.now] = lambda: moment

    yield _at
    app.dependency_overrides.pop(clock.now, None)


@pytest.fixture()
def season(db):
    """Two weeks. Week 1: NE@SEA Thursday, BUF@MIA Sunday (KC on a bye). Week 2: time TBD."""
    from datetime import datetime, timezone

    from app.models import Game, RosterWeek

    UTC = timezone.utc
    db.add_all([
        Game(game_id="w1_thu", season=2026, week=1, home_team="SEA", away_team="NE",
             gameday="2026-09-10", kickoff=datetime(2026, 9, 11, 0, 20, tzinfo=UTC)),
        Game(game_id="w1_sun", season=2026, week=1, home_team="MIA", away_team="BUF",
             gameday="2026-09-13", kickoff=datetime(2026, 9, 13, 17, 0, tzinfo=UTC)),
        Game(game_id="w2_tbd", season=2026, week=2, home_team="KC", away_team="SEA",
             gameday="2026-09-20", kickoff=None),
        Game(game_id="old", season=2025, week=1, home_team="KC", away_team="SEA",
             gameday="2025-09-07", kickoff=datetime(2025, 9, 7, 17, 0, tzinfo=UTC)),
    ])

    def player(week, pid, name, pos, team, status="ACT"):
        return RosterWeek(season=2026, week=week, player_id=pid, name=name, position=pos,
                          team=team, status=status)

    db.add_all([
        player(1, "q1", "Sam Seattle", "QB", "SEA"),
        player(1, "q2", "Bo Buffalo", "QB", "BUF", "RES"),
        player(1, "q3", "Kip Kansas", "QB", "KC"),
        player(1, "r1", "Ned England", "RB", "NE"),
        player(1, "w1", "Mia Wideout", "WR", "MIA"),
        player(1, "t1", "Al Tightend", "TE", "SEA"),
    ])
    db.commit()
