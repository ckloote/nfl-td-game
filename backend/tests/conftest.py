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
    """Sign the test client in as the given email (Google is faked)."""
    from app import auth

    def _login(email: str = "ada@example.com"):
        async def fake(request):
            return {"userinfo": {"sub": email, "email": email, "email_verified": True}}

        monkeypatch.setattr(auth.oauth.create_client("google"), "authorize_access_token", fake)
        assert client.get("/api/auth/google/callback?code=x&state=y").status_code == 303

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
