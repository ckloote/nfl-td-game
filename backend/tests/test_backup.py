"""Backups: snapshot, upload, retention, restore, and what the Admin screen is told."""

import gzip
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import backup
from app.config import settings
from app.models import FeedStatus, User

CSRF = {"X-Requested-With": "fetch"}
NOW = datetime(2027, 9, 20, 8, 0, tzinfo=timezone.utc)


class FakeS3:
    """The four S3 calls the backup uses, kept in memory."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.fail: Exception | None = None

    def upload_file(self, path, bucket, key):
        if self.fail:
            raise self.fail
        assert bucket == "pool-backups"
        self.objects[key] = Path(path).read_bytes()

    def download_file(self, bucket, key, path):
        Path(path).write_bytes(self.objects[key])

    def delete_object(self, Bucket, Key):
        del self.objects[Key]

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        fake = self

        class Pages:
            def paginate(self, Bucket, Prefix):
                found = [{"Key": k, "Size": len(v)} for k, v in fake.objects.items() if k.startswith(Prefix)]
                return [{"Contents": found[:2]}, {"Contents": found[2:]}, {}]

        return Pages()


@pytest.fixture()
def s3(monkeypatch):
    monkeypatch.setattr(settings, "backup_s3_bucket", "pool-backups")
    return FakeS3()


def key(when: datetime) -> str:
    return f"backups/app-{when.strftime(backup.STAMP)}.db.gz"


def test_a_backup_round_trips_through_the_bucket(db, s3, tmp_path):
    db.add(User(email="ada@example.com", name="Ada"))
    db.commit()
    status = backup.run(db, s3)
    assert status.error is None and status.ok_at == status.attempted_at
    [(name, body)] = s3.objects.items()
    assert backup.KEY.search(name) and status.rows == len(body)
    assert gzip.decompress(body).startswith(b"SQLite format 3")

    restored = tmp_path / "restored.db"
    assert backup.restore(s3, restored).key == name
    with sqlite3.connect(restored) as conn:
        assert conn.execute("SELECT name FROM users").fetchall() == [("Ada",)]


def test_restore_writes_only_a_new_checked_file(db, s3, tmp_path):
    with pytest.raises(LookupError, match="no backups"):
        backup.restore(s3, tmp_path / "a.db")
    backup.run(db, s3)
    (tmp_path / "live.db").write_text("the live database")
    with pytest.raises(FileExistsError):
        backup.restore(s3, tmp_path / "live.db")
    with pytest.raises(LookupError, match="no backup 'backups/nope'"):
        backup.restore(s3, tmp_path / "b.db", "backups/nope")

    s3.objects[key(NOW + timedelta(days=400))] = gzip.compress(b"not a database at all")
    with pytest.raises(Exception):  # the newest is corrupt: nothing is written
        backup.restore(s3, tmp_path / "c.db")
    assert not (tmp_path / "c.db").exists()


def test_old_backups_are_pruned_but_never_the_newest(s3):
    for days in (40, 15, 14, 1):
        s3.objects[key(NOW - timedelta(days=days))] = b"x"
    s3.objects["backups/notes.txt"] = b"someone else's file"
    assert backup.prune(s3, NOW) == [key(NOW - timedelta(days=40)), key(NOW - timedelta(days=15))]
    assert [b.taken_at for b in backup.stored(s3)] == [NOW - timedelta(days=14), NOW - timedelta(days=1)]
    assert "backups/notes.txt" in s3.objects

    # Backups stopped a long time ago: the last one survives.
    later = NOW + timedelta(days=365)
    backup.prune(s3, later)
    assert [b.key for b in backup.stored(s3)] == [key(NOW - timedelta(days=1))]


def test_a_failed_backup_is_recorded_and_retried_sooner(db, s3):
    assert backup.is_due(None, NOW)
    good = backup.run(db, s3)
    first_ok = good.ok_at
    assert not backup.is_due(good, first_ok + timedelta(hours=23))
    assert backup.is_due(good, first_ok + timedelta(hours=24))

    s3.fail = ConnectionError("bucket unreachable")
    bad = backup.run(db, s3)
    assert bad.error == "ConnectionError: bucket unreachable"
    assert bad.ok_at == first_ok  # the last success is still on record
    assert not backup.is_due(bad, bad.attempted_at + timedelta(minutes=9))
    assert backup.is_due(bad, bad.attempted_at + timedelta(minutes=10))
    assert len(s3.objects) == 1


def test_backup_status_is_not_listed_among_the_nfl_feeds(client, login, db, s3):
    backup.run(db, s3)
    login("boss@example.com", entry=False)
    assert client.get("/api/admin/feeds").json() == []
    assert db.get(FeedStatus, backup.STATUS_KEY) is not None


def test_admin_sees_backup_status_and_can_run_one(client, login, monkeypatch, s3):
    login("ada@example.com")
    assert client.get("/api/admin/backup").status_code == 403
    assert client.post("/api/admin/backup", headers=CSRF).status_code == 403

    login("boss@example.com", entry=False)
    assert client.get("/api/admin/backup").json() == {
        "enabled": True, "keep_days": 14, "attempted_at": None, "ok_at": None, "size": None,
        "error": None,
    }
    monkeypatch.setattr(backup, "s3_client", lambda: s3)
    assert client.post("/api/admin/backup").status_code == 403  # CSRF
    done = client.post("/api/admin/backup", headers=CSRF).json()
    assert done["error"] is None and done["size"] == len(next(iter(s3.objects.values())))
    assert client.get("/api/admin/backup").json() == done

    monkeypatch.setattr(settings, "backup_s3_bucket", "")
    assert client.get("/api/admin/backup").json()["enabled"] is False
    assert client.post("/api/admin/backup", headers=CSRF).status_code == 409
