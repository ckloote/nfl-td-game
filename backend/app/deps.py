from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Entry, User


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.get(User, user_id)
    if user is None:  # account deleted while a cookie was still alive
        request.session.clear()
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admins only")
    return user


def find_entry(db: Session, user: User) -> Entry | None:
    return db.scalar(
        select(Entry).where(Entry.user_id == user.id, Entry.season == settings.season)
    )


def current_entry(user: User = Depends(current_user), db: Session = Depends(get_db)) -> Entry:
    """The signed-in user's approved entry in the current season, or 403.

    Entries come from the invite link (`POST /api/join/{token}`) and the organizer's
    approval; nothing here creates one.
    """
    entry = find_entry(db, user)
    if entry is None or entry.status != "approved":
        raise HTTPException(status_code=403, detail="You don't have an approved entry in the pool")
    return entry


def require_csrf_header(request: Request) -> None:
    """CSRF defence for state-changing requests.

    Browsers won't let a cross-site page add a custom header without a CORS preflight,
    and this app does not enable CORS. Combined with SameSite=Lax cookies this blocks
    cross-site forged requests. The frontend's `apiFetch` adds the header automatically.
    """
    if request.headers.get("x-requested-with") != "fetch":
        raise HTTPException(status_code=403, detail="Missing CSRF header")
