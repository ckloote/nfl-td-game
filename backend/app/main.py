import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from . import backup
from .auth import router as auth_router
from .config import production_problem, settings
from .db import upgrade_db
from .ingest import refresh_loop
from .membership import admin as membership_admin_router
from .membership import router as membership_router
from .picks import admin as picks_admin_router
from .picks import router as picks_router
from .pool import admin as admin_router
from .pool import router as pool_router
from .standings import router as standings_router

if problem := production_problem(settings):
    raise RuntimeError(problem)


@asynccontextmanager
async def lifespan(_: FastAPI):
    upgrade_db()
    refresher = asyncio.create_task(refresh_loop()) if settings.refresh_enabled else None
    backups = asyncio.create_task(backup.backup_loop()) if backup.enabled() else None
    yield
    for task in (refresher, backups):
        if task:
            task.cancel()


app = FastAPI(title="NFL TD pool", lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    max_age=60 * 60 * 24 * 14,  # 14 days
    same_site="lax",  # Lax is required so the cookie survives Google's redirect back
    https_only=settings.cookie_secure,
)

app.include_router(auth_router)
app.include_router(pool_router)
app.include_router(picks_router)
app.include_router(standings_router)
app.include_router(membership_router)
app.include_router(membership_admin_router)
app.include_router(picks_admin_router)
app.include_router(admin_router)
app.include_router(backup.admin)


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
