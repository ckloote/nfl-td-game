from alembic import context

from app import models  # noqa: F401  (register tables on Base.metadata)
from app.db import Base, engine

# Online only: the app's own engine, so migrations always hit DATABASE_URL.
# Logging is left alone on purpose; fileConfig would silence uvicorn's loggers
# when migrations run at startup.
with engine.connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        render_as_batch=True,  # SQLite can't ALTER most things in place
    )
    with context.begin_transaction():
        context.run_migrations()
