from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .deps import current_user, require_csrf_header
from .models import Identity, User

router = APIRouter(prefix="/api")

# --- Providers ---------------------------------------------------------------
# Adding Microsoft later = one more `oauth.register(...)` and one more entry in
# PROVIDERS. The routes below are provider-agnostic (standard OIDC claims).
oauth = OAuth()
oauth.register(
    name="google",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    # Basic sign-in scopes only: no Google verification/security review needed.
    client_kwargs={"scope": "openid email profile"},
)
PROVIDERS = {"google"}


# --- Account logic -----------------------------------------------------------
def upsert_identity(
    db: Session,
    *,
    provider: str,
    subject: str,
    email: str | None,
    email_verified: bool,
    name: str | None,
    picture: str | None,
) -> User:
    """Find or create the user for a provider identity.

    - Known (provider, subject): log into that user.
    - Unknown identity with a *verified* email matching an existing user: link to it.
    - Otherwise: create a new user.
    Never links on an unverified email (that would allow account takeover).
    """
    verified_email = email if (email and email_verified) else None

    identity = db.scalar(
        select(Identity).where(Identity.provider == provider, Identity.subject == subject)
    )
    if identity is not None:
        user = identity.user
        identity.email = email
        identity.email_verified = email_verified
    else:
        user = None
        if verified_email:
            user = db.scalar(select(User).where(User.email == verified_email))
        if user is None:
            user = User(email=verified_email)
            db.add(user)
        user.identities.append(
            Identity(provider=provider, subject=subject, email=email, email_verified=email_verified)
        )

    # Keep profile fields fresh on every login.
    if verified_email and user.email is None:
        user.email = verified_email
    # ADMIN_EMAILS only ever grants; removing an address does not demote anyone.
    if verified_email and verified_email.lower() in settings.admin_email_set:
        user.is_admin = True
    if name:
        user.name = name
    if picture:
        user.picture = picture
    db.flush()
    return user


# --- Routes ------------------------------------------------------------------
class UserOut(BaseModel):
    id: int
    email: str | None
    name: str | None
    picture: str | None
    is_admin: bool

    model_config = {"from_attributes": True}


def _client(provider: str):
    if provider not in PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown provider")
    return oauth.create_client(provider)


@router.get("/auth/{provider}/login")
async def login(provider: str, request: Request):
    client = _client(provider)
    redirect_uri = f"{settings.public_base_url}/api/auth/{provider}/callback"
    return await client.authorize_redirect(request, redirect_uri)


@router.get("/auth/{provider}/callback")
async def callback(provider: str, request: Request, db: Session = Depends(get_db)):
    client = _client(provider)
    try:
        token = await client.authorize_access_token(request)
    except OAuthError:
        return RedirectResponse("/?login_error=1", status_code=303)

    claims = token.get("userinfo")
    if not claims or not claims.get("sub"):
        return RedirectResponse("/?login_error=1", status_code=303)

    user = upsert_identity(
        db,
        provider=provider,
        subject=claims["sub"],
        email=claims.get("email"),
        email_verified=bool(claims.get("email_verified")),
        name=claims.get("name"),
        picture=claims.get("picture"),
    )
    db.commit()

    request.session.clear()  # drop OAuth state; start a fresh session
    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=303)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> User:
    return user


@router.post("/auth/logout", status_code=204, dependencies=[Depends(require_csrf_header)])
def logout(request: Request) -> Response:
    request.session.clear()
    return Response(status_code=204)
