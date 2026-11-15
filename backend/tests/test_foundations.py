from datetime import datetime, timezone

from alembic.autogenerate import compare_metadata
from fastapi import Depends
from alembic.migration import MigrationContext

from app import auth, clock
from app.config import settings
from app.db import Base, engine
from app.deps import require_admin
from app.main import app
from app.models import User


def test_migrations_match_models():
    """A model change without a migration fails here, not in production."""
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def _upsert(db, email, **kw):
    args = dict(
        provider="google", subject=email, email=email, email_verified=True,
        name=None, picture=None,
    )
    args.update(kw)
    user = auth.upsert_identity(db, **args)
    db.commit()
    return user


def test_admin_emails_grant_admin(db):
    assert _upsert(db, "boss@example.com").is_admin
    assert _upsert(db, "second@example.com").is_admin  # case and spaces ignored
    assert not _upsert(db, "ada@example.com").is_admin


def test_unverified_admin_email_is_not_admin(db):
    assert not _upsert(db, "boss@example.com", email_verified=False).is_admin


def test_require_admin(client, db):
    @app.get("/api/_test_admin")
    def _probe(user: User = Depends(require_admin)):
        return {"ok": True}

    try:
        assert client.get("/api/_test_admin").status_code == 401

        async def as_user(request):
            return {"userinfo": {"sub": "u", "email": "ada@example.com", "email_verified": True}}

        async def as_boss(request):
            return {"userinfo": {"sub": "b", "email": "boss@example.com", "email_verified": True}}

        google = auth.oauth.create_client("google")
        google.authorize_access_token = as_user
        client.get("/api/auth/google/callback?code=x&state=y")
        assert client.get("/api/_test_admin").status_code == 403
        assert client.get("/api/me").json()["is_admin"] is False

        google.authorize_access_token = as_boss
        client.get("/api/auth/google/callback?code=x&state=y")
        assert client.get("/api/_test_admin").status_code == 200
        assert client.get("/api/me").json()["is_admin"] is True
    finally:
        app.router.routes[:] = [
            r for r in app.router.routes if getattr(r, "path", "") != "/api/_test_admin"
        ]


def test_clock_is_utc_and_can_be_frozen(monkeypatch):
    assert clock.now().tzinfo is not None
    monkeypatch.setattr(settings, "dev_now", "2026-09-17T20:00:00")
    assert clock.now() == datetime(2026, 9, 17, 20, 0, tzinfo=timezone.utc)
