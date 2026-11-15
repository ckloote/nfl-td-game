from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_db
from .models import User


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


def require_csrf_header(request: Request) -> None:
    """CSRF defence for state-changing requests.

    Browsers won't let a cross-site page add a custom header without a CORS preflight,
    and this app does not enable CORS. Combined with SameSite=Lax cookies this blocks
    cross-site forged requests. The frontend's `apiFetch` adds the header automatically.
    """
    if request.headers.get("x-requested-with") != "fetch":
        raise HTTPException(status_code=403, detail="Missing CSRF header")
