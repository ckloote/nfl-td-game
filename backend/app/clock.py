"""The app's idea of "now".

Every lock and visibility check takes the time from this dependency rather than
calling datetime.now() itself, so tests can move the clock and a developer can
replay a past week by setting DEV_NOW.
"""

from datetime import datetime, timezone

from .config import settings


def now() -> datetime:
    if settings.dev_now:
        fixed = datetime.fromisoformat(settings.dev_now)
        return fixed if fixed.tzinfo else fixed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)
