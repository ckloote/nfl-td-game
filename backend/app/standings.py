"""What entrants can see of each other: standings, a week's picks, one entrant's season.

Every response here goes through `visible`: another entrant's pick is shown only once
it has locked. Before that it is indistinguishable from an empty slot.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import clock, rules, scoring
from .config import settings
from .db import get_db
from .deps import current_entry
from .models import Entry, Pick
from .picks import PickOut, pick_out
from .pool import week_games

router = APIRouter(prefix="/api")


def approved_entries(db: Session) -> list[Entry]:
    return list(
        db.scalars(
            select(Entry)
            .where(Entry.season == settings.season, Entry.status == "approved")
            .order_by(Entry.display_name, Entry.id)
        )
    )


def visible(pick: Pick, viewer: Entry, now: datetime) -> bool:
    """The one visibility rule: my own picks always, anyone else's once locked."""
    return pick.entry_id == viewer.id or rules.is_locked(pick.game, now)


def picks_by_entry(db: Session, entries: list[Entry]) -> dict[int, list[Pick]]:
    out: dict[int, list[Pick]] = {e.id: [] for e in entries}
    for pick in db.scalars(
        select(Pick).where(Pick.entry_id.in_(out)).order_by(Pick.week, Pick.id)
    ):
        out[pick.entry_id].append(pick)
    return out


# --- standings --------------------------------------------------------------
class StandingOut(BaseModel):
    entry_id: int
    name: str
    is_me: bool
    rank: int
    total: int  # touchdowns from picks that are final
    weeks: dict[int, int]  # week -> final touchdowns that week
    pending: int  # locked picks still waiting for a final
    used: int  # players spent (locked picks)


class StandingsOut(BaseModel):
    season: int
    current_week: int | None
    final_through: int  # last week, counting from week 1, whose games are all final
    provisional: bool  # some locked pick is still pending, so totals can still rise
    standings: list[StandingOut]


@router.get("/standings", response_model=StandingsOut)
def standings(
    db: Session = Depends(get_db),
    now: datetime = Depends(clock.now),
    me: Entry = Depends(current_entry),
):
    """Everyone ranked by touchdowns so far. Ties share a rank (1, 2, 2, 4)."""
    return compute_standings(db, now, me)


def compute_standings(db: Session, now: datetime, me: Entry | None = None) -> StandingsOut:
    """The standings as of `now`; `me` only decides which row is flagged as the viewer's."""
    board = scoring.load_board(db, settings.season)
    entries = approved_entries(db)
    picks = picks_by_entry(db, entries)
    rows = []
    for entry in entries:
        weeks: dict[int, int] = {}
        pending = used = 0
        for pick in picks[entry.id]:
            if not rules.is_locked(pick.game, now):
                continue  # not spent yet, and nobody else may know about it
            used += 1
            tds, _ = scoring.score_pick(board, pick)
            if tds is None:
                pending += 1
            else:
                weeks[pick.week] = weeks.get(pick.week, 0) + tds
        rows.append(
            StandingOut(
                entry_id=entry.id, name=entry.display_name, is_me=me is not None and entry.id == me.id,
                rank=0, total=sum(weeks.values()), weeks=weeks, pending=pending, used=used,
            )
        )
    rows.sort(key=lambda r: (-r.total, r.name.lower(), r.entry_id))
    for i, row in enumerate(rows):
        row.rank = rows[i - 1].rank if i and rows[i - 1].total == row.total else i + 1
    return StandingsOut(
        season=settings.season,
        current_week=rules.current_week(db, settings.season, now),
        final_through=board.final_through(),
        provisional=any(r.pending for r in rows),
        standings=rows,
    )


# --- a week's picks ---------------------------------------------------------
class WeekSlotOut(BaseModel):
    slot: str
    # "pick": shown. "hidden": not locked yet, so it may or may not exist.
    # "empty": the week has locked and nobody was picked; scores zero.
    state: str
    pick: PickOut | None


class WeekEntryOut(BaseModel):
    entry_id: int
    name: str
    is_me: bool
    slots: list[WeekSlotOut]
    tds: int  # final touchdowns this week
    pending: int


class WeekPicksOut(BaseModel):
    week: int
    final: bool  # every game this week is final
    entries: list[WeekEntryOut]


@router.get("/weeks/{week}/picks", response_model=WeekPicksOut)
def week_picks(
    week: int,
    db: Session = Depends(get_db),
    now: datetime = Depends(clock.now),
    me: Entry = Depends(current_entry),
):
    """Everyone's picks for a week, as far as each has locked."""
    games = set(week_games(db, settings.season, week).values())
    week_open = any(not rules.is_locked(g, now) for g in games)
    board = scoring.load_board(db, settings.season)
    entries = approved_entries(db)
    picks = picks_by_entry(db, entries)
    out = []
    for entry in entries:
        mine = {p.slot: p for p in picks[entry.id] if p.week == week and visible(p, me, now)}
        slots, tds, pending = [], 0, 0
        for slot in rules.SLOTS:
            pick = mine.get(slot)
            if pick is None:
                state = "hidden" if week_open and entry.id != me.id else "empty"
                slots.append(WeekSlotOut(slot=slot, state=state, pick=None))
                continue
            shown = pick_out(pick, now, board)
            slots.append(WeekSlotOut(slot=slot, state="pick", pick=shown))
            tds += shown.tds or 0
            pending += shown.locked and shown.tds is None
        out.append(
            WeekEntryOut(
                entry_id=entry.id, name=entry.display_name, is_me=entry.id == me.id,
                slots=slots, tds=tds, pending=pending,
            )
        )
    out.sort(key=lambda e: (-e.tds, e.name.lower(), e.entry_id))
    return WeekPicksOut(week=week, final=board.week_is_final(week), entries=out)


# --- one entrant ------------------------------------------------------------
class EntryOut(BaseModel):
    entry_id: int
    name: str
    is_me: bool
    total: int
    pending: int
    picks: list[PickOut]  # locked picks only, unless this is me


@router.get("/entries/{entry_id}", response_model=EntryOut)
def entry_detail(
    entry_id: int,
    db: Session = Depends(get_db),
    now: datetime = Depends(clock.now),
    me: Entry = Depends(current_entry),
):
    """One entrant's season: the picks that have locked, which are the players spent."""
    entry = db.get(Entry, entry_id)
    if entry is None or entry.season != settings.season or entry.status != "approved":
        raise HTTPException(status_code=404, detail="Unknown entrant")
    board = scoring.load_board(db, settings.season)
    shown = [
        pick_out(p, now, board) for p in picks_by_entry(db, [entry])[entry.id] if visible(p, me, now)
    ]
    return EntryOut(
        entry_id=entry.id,
        name=entry.display_name,
        is_me=entry.id == me.id,
        total=sum(p.tds or 0 for p in shown),
        pending=sum(1 for p in shown if p.locked and p.tds is None),
        picks=shown,
    )
