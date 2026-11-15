"""Getting into the pool: the invite link, the organizer's approval, and the weekly export."""

import csv
import io
import secrets
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import clock, rules
from .config import settings
from .db import get_db
from .deps import current_entry, current_user, find_entry, require_admin, require_csrf_header
from .models import Entry, Pick, Season, User
from .pool import MyEntryOut, my_entry_out, week_games
from .standings import approved_entries, picks_by_entry

router = APIRouter(prefix="/api")
admin = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])
WRITE = [Depends(require_csrf_header)]


def current_season(db: Session) -> Season:
    """The season row, created with a fresh invite token the first time it is needed."""
    season = db.get(Season, settings.season)
    if season is None:
        season = Season(year=settings.season, invite_token=secrets.token_urlsafe(16))
        db.add(season)
        try:
            db.commit()
        except IntegrityError:  # two first requests at once
            db.rollback()
            season = db.get(Season, settings.season)
    return season


def free_name(db: Session, wanted: str, *, ignore: Entry | None = None) -> str:
    """`wanted`, or `wanted 2`, `wanted 3`… if another entrant already has it."""
    taken = {
        e.display_name.lower()
        for e in db.scalars(select(Entry).where(Entry.season == settings.season))
        if e is not ignore
    }
    name, n = wanted, 1
    while name.lower() in taken:
        n += 1
        name = f"{wanted[:60]} {n}"
    return name


# --- joining ----------------------------------------------------------------
class JoinIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=64)


@router.post("/join/{token}", response_model=MyEntryOut, dependencies=WRITE)
def join(
    token: str,
    body: JoinIn | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Ask to join through the invite link. Pending until the organizer approves.

    An admin's own request is approved on the spot. Using the link again changes nothing.
    """
    if not secrets.compare_digest(token, current_season(db).invite_token):
        raise HTTPException(status_code=404, detail="This invite link is not valid")
    entry = find_entry(db, user)
    if entry is None:
        wanted = (body and body.display_name or "").strip() or user.name
        wanted = wanted or (user.email or "").split("@")[0] or f"Entrant {user.id}"
        entry = Entry(
            user_id=user.id,
            season=settings.season,
            display_name=free_name(db, wanted[:64]),
            status="approved" if user.is_admin else "pending",
        )
        db.add(entry)
        db.commit()
    return my_entry_out(entry)


# --- organizer --------------------------------------------------------------
class InviteOut(BaseModel):
    url: str


def invite_out(season: Season) -> InviteOut:
    return InviteOut(url=f"{settings.public_base_url}/join/{season.invite_token}")


@admin.get("/invite", response_model=InviteOut)
def invite(db: Session = Depends(get_db)):
    return invite_out(current_season(db))


@admin.post("/invite/rotate", response_model=InviteOut, dependencies=WRITE)
def rotate_invite(db: Session = Depends(get_db)):
    """Replace the invite link. The old one stops working; existing entrants are unaffected."""
    season = current_season(db)
    season.invite_token = secrets.token_urlsafe(16)
    db.commit()
    return invite_out(season)


class AdminEntryOut(BaseModel):
    entry_id: int
    display_name: str
    status: str
    email: str | None
    google_name: str | None
    created_at: datetime
    picks: int


class EntryPatch(BaseModel):
    status: Literal["pending", "approved", "removed"] | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=64)


def admin_entry_out(db: Session, entry: Entry) -> AdminEntryOut:
    user = db.get(User, entry.user_id)
    picks = len(db.scalars(select(Pick.id).where(Pick.entry_id == entry.id)).all())
    return AdminEntryOut(
        entry_id=entry.id, display_name=entry.display_name, status=entry.status,
        email=user.email, google_name=user.name, created_at=entry.created_at, picks=picks,
    )


@admin.get("/entries", response_model=list[AdminEntryOut])
def entries(db: Session = Depends(get_db)):
    """Everyone who has used the invite link, pending first."""
    order = {"pending": 0, "approved": 1, "removed": 2}
    rows = db.scalars(select(Entry).where(Entry.season == settings.season)).all()
    rows = sorted(rows, key=lambda e: (order[e.status], e.display_name.lower(), e.id))
    return [admin_entry_out(db, e) for e in rows]


@admin.patch("/entries/{entry_id}", response_model=AdminEntryOut, dependencies=WRITE)
def update_entry(entry_id: int, body: EntryPatch, db: Session = Depends(get_db)):
    """Approve, remove or rename an entrant. Removing keeps their picks but hides them
    from standings and blocks further picking; approving again restores them."""
    entry = db.get(Entry, entry_id)
    if entry is None or entry.season != settings.season:
        raise HTTPException(status_code=404, detail="Unknown entrant")
    if body.status:
        entry.status = body.status
    if body.display_name:
        name = body.display_name.strip()
        if name != free_name(db, name, ignore=entry):
            raise HTTPException(status_code=409, detail="Another entrant already has that name")
        entry.display_name = name
    db.commit()
    return admin_entry_out(db, entry)


# --- weekly export ----------------------------------------------------------
@router.get("/export/week/{week}.csv")
def export_week(
    week: int,
    db: Session = Depends(get_db),
    now: datetime = Depends(clock.now),
    _: Entry = Depends(current_entry),
) -> Response:
    """The week's locked picks as `week,entrant,QB,RB,FLEX`.

    This is the layout the selector's `pool report import` reads. An empty cell is a
    slot with no locked pick, so the file is only a complete report once the week has
    locked; before that it says nothing about slots that can still change.
    """
    week_games(db, settings.season, week)  # 404 for an unknown week
    entries = approved_entries(db)
    picks = picks_by_entry(db, entries)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["week", "entrant", *rules.SLOTS])
    for entry in entries:
        locked = {
            p.slot: p.player_name
            for p in picks[entry.id]
            if p.week == week and rules.is_locked(p.game, now)
        }
        writer.writerow([week, entry.display_name, *(locked.get(s, "") for s in rules.SLOTS)])
    return Response(
        out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="week{week}.csv"'},
    )
