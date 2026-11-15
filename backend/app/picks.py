"""Submitting picks. The lock and one-use rules are enforced here, on every write."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import clock, rules
from .config import settings
from .db import get_db
from .deps import current_entry, current_user, require_csrf_header
from .models import Entry, Pick, PickEvent, User
from .pool import eligible_players, week_games

router = APIRouter(prefix="/api")
Slot = Literal["QB", "RB", "FLEX"]


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


class SlotOut(BaseModel):
    slot: str
    pick: PickOut | None
    # False once every game that week has locked: an empty slot stays empty.
    open: bool


class PickIn(BaseModel):
    player_id: str


def pick_out(pick: Pick, now: datetime) -> PickOut:
    game = pick.game
    home = game.home_team == pick.team
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
        locked=rules.is_locked(game, now),
    )


def conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=409, detail=detail)


def slot_pick(db: Session, entry: Entry, week: int, slot: str) -> Pick | None:
    return db.scalar(
        select(Pick).where(Pick.entry_id == entry.id, Pick.week == week, Pick.slot == slot)
    )


@router.get("/picks/me", response_model=list[PickOut])
def my_picks(
    db: Session = Depends(get_db),
    now: datetime = Depends(clock.now),
    entry: Entry = Depends(current_entry),
):
    """All my picks this season, by week."""
    picks = db.scalars(select(Pick).where(Pick.entry_id == entry.id).order_by(Pick.week, Pick.id))
    return [pick_out(p, now) for p in picks]


@router.get("/weeks/{week}/picks/me", response_model=list[SlotOut])
def my_week(
    week: int,
    db: Session = Depends(get_db),
    now: datetime = Depends(clock.now),
    entry: Entry = Depends(current_entry),
):
    """My three slots for a week, filled or not."""
    games = set(week_games(db, settings.season, week).values())
    any_open = any(not rules.is_locked(g, now) for g in games)
    out = []
    for slot in rules.SLOTS:
        pick = slot_pick(db, entry, week, slot)
        out.append(SlotOut(slot=slot, pick=pick_out(pick, now) if pick else None, open=any_open))
    return out


@router.put(
    "/weeks/{week}/picks/{slot}",
    response_model=PickOut,
    dependencies=[Depends(require_csrf_header)],
)
def set_pick(
    week: int,
    slot: Slot,
    body: PickIn,
    db: Session = Depends(get_db),
    now: datetime = Depends(clock.now),
    user: User = Depends(current_user),
    entry: Entry = Depends(current_entry),
):
    """Put a player in a slot, replacing whoever is there.

    Refused once either the current pick or the new player has locked, and when the
    player is already used anywhere else this season.
    """
    candidates = {p.player_id: (p, g) for p, g in eligible_players(db, settings.season, week)}
    if body.player_id not in candidates:
        raise HTTPException(status_code=400, detail="That player has no game that week")
    player, game = candidates[body.player_id]
    if player.position not in rules.SLOTS[slot]:
        raise HTTPException(status_code=400, detail=f"A {player.position} cannot go in {slot}")

    current = slot_pick(db, entry, week, slot)
    if current and current.player_id == player.player_id:
        return pick_out(current, now)
    if current and rules.is_locked(current.game, now):
        raise conflict(f"{current.player_name} has locked; this slot can no longer change")
    if rules.is_locked(game, now):
        raise conflict(f"{player.name} has locked")
    elsewhere = db.scalar(
        select(Pick).where(Pick.entry_id == entry.id, Pick.player_id == player.player_id)
    )
    if elsewhere:
        raise conflict(f"You already have {player.name} in week {elsewhere.week}")

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
            new_player_id=player.player_id, actor_user_id=user.id, at=now,
        )
    )
    try:
        db.commit()
    except IntegrityError:  # a second request raced this one past the checks above
        db.rollback()
        raise conflict("That pick conflicts with another you just made") from None
    db.refresh(pick)
    return pick_out(pick, now)


@router.delete(
    "/weeks/{week}/picks/{slot}", status_code=204, dependencies=[Depends(require_csrf_header)]
)
def clear_pick(
    week: int,
    slot: Slot,
    db: Session = Depends(get_db),
    now: datetime = Depends(clock.now),
    user: User = Depends(current_user),
    entry: Entry = Depends(current_entry),
) -> Response:
    """Empty a slot and free its player. Refused once the pick has locked."""
    week_games(db, settings.season, week)  # 404 for an unknown week
    pick = slot_pick(db, entry, week, slot)
    if pick:
        if rules.is_locked(pick.game, now):
            raise conflict(f"{pick.player_name} has locked; this slot can no longer change")
        db.add(
            PickEvent(
                entry_id=entry.id, week=week, slot=slot, old_player_id=pick.player_id,
                new_player_id=None, actor_user_id=user.id, at=now,
            )
        )
        db.delete(pick)
        db.commit()
    return Response(status_code=204)
