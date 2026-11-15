import os
import tempfile

# Must be set before the app is imported (settings are read at import time).
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["GOOGLE_CLIENT_ID"] = "test-client-id"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-client-secret"
os.environ["PUBLIC_BASE_URL"] = "http://localhost:5173"
os.environ["ADMIN_EMAILS"] = "boss@example.com, Second@Example.com"
os.environ.pop("STATIC_DIR", None)
os.environ.pop("DEV_NOW", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from sqlalchemy import text  # noqa: E402

from app.db import Base, SessionLocal, engine, upgrade_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db():
    # Build the schema the way production does: from the migrations, not the models.
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    upgrade_db()


@pytest.fixture()
def client():
    with TestClient(app, follow_redirects=False) as c:
        yield c


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
