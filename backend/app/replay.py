"""Replay a season from the organizer's weekly reports, in a throwaway database.

    python -m app.replay ../../nfl-player-selector/data/reports \\
        --selector ../../nfl-player-selector

Builds a fresh database (never the app's own), loads the season's NFL data, creates a
placeholder user and an approved entry for every entrant named in the reports, and
enters each reported pick through `picks.put_pick`, the same code the organizer's
override uses, so the position and one-use rules apply. Then it prints the standings
the app computes and, given `--selector`, compares every pick's player and touchdowns
with what the selector computes for the same reports.

Exits 0 only when every pick was entered and nothing disagrees.

A report is a CSV in either layout the selector's `pool report import` reads:

    week,entrant,QB,RB,FLEX            one row per entrant
    entrant,slot,player_name           one row per slot; the week comes from weekN.csv

An empty cell is a no-pick. A name must match exactly one eligible player in that slot
that week, ignoring case and punctuation; anything else is reported, never guessed.

The app has no misplaced picks (the pool's rule 7): nobody can put a player in a slot
his position isn't eligible for. A report that names exactly one player at another
position is therefore not entered at all. The replay itself scores that slot zero,
counts the player as spent, and says so.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.replay", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("reports", type=Path, help="directory of weekN.csv report files")
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--db", type=Path, default=Path("replay.db"),
                        help="throwaway database file (default: replay.db)")
    parser.add_argument("--keep-data", action="store_true",
                        help="reuse the NFL data already in --db instead of downloading it")
    parser.add_argument("--selector", type=Path,
                        help="selector checkout to compare against (its reports must be imported)")
    return parser.parse_args()


if __name__ == "__main__":
    # Settings are read when app.db is imported, so the throwaway database has to be
    # chosen before any of the imports below.
    ARGS = _arguments()
    os.environ["DATABASE_URL"] = f"sqlite:///{ARGS.db.resolve()}"
    os.environ["SEASON"] = str(ARGS.season)
    os.environ["REFRESH_ENABLED"] = "false"
    os.environ.pop("DEV_NOW", None)

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from . import rules, scoring  # noqa: E402
from .config import settings  # noqa: E402
from .models import Entry, Identity, Pick, PickEvent, User  # noqa: E402
from .picks import put_pick  # noqa: E402
from .pool import eligible_players  # noqa: E402
from .standings import StandingsOut, compute_standings  # noqa: E402

SLOT_ALIASES = {"WR": "FLEX", "TE": "FLEX", "WR/TE": "FLEX"}
WEEK_FILE = re.compile(r"week(\d+)\.csv", re.IGNORECASE)


def normalize(name: str) -> str:
    """Lowercase letters, digits and spaces only: the selector's name key."""
    return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()


# --- reading reports ----------------------------------------------------------
@dataclass(frozen=True)
class ReportPick:
    week: int
    entrant: str  # as typed in the report
    slot: str
    player_name: str | None  # None: the entrant made no pick


def _slot(name: str) -> str | None:
    upper = name.strip().upper()
    upper = SLOT_ALIASES.get(upper, upper)
    return upper if upper in rules.SLOTS else None


def parse_report(text: str, week: int | None = None) -> list[ReportPick]:
    """One report file -> three picks per entrant. `week` is used when no column gives it."""
    rows = [r for r in csv.reader(text.lstrip("﻿").splitlines()) if any(c.strip() for c in r)]
    if not rows:
        raise ValueError("report is empty")
    header = [c.strip().lower() for c in rows[0]]
    if "entrant" not in header:
        raise ValueError("report has no entrant column")
    records = []
    for line, row in enumerate(rows[1:], 2):
        if len(row) != len(header):
            raise ValueError(f"row {line}: expected {len(header)} fields, got {len(row)}")
        records.append({k: v.strip() for k, v in zip(header, row)})
    if not records:
        raise ValueError("report has no picks")

    if "week" in header:
        weeks = {r["week"] for r in records}
        if len(weeks) != 1 or not next(iter(weeks)).isdecimal():
            raise ValueError("report must contain exactly one week")
        stated = int(weeks.pop())
        if week is not None and week != stated:
            raise ValueError(f"report says week {stated} but the file is named for week {week}")
        week = stated
    if week is None:
        raise ValueError("report has no week column and its name is not weekN.csv")

    wide = {column: slot for column in header if (slot := _slot(column))}
    cells: list[tuple[str, str, str]] = []  # entrant, slot, typed name
    if wide:
        if set(wide.values()) != set(rules.SLOTS) or len(wide) != len(rules.SLOTS):
            raise ValueError(f"report needs exactly one column for each of {list(rules.SLOTS)}")
        cells = [(r["entrant"], slot, r[column]) for r in records for column, slot in wide.items()]
    else:
        if not {"slot", "player_name"} <= set(header):
            raise ValueError("report needs QB, RB and FLEX columns, or slot and player_name")
        for r in records:
            slot = _slot(r["slot"])
            if slot is None:
                raise ValueError(f"unknown slot {r['slot']!r}")
            cells.append((r["entrant"], slot, r["player_name"]))

    seen: dict[str, set[str]] = {}
    picks = []
    for entrant, slot, name in cells:
        key = normalize(entrant)
        if not key:
            raise ValueError("report contains an empty entrant name")
        if slot in seen.setdefault(key, set()):
            raise ValueError(f"{entrant}: {slot} appears twice")
        seen[key].add(slot)
        picks.append(ReportPick(week, entrant, slot, name or None))
    for key, slots in seen.items():
        if missing := set(rules.SLOTS) - slots:
            raise ValueError(f"{key}: missing slots {sorted(missing)}")
    return picks


def read_reports(directory: Path) -> list[ReportPick]:
    """Every weekN.csv in the directory, in week order."""
    files = sorted(
        (int(m.group(1)), p) for p in directory.iterdir() if (m := WEEK_FILE.fullmatch(p.name))
    )
    if not files:
        raise ValueError(f"no weekN.csv files in {directory}")
    picks = []
    for week, path in files:
        try:
            picks += parse_report(path.read_text(encoding="utf-8"), week)
        except ValueError as exc:
            raise ValueError(f"{path.name}: {exc}") from exc
    return picks


# --- entering picks -----------------------------------------------------------
@dataclass
class Imported:
    entries: dict[str, Entry] = field(default_factory=dict)  # normalized name -> entry
    picks: int = 0
    no_picks: int = 0
    # Wrong-slot picks, which the app cannot hold: (entrant, week, slot) -> player.
    misplaced: dict[tuple[str, int, str], tuple[str, str]] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


def reset_pool(db: Session) -> None:
    """Remove everyone and everything they picked; NFL data is left alone."""
    for table in (PickEvent, Pick, Entry, Identity, User):
        db.execute(delete(table))
    db.commit()


def import_reports(db: Session, picks: list[ReportPick], now: datetime) -> Imported:
    """Create the entrants and enter their picks. Problems are collected, not raised."""
    season = settings.season
    out = Imported()
    actor = User(name="Replay")
    db.add(actor)
    for pick in picks:
        key = normalize(pick.entrant)
        if key not in out.entries:
            user = User(name=pick.entrant)
            db.add(user)
            db.flush()
            entry = Entry(
                user_id=user.id, season=season, display_name=pick.entrant, status="approved"
            )
            db.add(entry)
            out.entries[key] = entry
    db.commit()

    by_week: dict[int, dict[str, list]] = {}
    for pick in picks:
        where = f"week {pick.week} {pick.entrant} {pick.slot}"
        if pick.player_name is None:
            out.no_picks += 1
            continue
        if pick.week not in by_week:
            names: dict[str, list] = {}
            for player, _game in eligible_players(db, season, pick.week):
                names.setdefault(normalize(player.name), []).append(player)
            by_week[pick.week] = names
        if not by_week[pick.week]:
            out.problems.append(f"{where}: no schedule or rosters loaded for week {pick.week}")
            continue
        named = by_week[pick.week].get(normalize(pick.player_name), [])
        # Nobody of that name in the slot: one player of that name elsewhere is a
        # misplaced pick. Two would be a guess, so that stays a problem.
        matches = [p for p in named if p.position in rules.SLOTS[pick.slot]] or named
        if len(matches) != 1:
            if matches:
                detail = "is ambiguous: " + ", ".join(
                    f"{p.name} {p.position} {p.team}" for p in matches
                )
            else:
                detail = "matches no player with a game that week"
            out.problems.append(f"{where}: {pick.player_name!r} {detail}")
            continue
        player, key = matches[0], normalize(pick.entrant)
        entry = out.entries[key]
        spent = next(
            (w for (k, w, _), (pid, _) in out.misplaced.items() if k == key and pid == player.player_id),
            None,
        )
        if spent is not None:
            out.problems.append(
                f"{where}: {player.name} was spent by a misplaced pick in week {spent}"
            )
            continue
        if player.position not in rules.SLOTS[pick.slot]:
            used = db.scalar(
                select(Pick.week).where(Pick.entry_id == entry.id, Pick.player_id == player.player_id)
            )
            if used is not None:
                out.problems.append(f"{where}: {player.name} is already used in week {used}")
                continue
            out.misplaced[(key, pick.week, pick.slot)] = (
                player.player_id, f"{where}: {player.name} is a {player.position} ({player.team})"
            )
            continue
        try:
            put_pick(
                db, entry, pick.week, pick.slot, player.player_id, actor, now, enforce_lock=False,
            )
            out.picks += 1
        except HTTPException as exc:
            db.rollback()
            out.problems.append(f"{where}: {pick.player_name!r}: {exc.detail}")
    return out


# --- scores and comparison ----------------------------------------------------
@dataclass(frozen=True)
class Scored:
    """One slot's outcome, in the form both the app and the selector can be put in."""

    entrant: str  # normalized
    week: int
    slot: str
    player_id: str | None
    tds: int | None  # None while pending
    note: str = ""


def app_scores(db: Session, imported: Imported, reported: list[ReportPick], now: datetime) -> list[Scored]:
    """Every reported slot as the app scores it; a no-pick is a final zero."""
    board = scoring.load_board(db, settings.season)
    stored = {
        (p.entry_id, p.week, p.slot): p
        for p in db.scalars(select(Pick).where(Pick.entry_id.in_([e.id for e in imported.entries.values()])))
    }
    out = []
    for r in reported:
        key = normalize(r.entrant)
        pick = stored.get((imported.entries[key].id, r.week, r.slot))
        if r.player_name is None:
            out.append(Scored(key, r.week, r.slot, None, 0))
        elif (key, r.week, r.slot) in imported.misplaced:
            player_id, _ = imported.misplaced[(key, r.week, r.slot)]
            out.append(Scored(key, r.week, r.slot, player_id, 0, "misplaced"))
        elif pick is None:
            out.append(Scored(key, r.week, r.slot, None, None, "not entered"))
        elif not rules.is_locked(pick.game, now):
            out.append(Scored(key, r.week, r.slot, pick.player_id, None, "not locked yet"))
        else:
            tds, pending = scoring.score_pick(board, pick)
            out.append(Scored(key, r.week, r.slot, pick.player_id, tds, pending or ""))
    return out


def compare(ours: list[Scored], theirs: list[Scored]) -> list[str]:
    """Differences between the app's slots and the selector's; empty when they agree."""
    mine = {(s.entrant, s.week, s.slot): s for s in ours}
    other = {(s.entrant, s.week, s.slot): s for s in theirs}
    out = []
    for key in sorted(mine.keys() | other.keys(), key=lambda k: (k[1], k[0], k[2])):
        where = f"week {key[1]} {key[0]} {key[2]}"
        a, b = mine.get(key), other.get(key)
        if a is None:
            out.append(f"{where}: in the selector but not in the reports replayed")
        elif b is None:
            out.append(f"{where}: not in the selector; import that report there")
        elif a.player_id != b.player_id:
            notes = "".join(f" ({s.note})" for s in (a, b) if s.note)
            out.append(
                f"{where}: app has player {a.player_id}, selector has {b.player_id}{notes}"
            )
        elif a.tds != b.tds:
            def show(s: Scored) -> str:
                return f"pending ({s.note})" if s.tds is None else f"{s.tds} TD"
            out.append(f"{where}: app scores {show(a)}, selector scores {show(b)}")
    return out


SELECTOR_DUMP = """
import json, sys
from pool import db, standings
conn = db.connect(None)
print(json.dumps([
    dict(entrant=p.entrant_id, week=p.week, slot=p.slot, player_id=p.player_id,
         tds=p.tds, status=p.status, pending=p.pending, misplaced=p.misplaced)
    for p in standings.entrant_scores(conn, int(sys.argv[1]))
]))
"""


def selector_scores(checkout: Path, season: int) -> list[Scored]:
    """Ask the selector to score the reports it has imported. Runs `uv` in its checkout."""
    done = subprocess.run(
        ["uv", "run", "python", "-c", SELECTOR_DUMP, str(season)],
        cwd=checkout, capture_output=True, text=True,
    )
    if done.returncode:
        raise RuntimeError(f"selector failed:\n{done.stderr.strip()}")
    out = []
    for row in json.loads(done.stdout):
        note = "misplaced" if row["misplaced"] else row["pending"] or (
            "" if row["status"] == "final" else row["status"]
        )
        out.append(
            Scored(row["entrant"], row["week"], row["slot"], row["player_id"],
                   row["tds"] if row["status"] == "final" else None, note)
        )
    return out


# --- output -------------------------------------------------------------------
def standings_table(result: StandingsOut) -> str:
    weeks = sorted({w for row in result.standings for w in row.weeks})
    width = max([7, *(len(r.name) for r in result.standings)])
    lines = [f"{'Rank':>4}  {'Entrant':<{width}}  {'Total':>5}  " + " ".join(f"{'W%d' % w:>3}" for w in weeks)]
    for row in result.standings:
        cells = " ".join(f"{row.weeks.get(w, 0):>3}" for w in weeks)
        pending = f"  ({row.pending} pending)" if row.pending else ""
        lines.append(f"{row.rank:>4}  {row.name:<{width}}  {row.total:>5}  {cells}{pending}")
    return "\n".join(lines)


def main(args: argparse.Namespace) -> int:
    from . import ingest
    from .db import SessionLocal, upgrade_db

    if args.db.resolve() == Path("app.db").resolve():
        raise SystemExit("--db is the app's own database; pick another file")
    reported = read_reports(args.reports)
    if not args.keep_data:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{args.db}{suffix}").unlink(missing_ok=True)
    upgrade_db()
    if not args.keep_data:
        print(f"Loading {args.season} NFL data ...")
        for status in ingest.refresh(args.season):
            if status.error:
                raise SystemExit(f"{status.feed} failed to load: {status.error}")
            print(f"  {status.feed}: {status.rows} rows")

    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        reset_pool(db)
        imported = import_reports(db, reported, now)
        weeks = sorted({p.week for p in reported})
        print(
            f"\nWeeks {weeks[0]}-{weeks[-1]}: {len(imported.entries)} entrants, "
            f"{imported.picks} picks entered, {imported.no_picks} no-picks, "
            f"{len(imported.misplaced)} misplaced, "
            f"{len(imported.problems)} problems"
        )
        for _, line in imported.misplaced.values():
            print(f"  MISPLACED {line}; not entered, scores zero")
        for problem in imported.problems:
            print(f"  PROBLEM {problem}")
        result = compute_standings(db, now)
        print(f"\nStandings (final through week {result.final_through}"
              + (", provisional" if result.provisional else "") + ")")
        print(standings_table(result))
        ours = app_scores(db, imported, reported, now)

    differences: list[str] = []
    if args.selector:
        differences = compare(ours, selector_scores(args.selector, args.season))
        final = sum(s.tds is not None for s in ours)
        print(f"\nCompared {len(ours)} slots with the selector ({final} final): "
              + (f"{len(differences)} differences" if differences else "all agree"))
        for difference in differences:
            print(f"  DIFF {difference}")
    else:
        print("\nNot compared with the selector (no --selector given).")
    return 1 if imported.problems or differences else 0


if __name__ == "__main__":
    raise SystemExit(main(ARGS))
