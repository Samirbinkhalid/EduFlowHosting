import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # Azure AD / Microsoft Entra ID
    AZURE_CLIENT_ID: str = os.environ["AZURE_CLIENT_ID"]
    AZURE_CLIENT_SECRET: str = os.environ["AZURE_CLIENT_SECRET"]
    # Use "common" for multi-tenant, or your specific Tenant ID for single-tenant
    AZURE_TENANT_ID: str = os.getenv("AZURE_TENANT_ID", "common")

    # App
    APP_BASE_URL: str = os.getenv(
        "APP_BASE_URL", "https://mentormindweb.thedevrelay.com"
    )
    SESSION_SECRET_KEY: str = os.environ["SESSION_SECRET_KEY"]

    # Set to "true" in production (HTTPS).  Local dev defaults to False so
    # the session cookie is sent over plain HTTP without a TLS proxy.
    HTTPS_ONLY: bool = os.getenv("HTTPS_ONLY", "false").lower() == "true"

    # After successful login, redirect here
    POST_LOGIN_REDIRECT: str = os.getenv("POST_LOGIN_REDIRECT", "/")
    # After logout, redirect here
    POST_LOGOUT_REDIRECT: str = os.getenv("POST_LOGOUT_REDIRECT", "/")

    # ── Admin access ───────────────────────────────────────────────────────────
    # Comma-separated list of SSO email addresses that may access /dbstatus.
    # Comparison is case-insensitive.  Set ADMIN_EMAILS in the environment to
    # override (e.g. ADMIN_EMAILS=alice@example.com,bob@example.com).
    _admin_raw: str = os.getenv(
        "ADMIN_EMAILS", "syed.atyab@codeline.rihal.om,ikhlas.khusaibi@codeline.rihal.om"
    )
    ADMIN_EMAILS: list = [e.strip().lower() for e in _admin_raw.split(",") if e.strip()]

    # External webhook that authorises activated users.
    # Called as GET <USERS_URL>?email=<email>  →  200 = allowed, 404 = not activated.
    USERS_URL: str = os.getenv(
        "USERS_URL",
        "https://echoautomation.theworkpc.com/webhook/mentormindusers",
    )

    # ── Storage paths ──────────────────────────────────────────────────────
    # Defaults are relative to the working directory, which works for
    # `uv run serve` / `uv run dev` out of the box.
    # In Docker these are overridden to absolute volume-mount paths via
    # environment variables set in docker-compose.yml.

    # Directory that holds the SQLite database file (mentormind.db)
    DATA_DIR: str = os.getenv("DATA_DIR", "./data")

    # Directory where extracted .m4a audio files are stored persistently
    UPLOADS_DIR: str = os.getenv("UPLOADS_DIR", "./uploads")

    # Temporary directory used to assemble TUS upload chunks; safe to wipe
    # between restarts — in-flight uploads will simply restart from offset 0
    TUS_UPLOADS_DIR: str = os.getenv("TUS_UPLOADS_DIR", "/tmp/tus_uploads")

    # Directory where transcription .txt files are stored persistently
    TRANSCRIPTIONS_DIR: str = os.getenv("TRANSCRIPTIONS_DIR", "./transcriptions")

    # ── ElevenLabs ─────────────────────────────────────────────────────────
    ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")

    # ── Transcription scheduler ────────────────────────────────────────────
    # After this many consecutive failures the upload is marked is_processed=-1
    # and will no longer be retried automatically.
    MAX_TRANSCRIPTION_RETRIES: int = int(os.getenv("MAX_TRANSCRIPTION_RETRIES", "3"))

    # ── Cloudflare R2 (S3-compatible) ──────────────────────────────────────
    # Endpoint format: https://<account_id>.r2.cloudflarestorage.com
    R2_ENDPOINT_URL: str = os.getenv("R2_ENDPOINT_URL", "")
    R2_ACCESS_KEY_ID: str = os.getenv("R2_ACCESS_KEY_ID", "")
    R2_SECRET_ACCESS_KEY: str = os.getenv("R2_SECRET_ACCESS_KEY", "")
    R2_BUCKET_NAME: str = os.getenv("R2_BUCKET_NAME", "mentormindweb-audio-uploads")

    # ── Remote PostgreSQL ──────────────────────────────────────────────────
    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "")
    POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "n8ndb")
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "root")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "")

    # ── Sync scheduler (R2 + Postgres) ─────────────────────────────────────
    # After this many consecutive failures the transcription is marked
    # is_processed=-1 and will no longer be retried automatically.
    MAX_SYNC_RETRIES: int = int(os.getenv("MAX_SYNC_RETRIES", "3"))

    @property
    def redirect_uri(self) -> str:
        return f"{self.APP_BASE_URL}/auth"

    @property
    def microsoft_authorize_url(self) -> str:
        return f"https://login.microsoftonline.com/{self.AZURE_TENANT_ID}/oauth2/v2.0/authorize"

    @property
    def microsoft_token_url(self) -> str:
        return f"https://login.microsoftonline.com/{self.AZURE_TENANT_ID}/oauth2/v2.0/token"

    @property
    def microsoft_jwks_url(self) -> str:
        return f"https://login.microsoftonline.com/{self.AZURE_TENANT_ID}/discovery/v2.0/keys"


settings = Settings()
