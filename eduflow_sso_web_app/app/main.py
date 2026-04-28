import uvicorn
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.routers.auth import router as auth_router
from app.routers.upload import router as upload_router
from app.routers.monitor import router as monitor_router
from app.auth.dependencies import get_current_user
from app import database
from app import scheduler
from app import sync_scheduler

# Resolve the ui/ directory relative to this file so it works regardless of
# the working directory the server is launched from.
UI_DIR = Path(__file__).parent.parent / "ui"


# --------------------------------------------------------------------------- #
# Lifespan                                                                     #
# Runs once at startup / once at shutdown for the entire process.             #
# In production (4 workers) every worker runs its own lifespan, but all       #
# calls here are idempotent so that is fine.                                  #
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure all storage directories exist.
    # Paths come from settings so they work for both `uv run serve` (relative
    # ./data, ./uploads) and Docker (absolute /data, /app/uploads via env vars).
    Path(settings.DATA_DIR).resolve().mkdir(parents=True, exist_ok=True)
    Path(settings.UPLOADS_DIR).resolve().mkdir(parents=True, exist_ok=True)
    Path(settings.TUS_UPLOADS_DIR).resolve().mkdir(parents=True, exist_ok=True)
    Path(settings.TRANSCRIPTIONS_DIR).resolve().mkdir(parents=True, exist_ok=True)

    # Initialise SQLite database (creates tables if not exist, runs migrations)
    await database.init_db()

    # Start the background transcription worker (1 thread per worker process)
    scheduler.start_scheduler()

    # Start the background R2 + Postgres sync worker (1 thread per worker process)
    sync_scheduler.start_scheduler()

    yield  # application runs here

    # Graceful shutdown: signal both worker threads and wait briefly
    scheduler.stop_scheduler()
    sync_scheduler.stop_scheduler()


app = FastAPI(title="Codeline SSO", version="1.0.0", lifespan=lifespan)

# --------------------------------------------------------------------------- #
# Session middleware                                                           #
# SessionMiddleware signs & encrypts the cookie with SESSION_SECRET_KEY.      #
# https_only is driven by the HTTPS_ONLY env var (default False) so local     #
# development works over plain HTTP.  Set HTTPS_ONLY=true in production.      #
# --------------------------------------------------------------------------- #
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SESSION_SECRET_KEY,
    session_cookie="session",
    max_age=3600 * 8,  # 8-hour session lifetime
    https_only=settings.HTTPS_ONLY,
    same_site="lax",  # Protects against CSRF while allowing top-level nav
)

# --------------------------------------------------------------------------- #
# Static files — ui/ directory served at /ui                                  #
# JS, CSS, and any future assets live here and are referenced as /ui/<file>   #
# --------------------------------------------------------------------------- #
app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")

# --------------------------------------------------------------------------- #
# Routers                                                                     #
# --------------------------------------------------------------------------- #
app.include_router(auth_router)
app.include_router(upload_router, prefix="/upload", tags=["upload"])
app.include_router(monitor_router, tags=["monitor"])


# --------------------------------------------------------------------------- #
# Root — serve the UI landing page                                            #
# --------------------------------------------------------------------------- #
@app.get("/")
async def root():
    return FileResponse(UI_DIR / "index.html")


# --------------------------------------------------------------------------- #
# Protected example route                                                     #
# --------------------------------------------------------------------------- #
@app.get("/protected")
async def protected_route(current_user: dict = Depends(get_current_user)):
    """Example endpoint that requires authentication."""
    return {
        "message": f"Access granted for {current_user['email']}",
        "user": current_user,
    }


def run() -> None:
    """Production entry point: `uv run serve`"""
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8090,
        workers=4,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


def dev() -> None:
    """Development entry point: `uv run dev`"""
    uvicorn.run("app.main:app", host="0.0.0.0", port=8090, reload=True)
