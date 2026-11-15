from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SESSION_SECRET = "dev-only-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    google_client_id: str = ""
    google_client_secret: str = ""
    session_secret: str = DEV_SESSION_SECRET
    # Browser-facing origin. Used to build the OAuth redirect URI explicitly so it
    # doesn't depend on Host/X-Forwarded-* headers behind a proxy.
    public_base_url: str = "http://localhost:5173"
    cookie_secure: bool = False
    database_url: str = "sqlite:///./app.db"
    static_dir: str | None = None
    # The NFL season the pool is playing.
    season: int = 2026
    # Download NFL data on a timer while the server runs. Off in tests.
    refresh_enabled: bool = True
    # Comma-separated verified emails that become admins when they sign in.
    admin_emails: str = ""
    # Development only: freeze the app's clock at this ISO time (UTC if no offset),
    # e.g. 2026-09-17T20:00:00, to replay a past week. See app/clock.py.
    dev_now: str | None = None
    # Nightly off-site backups (app/backup.py), on when the bucket is set. Any
    # S3-compatible store works; the endpoint is its API URL (blank for AWS itself).
    backup_s3_bucket: str = ""
    backup_s3_endpoint: str = ""
    backup_s3_region: str = "auto"
    backup_s3_access_key_id: str = ""
    backup_s3_secret_access_key: str = ""
    backup_keep_days: int = 14

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}


def production_problem(s: Settings) -> str | None:
    """Why these settings must not serve real users, or None when they may.

    COOKIE_SECURE marks a real deployment. It must not run with the development
    session secret (anyone could forge a login) or a frozen clock (no pick would lock).
    """
    if not s.cookie_secure:
        return None
    if s.session_secret == DEV_SESSION_SECRET:
        return "Set a real SESSION_SECRET when COOKIE_SECURE is enabled."
    if s.dev_now:
        return "DEV_NOW freezes the clock; remove it when COOKIE_SECURE is enabled."
    return None


settings = Settings()
