"""Nightly off-site backups of the SQLite database.

While the server runs, once a day it takes a consistent snapshot of the database,
compresses it and uploads it to an S3-compatible bucket (Cloudflare R2, Backblaze B2,
AWS S3, ...), then deletes uploads older than BACKUP_KEEP_DAYS. Backups are on when
BACKUP_S3_BUCKET is set. The outcome of the latest attempt is kept in `feed_status`
(feed "backup") and shown on the Admin screen.

By hand, from backend/:

    python -m app.backup now                     take and upload a backup
    python -m app.backup list                    what is in the bucket
    python -m app.backup restore --to file.db    download the newest (or --key ...)

`restore` never touches the live database: it writes a new file and checks it. To use
it, point DATABASE_URL at that file and restart. See README, "Backups".
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import logging
import re
import shutil
import sqlite3
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal, engine, get_db
from .deps import require_admin, require_csrf_header
from .models import FeedStatus

log = logging.getLogger(__name__)

FEED = "backup"
STATUS_KEY = (FEED, 0)  # not tied to a season
PREFIX = "backups/"
STAMP = "%Y%m%dT%H%M%SZ"
KEY = re.compile(r"app-(\d{8}T\d{6}Z)\.db\.gz$")
EVERY = timedelta(hours=24)
RETRY_AFTER = timedelta(minutes=10)
CHECK_EVERY_SECONDS = 300

_running = threading.Lock()


def enabled() -> bool:
    return bool(settings.backup_s3_bucket)


def s3_client():
    """A client for the configured bucket's endpoint."""
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=settings.backup_s3_endpoint or None,
        aws_access_key_id=settings.backup_s3_access_key_id,
        aws_secret_access_key=settings.backup_s3_secret_access_key,
        region_name=settings.backup_s3_region,
        # Newer SDKs add checksum headers that some S3-compatible stores reject.
        config=Config(
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            retries={"max_attempts": 3},
        ),
    )


def _utcnow() -> datetime:
    # Backups are about the real world, so this ignores the DEV_NOW clock.
    return datetime.now(timezone.utc)


# --- snapshot -----------------------------------------------------------------
def database_path() -> Path:
    if engine.url.get_backend_name() != "sqlite" or not engine.url.database:
        raise RuntimeError("backups only know how to copy a SQLite database file")
    return Path(engine.url.database)


def check(path: Path) -> None:
    """Raise unless the file is a healthy SQLite database with the app's tables in it."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"integrity check failed: {result}")
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'alembic_version'").fetchone():
            raise RuntimeError("not this app's database (no alembic_version table)")
    finally:
        conn.close()


def snapshot(dest: Path) -> None:
    """A consistent copy of the live database, safe to take while the app is writing."""
    conn = sqlite3.connect(database_path())
    try:
        conn.execute("VACUUM INTO ?", (str(dest),))
    finally:
        conn.close()
    check(dest)


# --- the bucket ---------------------------------------------------------------
@dataclass(frozen=True)
class Stored:
    key: str
    taken_at: datetime
    size: int


def stored(s3) -> list[Stored]:
    """Every backup in the bucket, oldest first. Objects not named like one are ignored."""
    out = []
    for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=settings.backup_s3_bucket, Prefix=PREFIX
    ):
        for item in page.get("Contents", []):
            if match := KEY.search(item["Key"]):
                taken = datetime.strptime(match.group(1), STAMP).replace(tzinfo=timezone.utc)
                out.append(Stored(item["Key"], taken, item["Size"]))
    return sorted(out, key=lambda b: b.taken_at)


def prune(s3, now: datetime) -> list[str]:
    """Delete backups older than BACKUP_KEEP_DAYS. The newest is kept whatever its age."""
    cutoff = now - timedelta(days=settings.backup_keep_days)
    old = [b.key for b in stored(s3)[:-1] if b.taken_at < cutoff]
    for key in old:
        s3.delete_object(Bucket=settings.backup_s3_bucket, Key=key)
    return old


def upload(s3, now: datetime) -> Stored:
    """Snapshot, compress and upload. Returns what was stored."""
    key = f"{PREFIX}app-{now.strftime(STAMP)}.db.gz"
    with tempfile.TemporaryDirectory() as tmp:
        raw, packed = Path(tmp) / "snapshot.db", Path(tmp) / "snapshot.db.gz"
        snapshot(raw)
        with raw.open("rb") as src, gzip.open(packed, "wb") as dst:
            shutil.copyfileobj(src, dst)
        s3.upload_file(str(packed), settings.backup_s3_bucket, key)
        return Stored(key, now, packed.stat().st_size)


def restore(s3, to: Path, key: str | None = None) -> Stored:
    """Download a backup (the newest unless `key` is given) to a new file and check it."""
    if to.exists():
        raise FileExistsError(f"{to} already exists; restore writes a new file")
    available = stored(s3)
    chosen = next((b for b in available if b.key == key), None) if key else (available or [None])[-1]
    if chosen is None:
        raise LookupError(f"no backup {key!r} in the bucket" if key else "the bucket has no backups")
    with tempfile.TemporaryDirectory() as tmp:
        packed, raw = Path(tmp) / "download.db.gz", Path(tmp) / "download.db"
        s3.download_file(settings.backup_s3_bucket, chosen.key, str(packed))
        with gzip.open(packed, "rb") as src, raw.open("wb") as dst:
            shutil.copyfileobj(src, dst)
        check(raw)
        shutil.move(raw, to)
    return chosen


# --- running and recording ----------------------------------------------------
def run(db: Session, s3=None) -> FeedStatus:
    """Take a backup now and record how it went. A failure is recorded, not raised."""
    started = _utcnow()
    error = size = None
    try:
        if not enabled():
            raise RuntimeError("backups are not configured (BACKUP_S3_BUCKET is not set)")
        s3 = s3 or s3_client()
        size = upload(s3, started).size
        prune(s3, started)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        log.warning("backup failed: %s", error)
    status = db.get(FeedStatus, STATUS_KEY) or FeedStatus(feed=FEED, season=0)
    status.attempted_at = started
    status.error = error
    if error is None:
        status.ok_at, status.rows = started, size  # rows holds the upload's size in bytes
    db.add(status)
    db.commit()
    return status


def is_due(status: FeedStatus | None, now: datetime) -> bool:
    if status is None:
        return True
    if status.error:
        return now - status.attempted_at >= RETRY_AFTER
    return status.ok_at is None or now - status.ok_at >= EVERY


def run_if_due() -> None:
    if not _running.acquire(blocking=False):
        return
    try:
        with SessionLocal() as db:
            if is_due(db.get(FeedStatus, STATUS_KEY), _utcnow()):
                run(db)
    finally:
        _running.release()


async def backup_loop() -> None:
    """Back up once a day while the server runs. Started from the app's lifespan."""
    while True:
        try:
            await asyncio.to_thread(run_if_due)
        except Exception:
            log.exception("scheduled backup failed")
        await asyncio.sleep(CHECK_EVERY_SECONDS)


# --- admin --------------------------------------------------------------------
admin = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


class BackupOut(BaseModel):
    enabled: bool
    keep_days: int
    attempted_at: datetime | None
    ok_at: datetime | None
    size: int | None  # bytes uploaded by the last success
    error: str | None


def backup_out(status: FeedStatus | None) -> BackupOut:
    return BackupOut(
        enabled=enabled(),
        keep_days=settings.backup_keep_days,
        attempted_at=status.attempted_at if status else None,
        ok_at=status.ok_at if status else None,
        size=status.rows if status else None,
        error=status.error if status else None,
    )


@admin.get("/backup", response_model=BackupOut)
def backup_status(db: Session = Depends(get_db)):
    return backup_out(db.get(FeedStatus, STATUS_KEY))


@admin.post("/backup", response_model=BackupOut, dependencies=[Depends(require_csrf_header)])
async def backup_now(db: Session = Depends(get_db)):
    """Take a backup now. A failure comes back in `error`, as it does for the nightly one."""
    if not enabled():
        raise HTTPException(status_code=409, detail="Backups are not configured")
    return backup_out(await run_in_threadpool(run, db))


# --- command line -------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.backup", description="Database backups.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("now", help="take and upload a backup")
    commands.add_parser("list", help="list the backups in the bucket")
    restoring = commands.add_parser("restore", help="download a backup to a new file")
    restoring.add_argument("--to", type=Path, required=True, help="file to write (must not exist)")
    restoring.add_argument("--key", help="which backup (default: the newest)")
    args = parser.parse_args()
    if not enabled():
        raise SystemExit("Backups are not configured: set BACKUP_S3_BUCKET and its credentials.")

    if args.command == "now":
        with SessionLocal() as db:
            status = run(db)
        print(f"FAILED: {status.error}" if status.error else f"Uploaded {status.rows} bytes")
        return 1 if status.error else 0
    s3 = s3_client()
    if args.command == "list":
        for b in stored(s3):
            print(f"{b.taken_at:%Y-%m-%d %H:%M} UTC  {b.size:>10}  {b.key}")
        return 0
    chosen = restore(s3, args.to, args.key)
    print(f"Restored {chosen.key} to {args.to} (integrity check passed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
