"""Submitting picks. The lock and one-use rules are enforced here, on every write.

Entrants write through `/api/weeks/...`. The organizer can write to anyone's slots
through `/api/admin/entries/{id}/weeks/...`, which skips the lock (and only the lock)
and records the admin as the actor in the pick log.
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import clock, rules, scoring
from .config import settings
from .db import get_db
from .deps import current_entry, current_user, require_admin, require_csrf_header
from .models import Entry, Pick, PickEvent, User
from .pool import PlayerOut, eligible_players, players_for, week_games

router = APIRouter(prefix="/api")
admin = APIRouter(prefix="/api/admin/entries/{entry_id}", dependencies=[Depends(require_admin)])
Slot = Literal["QB", "RB", "FLEX"]
WRITE = [Depends(require_csrf_header)]


class PickOut(BaseModel):
    week: int
    slot: str
    player_id: str
    name: str
    position: str
    team: str
    opponent: str
    home: bool
    game_id: str
    kickoff: datetime | None
    lock_at: datetime | None
    locked: bool
    # Touchdowns once the game is final. A locked pick with tds None is still pending,
    # and `pending` says why; an unlocked pick has neither.
    tds: int | None
    pending: str | None


class SlotOut(BaseModel):
    slot: str
    pick: PickOut | None
    # False once every game that week has locked: an empty slot stays empty.
    open: bool


class PickIn(BaseModel):
    player_id: str


def pick_out(pick: Pick, now: datetime, board: scoring.Board | None = None) -> PickOut:
    game = pick.game
    home = game.home_team == pick.team
    locked = rules.is_locked(game, now)
    tds, pending = scoring.score_pick(board, pick) if board and locked else (None, None)
    return PickOut(
        week=pick.week,
        slot=pick.slot,
        player_id=pick.player_id,
        name=pick.player_name,
        position=pick.position,
        team=pick.team,
        opponent=game.away_team if home else game.home_team,
        home=home,
        game_id=game.game_id,
        kickoff=game.kickoff,
        lock_at=rules.lock_at(game),
        locked=locked,
        tds=tds,
        pending=pending,
    )


def conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=409, detail=detail)


def slot_pick(db: Session, entry: Entry, week: int, slot: str) -> Pick | None:
    return db.scalar(
        select(Pick).where(Pick.entry_id == entry.id, Pick.week == week, Pick.slot == slot)
    )


# --- the three operations, for any entry ---------------------------------------
def week_slots(db: Session, entry: Entry, week: int, now: datetime) -> list[SlotOut]:
    games = set(week_games(db, settings.season, week).values())
    any_open = any(not rules.is_locked(g, now) for g in games)
    board = scoring.load_board(db, settings.season)
    out = []
    for slot in rules.SLOTS:
        pick = slot_pick(db, entry, week, slot)
        out.append(
            SlotOut(slot=slot, pick=pick_out(pick, now, board) if pick else None, open=any_open)
        )
    return out


def put_pick(
    db: Session, entry: Entry, week: int, slot: str, player_id: str, actor: User, now: datetime,
    *, enforce_lock: bool = True,
) -> PickOut:
    """Put a player in a slot, replacing whoever is there.

    Refused when the player has no game that week, plays the wrong position, or is
    already used anywhere else this season; and, unless `enforce_lock` is off, once
    either the current pick or the new player has locked.
    """
    candidates = {p.player_id: (p, g) for p, g in eligible_players(db, settings.season, week)}
    if player_id not in candidates:
        raise HTTPException(status_code=400, detail="That player has no game that week")
    player, game = candidates[player_id]
    if player.position not in rules.SLOTS[slot]:
        raise HTTPException(status_code=400, detail=f"A {player.position} cannot go in {slot}")

    current = slot_pick(db, entry, week, slot)
    if current and current.player_id == player.player_id:
        return pick_out(current, now)
    if enforce_lock:
        if current and rules.is_locked(current.game, now):
            raise conflict(f"{current.player_name} has locked; this slot can no longer change")
        if rules.is_locked(game, now):
            raise conflict(f"{player.name} has locked")
    elsewhere = db.scalar(
        select(Pick).where(Pick.entry_id == entry.id, Pick.player_id == player.player_id)
    )
    if elsewhere:
        raise conflict(f"{player.name} is already used in week {elsewhere.week}")

    old = current.player_id if current else None
    pick = current or Pick(entry_id=entry.id, week=week, slot=slot)
    pick.player_id = player.player_id
    pick.player_name = player.name
    pick.position = player.position
    pick.team = player.team
    pick.game_id = game.game_id
    pick.updated_at = now
    db.add(pick)
    db.add(
        PickEvent(
            entry_id=entry.id, week=week, slot=slot, old_player_id=old,
            new_player_id=player.player_id, actor_user_id=actor.id, at=now,
        )
    )
    try:
        db.commit()
    except IntegrityError:  # a second request raced this one past the checks above
        db.rollback()
        raise conflict("That pick conflicts with another one just made") from None
    db.refresh(pick)
    return pick_out(pick, now)


def remove_pick(
    db: Session, entry: Entry, week: int, slot: str, actor: User, now: datetime,
    *, enforce_lock: bool = True,
) -> Response:
    """Empty a slot and free its player."""
    week_games(db, settings.season, week)  # 404 for an unknown week
    pick = slot_pick(db, entry, week, slot)
    if pick:
        if enforce_lock and rules.is_locked(pick.game, now):
            raise conflict(f"{pick.player_name} has locked; this slot can no longer change")
        db.add(
            PickEvent(
                entry_id=entry.id, week=week, slot=slot, old_player_id=pick.player_id,
                new_player_id=None, actor_user_id=actor.id, at=now,
            )
        )
        db.delete(pick)
        db.commit()
    return Response(status_code=204)


# --- entrants: my own picks ------------------------------------------------------
@router.get("/picks/me", response_model=list[PickOut])
def my_picks(
    db: Session = Depends(get_db),
    now: datetime = Depends(clock.now),
    entry: Entry = Depends(current_entry),
):
    """All my picks this season, by week."""
    board = scoring.load_board(db, settings.season)
    picks = db.scalars(select(Pick).where(Pick.entry_id == entry.id).order_by(Pick.week, Pick.id))
    return [pick_out(p, now, board) for p in picks]


@router.get("/weeks/{week}/picks/me", response_model=list[SlotOut])
def my_week(
    week: int,
    db: Session = Depends(get_db),
    now: datetime = Depends(clock.now),
    entry: Entry = Depends(current_entry),
):
    """My three slots for a week, filled or not."""
    return week_slots(db, entry, week, now)


@router.put("/weeks/{week}/picks/{slot}", response_model=PickOut, dependencies=WRITE)
def set_pick(
    week: int,
    slot: Slot,
    body: PickIn,
    db: Session = Depends(get_db),
    now: datetime = Depends(clock.now),
    user: User = Depends(current_user),
    entry: Entry = Depends(current_entry),
):
    return put_pick(db, entry, week, slot, body.player_id, user, now)


@router.delete("/weeks/{week}/picks/{slot}", status_code=204, dependencies=WRITE)
def clear_pick(
    week: int,
    slot: Slot,
    db: Session = Depends(get_db),
    now: datetime = Depends(clock.now),
    user: User = Depends(current_user),
    entry: Entry = Depends(current_entry),
) -> Response:
    return remove_pick(db, entry, week, slot, user, now)


# --- organizer: anyone's picks, regardless of locks ------------------------------
def target_entry(entry_id: int, db: Session = Depends(get_db)) -> Entry:
    entry = db.get(Entry, entry_id)
    if entry is None or entry.season != settings.season:
        raise HTTPException(status_code=404, detail="Unknown entrant")
    return entry


@admin.get("/weeks/{week}/picks", response_model=list[SlotOut])
def admin_week(
    week: int,
    db: Session = Depends(get_db),
    now: datetime = Depends(clock.now),
    entry: Entry = Depends(target_entry),
):
    return week_slots(db, entry, week, now)


@admin.get("/weeks/{week}/players", response_model=list[PlayerOut])
def admin_players(
    week: int,
    slot: Slot,
    db: Session = Depends(get_db),
    now: datetime = Depends(clock.now),
    entry: Entry = Depends(target_entry),
):
    """The player list as that entrant would see it (their used players marked)."""
    return players_for(db, entry, week, slot, now)


@admin.put("/weeks/{week}/picks/{slot}", response_model=PickOut, dependencies=WRITE)
def admin_set_pick(
    week: int,
    slot: Slot,
    body: PickIn,
    db: Session = Depends(get_db),
    now: datetime = Depends(clock.now),
    user: User = Depends(current_user),
    entry: Entry = Depends(target_entry),
):
    """Set a pick for an entrant even after it has locked. Logged with the admin as actor."""
    return put_pick(db, entry, week, slot, body.player_id, user, now, enforce_lock=False)


@admin.delete("/weeks/{week}/picks/{slot}", status_code=204, dependencies=WRITE)
def admin_clear_pick(
    week: int,
    slot: Slot,
    db: Session = Depends(get_db),
    now: datetime = Depends(clock.now),
    user: User = Depends(current_user),
    entry: Entry = Depends(target_entry),
) -> Response:
    return remove_pick(db, entry, week, slot, user, now, enforce_lock=False)
