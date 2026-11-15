from urllib.parse import parse_qs, urlparse

from sqlalchemy import func, select

from app import auth
from app.models import Identity, User

CSRF = {"X-Requested-With": "fetch"}


def fake_google_token(monkeypatch, **claims):
    """Make the Google token exchange return fixed ID-token claims (no network)."""
    base = {
        "sub": "google-sub-1",
        "email": "ada@example.com",
        "email_verified": True,
        "name": "Ada Lovelace",
        "picture": "https://example.com/ada.png",
    }
    base.update(claims)

    async def fake_authorize_access_token(request):
        return {"userinfo": base}

    monkeypatch.setattr(
        auth.oauth.create_client("google"), "authorize_access_token", fake_authorize_access_token
    )


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_me_requires_login(client):
    assert client.get("/api/me").status_code == 401


def test_unknown_provider_404(client):
    assert client.get("/api/auth/nope/login").status_code == 404


def test_login_redirects_to_google(client, monkeypatch):
    google = auth.oauth.create_client("google")

    async def fake_metadata():
        return {
            "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_endpoint": "https://oauth2.googleapis.com/token",
            "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
            "issuer": "https://accounts.google.com",
        }

    monkeypatch.setattr(google, "load_server_metadata", fake_metadata)

    resp = client.get("/api/auth/google/login")
    assert resp.status_code == 302
    url = urlparse(resp.headers["location"])
    q = parse_qs(url.query)
    assert url.netloc == "accounts.google.com"
    assert q["client_id"] == ["test-client-id"]
    assert q["redirect_uri"] == ["http://localhost:5173/api/auth/google/callback"]
    assert q["scope"] == ["openid email profile"]
    assert "state" in q and "nonce" in q


def test_callback_creates_user_and_session(client, monkeypatch, db):
    fake_google_token(monkeypatch)

    resp = client.get("/api/auth/google/callback?code=x&state=y")
    assert resp.status_code == 303 and resp.headers["location"] == "/"

    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["email"] == "ada@example.com"
    assert me.json()["name"] == "Ada Lovelace"
    assert count(db, User) == 1 and count(db, Identity) == 1


def test_second_login_reuses_user(client, monkeypatch, db):
    fake_google_token(monkeypatch)
    client.get("/api/auth/google/callback?code=x&state=y")
    fake_google_token(monkeypatch, name="Ada L.")  # same sub, updated profile
    client.get("/api/auth/google/callback?code=x&state=y")

    assert count(db, User) == 1
    assert client.get("/api/me").json()["name"] == "Ada L."


def test_oauth_error_redirects_with_flag(client, monkeypatch):
    from authlib.integrations.base_client.errors import OAuthError

    async def boom(request):
        raise OAuthError(error="access_denied")

    monkeypatch.setattr(auth.oauth.create_client("google"), "authorize_access_token", boom)
    resp = client.get("/api/auth/google/callback?error=access_denied")
    assert resp.status_code == 303 and resp.headers["location"] == "/?login_error=1"
    assert client.get("/api/me").status_code == 401


def test_logout_needs_csrf_header_and_clears_session(client, monkeypatch):
    fake_google_token(monkeypatch)
    client.get("/api/auth/google/callback?code=x&state=y")

    assert client.post("/api/auth/logout").status_code == 403
    assert client.get("/api/me").status_code == 200  # still logged in

    assert client.post("/api/auth/logout", headers=CSRF).status_code == 204
    assert client.get("/api/me").status_code == 401


# --- account linking (pure logic, no HTTP) -----------------------------------
def _upsert(db, **kw):
    args = dict(
        provider="google", subject="s1", email="a@example.com", email_verified=True,
        name=None, picture=None,
    )
    args.update(kw)
    user = auth.upsert_identity(db, **args)
    db.commit()
    return user


def test_other_provider_links_on_verified_email(db):
    u1 = _upsert(db, provider="google", subject="g1")
    u2 = _upsert(db, provider="microsoft", subject="m1")
    assert u1.id == u2.id
    assert count(db, Identity) == 2


def test_unverified_email_never_links(db):
    u1 = _upsert(db, provider="google", subject="g1")
    u2 = _upsert(db, provider="microsoft", subject="m1", email_verified=False)
    assert u1.id != u2.id
    assert u2.email is None  # unverified emails are not stored on the user
