from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from .auth import router as auth_router
from .config import DEV_SESSION_SECRET, settings
from .db import upgrade_db

if settings.cookie_secure and settings.session_secret == DEV_SESSION_SECRET:
    raise RuntimeError("Set a real SESSION_SECRET when COOKIE_SECURE is enabled.")


@asynccontextmanager
async def lifespan(_: FastAPI):
    upgrade_db()
    yield


app = FastAPI(title="NFL TD pool", lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    max_age=60 * 60 * 24 * 14,  # 14 days
    same_site="lax",  # Lax is required so the cookie survives Google's redirect back
    https_only=settings.cookie_secure,
)

app.include_router(auth_router)


@app.get("/api/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


class SPAStaticFiles(StaticFiles):
    """Serve index.html for client-side routes (/standings, /season, ...)."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not path.startswith("api"):
                return await super().get_response("index.html", scope)
            raise


# Optionally serve the built React app from FastAPI (single-origin deployment).
if settings.static_dir and Path(settings.static_dir).is_dir():
    app.mount("/", SPAStaticFiles(directory=settings.static_dir, html=True), name="spa")
