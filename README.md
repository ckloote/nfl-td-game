# NFL TD Pool

A web app for running a season-long NFL touchdown pool: entrants sign in, submit picks, and the
app tracks locks, scoring and who everyone has used. The design, rules and milestones are in
[`docs/DESIGN.md`](docs/DESIGN.md). Built so far: login, migrations, admin flag and the app shell
(M0), NFL schedule and roster data (M1), submitting picks with locks and one-use enforced (M2),
touchdown scoring with standings and everyone's locked picks (M3), and the invite link, approval
and Admin screen (M4). M5 so far: the 2026 replay, the container image and nightly backups; the first real deploy is still to come.

## Running a pool

1. Put your Google address in `ADMIN_EMAILS` and sign in; the Admin tab appears. To add another
   organizer, have them sign in once, then choose "Make admin" under Organizers.
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

## Replaying a season from the organizer's reports

To check the app against a season that was run by hand, replay its weekly reports. From
`backend/`:

```bash
python -m app.replay ../../nfl-player-selector/data/reports --selector ../../nfl-player-selector
```

This builds a throwaway database (`replay.db`, never the app's own), downloads the season's
NFL data, creates a placeholder entrant for every name in the `weekN.csv` files, enters each
pick under the same position and one-use rules as the Admin override, and prints the standings.
With `--selector` it also compares every pick's player and touchdowns with the selector, which
must have the same reports imported. It exits non-zero if a pick could not be entered or
anything disagrees.

A name has to match exactly one eligible player in that slot that week (case and punctuation
aside); a name that doesn't is listed as a problem to fix in the report file. The exception is
a name that is exactly one player at another position. The app does not allow such a pick, so
the replay leaves it out, scores the slot zero and says so.

`--keep-data` reruns without downloading again, and `--season` and `--db` change the defaults.

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
uv venv .venv && source .venv/bin/activate
uv pip install -r requirements-dev.txt
cp .env.example .env        # then fill in GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / ADMIN_EMAILS
uvicorn app.main:app --reload --port 8000

# Frontend (terminal 2)
cd frontend
npm install
npm run dev                 # http://localhost:5173
```

Open **http://localhost:5173** (not :8000). Vite proxies `/api` to the backend so the browser sees a
single origin; that keeps cookies first-party and avoids CORS.

The Python environment is managed with [uv](https://docs.astral.sh/uv/). The `python`, `pytest`
and `alembic` commands in this README assume `backend/.venv` is activated; without activating,
prefix them with `uv run` from `backend/` (for example `uv run pytest`). After
`requirements.txt` or `requirements-dev.txt` changes, run `uv pip install -r
requirements-dev.txt` again. Plain `python -m venv` and `pip` work too if you don't have uv.

`ADMIN_EMAILS` lists the Google addresses that become admins when they sign in. Admins can
make other signed-in users admins, or stop them being one, under Organizers on the Admin screen. `DEV_NOW`
freezes the app's clock to replay a past week (development only).

Tests: `cd backend && pytest` (Google is mocked; no network or credentials needed).

## 3. Deploying

The app deploys as one container: FastAPI serves the API and the built React app from one
origin, with the SQLite database on a mounted volume. The [`Dockerfile`](Dockerfile) at the
repo root builds it. It must run as **exactly one instance**: the NFL refresh job and SQLite
both assume a single process.

The image sets `COOKIE_SECURE=true`, `DATABASE_URL=sqlite:////data/app.db` and `STATIC_DIR`
itself. With `COOKIE_SECURE=true` the app refuses to start on the development session secret
or with `DEV_NOW` set.

### On Railway

Settings are made in the Railway dashboard. (Railway's `railway.json` config files are
deprecated and stop being read on 2026-12-01, so the repo has none.)

1. **New project → Deploy from GitHub repo.** Railway finds the root `Dockerfile` and builds it.
2. **Add a volume** to the service, mounted at `/data`. A service with a volume cannot have
   replicas, which is what this app needs anyway. Redeploys cause a few seconds of downtime.
3. **Variables:**

   | Variable | Value |
   |---|---|
   | `SESSION_SECRET` | `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
   | `PUBLIC_BASE_URL` | `https://your.domain` (no trailing slash) |
   | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | From the **production** OAuth client (below) |
   | `ADMIN_EMAILS` | Comma-separated Google addresses of the organizers |
   | `SEASON` | The season being played |

   Railway sets `PORT` itself; the container listens on it.
4. **Settings → Deploy → Healthcheck path:** `/api/healthz`. Railway checks it only while a
   deploy starts, not afterwards.
5. **Settings → Networking → Custom domain:** add your hostname and create the CNAME record
   Railway shows you.
6. **Google Cloud:** in a separate production project, create an OAuth client (Web application)
   with origin `https://your.domain` and redirect URI
   `https://your.domain/api/auth/google/callback`.

The first start downloads the season's NFL data in the background; the Admin screen shows when
each feed has loaded. Then sign in with an `ADMIN_EMAILS` address and follow "Running a pool".

### Backups

Once a day the running app takes a consistent snapshot of the database, compresses it and
uploads it to an S3-compatible bucket, then deletes uploads older than `BACKUP_KEEP_DAYS`
(14 by default; the newest is never deleted). Use a bucket outside the host that runs the app,
such as Cloudflare R2 or Backblaze B2, and add these variables:

| Variable | Value |
|---|---|
| `BACKUP_S3_BUCKET` | The bucket's name. Backups are off until this is set |
| `BACKUP_S3_ENDPOINT` | The store's S3 API URL (blank for AWS S3) |
| `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY` | A key limited to that bucket |
| `BACKUP_S3_REGION` | `auto` (the default) suits R2; B2 and AWS want the bucket's region |

The Admin screen shows when the last backup ran, any error, and a "Back up now" button. A
failed backup is retried every ten minutes.

To restore, from `backend/` on any machine with the same `BACKUP_S3_*` variables:

```bash
python -m app.backup list
```

```bash
python -m app.backup restore --to restored.db
```

`restore` downloads the newest backup (or `--key ...`) to a **new** file and checks it; it
never overwrites the live database. To put it into service on Railway, run the restore in the
service's shell with `--to /data/restored.db`, set `DATABASE_URL=sqlite:////data/restored.db`,
and redeploy. Everything since that backup was taken is lost, so take a fresh one first if
the live database still opens (`python -m app.backup now`).

### Anywhere else

Any host that runs a container with a persistent disk at `/data` works the same way. Without
a container: `npm run build` in `frontend/`, set `STATIC_DIR=../frontend/dist` and the
variables above plus `COOKIE_SECURE=true`, and run
`uvicorn app.main:app --proxy-headers` behind an HTTPS reverse proxy.

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
