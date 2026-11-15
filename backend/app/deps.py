from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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


def current_entry(user: User = Depends(current_user), db: Session = Depends(get_db)) -> Entry:
    """The signed-in user's entry in the current season.

    TEMPORARY until M4: anyone who signs in gets an approved entry on first use. M4
    replaces this with the invite link and the organizer's approval.
    """
    query = select(Entry).where(Entry.user_id == user.id, Entry.season == settings.season)
    entry = db.scalar(query)
    if entry is None:
        name = user.name or (user.email or "").split("@")[0] or f"Entrant {user.id}"
        entry = Entry(user_id=user.id, season=settings.season, display_name=name[:64])
        db.add(entry)
        try:
            db.commit()
        except IntegrityError:  # two first requests at once
            db.rollback()
            entry = db.scalar(query)
    if entry.status != "approved":
        raise HTTPException(status_code=403, detail="Your entry is not approved")
    return entry


def require_csrf_header(request: Request) -> None:
    """CSRF defence for state-changing requests.

    Browsers won't let a cross-site page add a custom header without a CORS preflight,
    and this app does not enable CORS. Combined with SameSite=Lax cookies this blocks
    cross-site forged requests. The frontend's `apiFetch` adds the header automatically.
    """
    if request.headers.get("x-requested-with") != "fetch":
        raise HTTPException(status_code=403, detail="Missing CSRF header")
