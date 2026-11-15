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
    # Comma-separated verified emails that become admins when they sign in.
    admin_emails: str = ""
    # Development only: freeze the app's clock at this ISO time (UTC if no offset),
    # e.g. 2026-09-17T20:00:00, to replay a past week. See app/clock.py.
    dev_now: str | None = None

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}


settings = Settings()
