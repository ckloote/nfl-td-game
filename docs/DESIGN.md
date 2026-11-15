# Design: NFL Touchdown Pool web app

## Context

The pool is run by hand today: entrants send picks to the organizer, who sends back a weekly
report of everyone's picks and totals. `../nfl-player-selector` is one entrant's private advice
tool for that pool; its `docs/DESIGN.md` §1 is the authoritative statement of the rules, and its
`src/pool/scoring.py` and `results.py` are a working, tested implementation of scoring.

This app replaces the manual part: entrants sign in, submit picks, and the app enforces locks
and one-use, scores from NFL data, and shows standings and who everyone has used. It is not an
advice tool; nothing from the selector's projection, optimizer or simulation code comes over.

Decisions already made with you:

- **One pool**, one season at a time; past seasons kept as read-only history.
- **Go live for week 1 of 2027.** The 2026 season is the development and test dataset.
- **Joining:** organizer shares an invite link; a signed-in user is pending until approved.
- **Visibility:** a pick becomes visible to everyone at the moment it locks.

## 1. Rules the app enforces

| # | Rule (selector `DESIGN.md` §1) | In the app |
|---|---|---|
| 1 | Each week pick one QB, one RB, one WR/TE | Three slots per entrant per week: `QB`, `RB`, `FLEX` |
| 2 | Score = TDs thrown or scored, any kind; no 2-pt conversions | Ported from `scoring.transform_touchdowns` |
| 3 | A player at most once per season | DB unique constraint on (entry, player) |
| 4 | Most TDs wins; ties at the top split | Competition ranks (1, 2, 2, 4) |
| 5 | Each pick locks 1 hour before that player's kickoff, independently | Checked on the server at every write |
| 6 | Weekly report of all picks and totals | Replaced by the standings and week pages |
| 7 | A player in the wrong slot scores zero and is spent | Cannot happen through the UI (only eligible players are offered); stays possible for an admin-entered pick and is scored as zero |

Derived behaviour:

- **A slot can be changed freely until it locks.** Changing means: the current pick's lock has
  not passed *and* the new player's lock has not passed. Clearing a slot frees the player.
- **A missed slot is a no-pick:** zero TDs, nobody spent.
- **Any future week can be picked ahead of time.** A player held in a later week counts as used
  until that slot is cleared.
- **Only players whose team plays that week can be picked.** A game with no confirmed kickoff
  time is pickable and has no lock until the time is published.
- **A pick on a player who then doesn't play scores zero** once his game is final, and he is spent.

## 2. Architecture

Keeps the existing stack and its single-origin shape. No new services.

```
Browser (React, Vite, Tailwind)
   │  /api/*  same origin, session cookie, X-Requested-With on writes
FastAPI ── auth (existing) ── picks ── standings ── admin
   │                                        │
SQLAlchemy ── SQLite (WAL)          refresh job (in-process, timed)
                                            │
                                    nflverse via nflreadpy
```

- **Backend** stays FastAPI + SQLAlchemy. New routers beside `backend/app/auth.py`, all using the
  existing `current_user` and `require_csrf_header` from `backend/app/deps.py`.
- **Database** stays SQLite (a pool is tens of users). Turn on WAL. Replace `create_all` with
  **Alembic** in M0, as the README already advises, before any real data exists.
- **Refresh job** is a plain function run from a timed task started in the FastAPI lifespan, and
  from an admin "Refresh now" button. Assumes one uvicorn process; a `last_run` row guards
  against overlap.
- **Clock** is a dependency (`now()`), so tests and a dev-only "as of" setting can replay 2026
  weeks and exercise locks.
- **Frontend** adds `react-router` for pages and TanStack Query for fetching and polling. Every
  write goes through the existing `apiFetch` in `frontend/src/api.ts`.

## 3. NFL data and scoring

**Source:** nflverse through `nflreadpy`, the same source the organizer and the selector use.

| Feed | Used for | Refresh |
|---|---|---|
| Schedule | Weeks, kickoff times (stored UTC), final scores | Hourly in season |
| Rosters | Player list, team, position | Daily |
| Play-by-play | Touchdown credits, game completeness | Hourly while a game from the last four days has no trusted final, daily otherwise |

A failed download keeps the previous data, as in the selector's `ingest.refresh`.

**Scoring is ported, not imported.** Depending on the selector package would pull in scipy and
the research code. Instead copy the logic of two small pieces, with their tests:

- `scoring.transform_touchdowns` (`../nfl-player-selector/src/pool/scoring.py`): one credit for
  the scorer (`td_player_id`), one more for the passer on a passing TD; conversions and negated
  plays excluded. A game is **complete** only with an end-of-game marker, terminal scores equal
  to the schedule, and every TD identity resolved.
- `results.score_pick` (`../nfl-player-selector/src/pool/results.py`): a complete game with no
  credits is a real **0**; an incomplete or missing feed is **pending**, never zero.

A pick is scored from the game the player has credits in that week when there is one (he may
have changed teams after the pick was made), otherwise from the game he was picked in. The
selector's "pick with no game" case cannot arise here, because only players with a game can be
picked.

**Scores are not stored.** They are computed on read from `touchdown_credits` and `game_results`,
so an upstream stat correction appears after the next refresh. Totals show as provisional while
any pick is pending.

**Consequence to accept:** nflverse play-by-play lands after games, not during them. Picks and
locks are live; TD counts appear some hours after a game ends. Live in-game scoring would need a
second, unofficial source and is out of scope for v1 (open question 2).

**Slot eligibility** comes from the roster position: QB → `QB`; RB → `RB`; WR, TE → `FLEX`.
nflverse lists fullbacks as RB, so they are eligible as `RB`. Players the roster says have left
a team (cut, retired, traded away) are not offered; injured-reserve and practice-squad players
are, with their status shown.
An admin-editable `position_overrides` table covers players the pool rules differently.

## 4. Data model

Existing `users` and `identities` are unchanged except `users.is_admin`. First admins come from
an `ADMIN_EMAILS` setting, matched against the verified email at login.

| Table | Key columns | Notes |
|---|---|---|
| `seasons` | year, first_week, last_week, status, invite_token | One row is current. Arrives with M4; until then the season is the `SEASON` setting |
| `entries` | user_id, season, display_name, status (`pending`/`approved`/`removed`) | Unique (user, season). An entry, not a user, owns picks. Until M4 adds the invite link and approval, anyone who signs in gets an approved entry |
| `picks` | entry_id, week, slot, player_id, player name/position/team as submitted, game_id, updated_at | Unique (entry, week, slot) and unique (entry, player) |
| `pick_events` | entry_id, week, slot, old/new player, actor_user_id, at | Append-only; settles disputes about what was submitted when |
| `games` | game_id, season, week, home, away, kickoff_utc, scores | From schedule |
| `roster_weeks` | season, week, player_id (nflverse gsis), name, position, team, status | From weekly rosters. A week's player list is each team's latest roster at or before that week, because the feed skips a team on its bye |
| `position_overrides` | season, player_id, slot | Admin |
| `touchdown_credits` | game_id, play_id, player_id, kind, season | From play-by-play |
| `game_results` | game_id, complete, reason, scores | From play-by-play |
| `feed_status` | feed, season, attempted_at, ok_at, rows, error | Shown on the admin page |

A pick's lock time is not stored: it is `games.kickoff_utc − 60 min` for the player's game that
week, read at request time, so a rescheduled game moves the lock with it.

## 5. API

All under `/api`, JSON, session cookie. Writes require the CSRF header.

| Method and path | Who | Does |
|---|---|---|
| `POST /join/{token}` | signed in | Creates a pending entry |
| `GET /season` | entrant | Current season, current week, my entry status |
| `GET /weeks/{w}/players?slot=` | entrant | Eligible players with opponent, kickoff, lock time, and whether I've used them |
| `GET /weeks/{w}/picks/me` | entrant | My three slots, locked or open |
| `PUT /weeks/{w}/picks/{slot}` | entrant | Set or change a pick; `DELETE` clears it |
| `GET /weeks/{w}/picks` | entrant | Everyone's **locked** picks for the week, with scores. An unlocked slot reads `hidden` whether or not it is filled; `empty` only once the week has locked |
| `GET /standings` | entrant | Rank, total, weekly totals, provisional flag |
| `GET /entries/{id}` | entrant | One entrant's season grid and used players (locked picks only) |
| `GET /export/week/{w}.csv` | entrant | `week,entrant,QB,RB,FLEX`, the layout the selector's `pool report import` already reads |
| `/admin/*` | admin | Approve or remove entries, rotate invite link, set a pick on someone's behalf, position overrides, refresh now, feed status |

Two rules are enforced in the server, never only in the UI:

- **Lock:** `PUT`/`DELETE` are refused when either the existing or the new player's lock has
  passed. Admin writes bypass this and are recorded in `pick_events` with the admin as actor.
- **Visibility:** any response containing another entrant's pick filters to `lock time ≤ now`.
  This includes used-player lists and the CSV export. Standings count only locked picks, so an
  entrant's total and players-used never reveal a pick that could still change.

## 6. Screens

1. **Sign in / join** — existing Google sign-in; the invite link lands here and shows
   "waiting for approval" until approved.
2. **This week** (home) — three slot cards. Each shows the current pick, its lock countdown, or
   a locked pick with its score. Choosing a slot opens a searchable player list: team, opponent,
   kickoff, lock time; used players greyed out with the week they were used.
3. **My season** — week × slot grid of my picks and scores, plus my used players by position.
4. **Standings** — rank, entrant, season TDs, this week's TDs; provisional marker when anything
   is pending.
5. **Week view** — every entrant's locked picks for a week; unlocked slots show as hidden.
6. **Entrant page** — another entrant's grid and used players.
7. **Admin** — pending approvals, invite link, feed status and refresh, pick override, position
   overrides.

Times are shown in the viewer's local timezone. Mobile layout first; most picks will be made on
a phone.

## 7. Milestones

| | Delivers | Done when |
|---|---|---|
| **M0** Foundations ✔ | Alembic, `is_admin`, clock dependency, router and app shell | Existing auth tests pass on migrated schema |
| **M1** NFL data ✔ | Schedule and roster ingest, refresh job, players endpoint | 2026 schedule and rosters load; players list for a 2026 week is right |
| **M2** Picks ✔ | Submit, change, clear; lock and one-use enforcement; pick log; This week and My season screens | Lock and one-use tests pass against a moved clock |
| **M3** Scoring and standings ✔ | Ported scoring, play-by-play ingest, standings, week view, entrant page, visibility filter | A 2026 week scores identically to the selector for the same picks |
| **M4** Membership and admin | Invite link, approval, admin page, CSV export | A second Google account can join, be approved, and pick |
| **M5** Deploy and dry run | Single-origin deployment per README §3, backups, 2026 replay with real entrants' picks | Standings match the organizer's 2026 reports |

## 8. Verification

- **Unit:** scoring port against the selector's test cases (returns, laterals, negated plays,
  conversions, incomplete games); lock boundary at exactly 60 minutes; one-use across weeks;
  swap rules when either side is locked.
- **API:** visibility — entrant B never receives entrant A's unlocked pick from any endpoint.
- **Replay:** load 2026 data, enter one entrant's real picks, compare weekly TDs to
  `uv run pool picks` in the selector.
- **Manual:** run both dev servers, set the dev clock to a 2026 Thursday, and walk through
  pick → lock → reveal → score in the browser at phone width.
- `cd backend && pytest`; `cd frontend && npm run build`.

## 9. Open questions

None of these block M0–M2.

1. **Odd positions.** Is anyone ruled differently from his listed position? Default: the
   roster position decides, with overrides for exceptions. (Fullbacks need no ruling: the data
   lists them as RB.)
2. **Live scoring.** Is next-morning scoring acceptable for 2027, or is in-game scoring wanted?
3. **Reminders.** Email or push before a lock needs a sending service; left out of v1.
4. **Hosting.** Where this runs (a small VPS with a reverse proxy is assumed) and the domain.
5. **Admin edits after lock.** Allowed with an audit entry in this design; say if the organizer
   should not have that power.
6. **Money.** Entry fees and payouts are not tracked.
