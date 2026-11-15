# NFL TD Pool

A web app for running a season-long NFL touchdown pool: entrants sign in, submit picks, and the
app tracks locks, scoring and who everyone has used. The design, rules and milestones are in
[`docs/DESIGN.md`](docs/DESIGN.md). Built so far: login, migrations, admin flag and the app shell
(M0), NFL schedule and roster data (M1), submitting picks with locks and one-use enforced (M2),
touchdown scoring with standings and everyone's locked picks (M3), and the invite link, approval
and Admin screen (M4). Deployment (M5) is still to come.

## Running a pool

1. Put your Google address in `ADMIN_EMAILS` and sign in; the Admin tab appears.
2. Copy the invite link from Admin and send it to the entrants. Open it yourself to play too.
3. Each person who opens the link and signs in shows up under Entrants as waiting; approve them.
4. Admin also lets you fix an entrant's pick after it has locked (logged under your name), and
   shows when the NFL data last loaded.

Every week's locked picks can be downloaded from the All picks page as a CSV in the layout the
selector's `pool report import` reads.

## NFL data

The schedule, weekly rosters and play-by-play come from [nflverse](https://github.com/nflverse). While the
server runs it reloads them on a timer (schedule hourly; rosters daily; play-by-play hourly
while a recent game is waiting for its final score, otherwise daily); an admin can force a
reload with `POST /api/admin/refresh` and see the outcome at `GET /api/admin/feeds`. A feed that
fails keeps the data it had. To load by hand, from `backend/`:

```bash
python -m app.ingest
```

Set `SEASON` for the season being played and `REFRESH_ENABLED=false` to turn the timer off.

## Login: "Sign in with Google"

Federated login with **no passwords stored**. The backend runs the OAuth/OIDC flow (Authlib) and
issues an HttpOnly session cookie; the React app never sees tokens.

```
backend/    FastAPI, Authlib, SQLAlchemy (SQLite by default), pytest
frontend/   Vite, React, TypeScript, Tailwind v4
```

## How it works

1. React shows `<a href="/api/auth/google/login">`. Clicking it is a full-page navigation.
2. Backend redirects to Google (state, nonce and PKCE handled by Authlib).
3. Google redirects back to `/api/auth/google/callback`. The backend exchanges the code, validates
   the ID token, finds or creates the user, and sets the session cookie.
4. React calls `GET /api/me` (200 = logged in, 401 = not) and `POST /api/auth/logout`.

Users are keyed by `(provider, sub)` in the `identities` table, never by email. A new provider
whose **verified** email matches an existing user is linked to that user; unverified emails never
link.

## 1. Google Cloud setup (one-time, ~10 minutes)

1. Create a Google Cloud project for **development** (make a second one for production later;
   Google's policies expect them to be separate).
2. APIs & Services → **OAuth consent screen**: set app name, support email, and (for production)
   a homepage and privacy policy on a domain you own.
3. Credentials → **Create credentials → OAuth client ID → Web application**:
   - Authorized JavaScript origins: `http://localhost:5173`
   - Authorized redirect URIs: `http://localhost:5173/api/auth/google/callback`
4. Copy the client ID and secret into `backend/.env` (next step).

Only the `openid email profile` scopes are requested. That is the non-sensitive set, so no Google
verification or security review is needed for basic sign-in. Avoid adding Gmail/Drive/Calendar
scopes unless you truly need them.

## 2. Run it locally

```bash
# Backend (terminal 1)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env        # then fill in GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / ADMIN_EMAILS
uvicorn app.main:app --reload --port 8000

# Frontend (terminal 2)
cd frontend
npm install
npm run dev                 # http://localhost:5173
```

Open **http://localhost:5173** (not :8000). Vite proxies `/api` to the backend so the browser sees a
single origin; that keeps cookies first-party and avoids CORS.

If `python -m venv` fails for lack of `ensurepip`, use `uv venv .venv && uv pip install -r
requirements-dev.txt` instead.

`ADMIN_EMAILS` lists the Google addresses that become admins when they sign in. `DEV_NOW`
freezes the app's clock to replay a past week (development only).

Tests: `cd backend && pytest` (Google is mocked; no network or credentials needed).

## 3. Production notes

- One origin is simplest: build the frontend (`npm run build`) and either serve `frontend/dist` from
  FastAPI (`STATIC_DIR=../frontend/dist`) or put both behind a reverse proxy at one hostname.
- Set `PUBLIC_BASE_URL=https://your.domain`, `COOKIE_SECURE=true`, and a real `SESSION_SECRET`
  (the app refuses to start with `COOKIE_SECURE=true` and the dev secret).
- Add `https://your.domain/api/auth/google/callback` to the production OAuth client's redirect URIs.
- Run uvicorn behind your proxy with `--proxy-headers`.

## 4. Known simplifications (decide before real users)

- **Sessions** live in a signed cookie holding only `user_id` (14 days). You can't revoke one
  server-side. Move to server-side sessions (Redis/DB) if you need "log out everywhere".
- **Schema** is managed by Alembic (`backend/migrations/`) and brought up to date at startup.
  After changing a model, run `alembic revision --autogenerate -m "what changed"` from
  `backend/` and review the file; a test fails while models and migrations disagree.
- **DB access is synchronous** SQLAlchemy inside async routes. Fine at starter scale; use an async
  driver or `def` routes if you see event-loop blocking.
- **CSRF**: state-changing requests require `X-Requested-With: fetch` (see `deps.py` and
  `frontend/src/api.ts`). Use `apiFetch` for every non-GET call you add.
- **Google button**: the sign-in link is a plain styled button. Follow Google's branding
  guidelines before launch.

## Adding Microsoft (or another OIDC provider)

In `backend/app/auth.py`: add one `oauth.register(name="microsoft", server_metadata_url=..., ...)`
and add `"microsoft"` to `PROVIDERS`. The login/callback routes and account linking already work for
any provider that returns standard OIDC claims. Add a link to `/api/auth/microsoft/login` in the UI.
(Microsoft's multi-tenant issuer needs one extra setting, which is documented in Authlib's guide.)
