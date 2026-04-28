"""
app/routers/monitor.py
----------------------
Admin-only DB monitoring endpoints.

Routes
------
  GET /dbstatus        — Serves the monitor HTML page.
                         • No session       → redirect to /auth/login
                         • Not admin        → styled 403 page
                         • Admin            → monitor.html

  GET /dbstatus/data   — Returns uploads + transcriptions tables as JSON.
                         Protected by get_admin_user dependency (401 / 403).
"""

import time
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, RedirectResponse

from app.auth.dependencies import get_admin_user
from app import database
from app.config import settings

router = APIRouter()

# Resolve ui/ directory relative to this file so it works from any cwd.
_UI_DIR = Path(__file__).parent.parent.parent / "ui"


@router.get("/dbstatus")
async def monitor_page(request: Request):
    """Serve the admin monitor page with a three-tier gate.

    Tier 1 — no SSO session  → redirect to Microsoft login
    Tier 2 — authenticated but not admin → styled 403 HTML page
    Tier 3 — admin → serve monitor.html
    """
    user = request.session.get("user")

    # Tier 1: not logged in at all
    if not user:
        return RedirectResponse("/auth/login")

    # Tier 2: logged in but not admin
    email = (user.get("email") or "").lower()
    if email not in settings.ADMIN_EMAILS:
        return FileResponse(
            _UI_DIR / "monitor_403.html",
            status_code=403,
        )

    # Tier 3: admin — serve the dashboard
    return FileResponse(_UI_DIR / "monitor.html")


@router.get("/dbstatus/data")
async def monitor_data(current_user: dict = Depends(get_admin_user)):
    """Return uploads + transcriptions tables as JSON.

    Response shape:
    {
        "uploads": [...],           // all upload rows (newest first)
        "total":        <int>,      // total upload records
        "pending":      <int>,      // is_processed == 0
        "in_progress":  <int>,      // is_processed == 2
        "processed":    <int>,      // is_processed == 1
        "failed":       <int>,      // is_processed == -1

        "transcriptions": [...],           // all transcription rows (newest first)
        "transcription_total":     <int>,
        "transcription_pending":   <int>,  // is_processed == 0
        "transcription_processed": <int>,  // is_processed == 1

        "generated_at": <int>   // Unix epoch seconds (server time)
    }
    """
    uploads = await database.fetch_all_uploads()
    transcriptions = await database.fetch_all_transcriptions()

    return {
        # uploads stats
        "uploads": uploads,
        "total": len(uploads),
        "pending": sum(1 for r in uploads if r["is_processed"] == 0),
        "in_progress": sum(1 for r in uploads if r["is_processed"] == 2),
        "processed": sum(1 for r in uploads if r["is_processed"] == 1),
        "failed": sum(1 for r in uploads if r["is_processed"] == -1),
        # transcriptions stats
        "transcriptions": transcriptions,
        "transcription_total": len(transcriptions),
        "transcription_pending": sum(
            1 for r in transcriptions if r["is_processed"] == 0
        ),
        "transcription_processed": sum(
            1 for r in transcriptions if r["is_processed"] == 1
        ),
        "generated_at": int(time.time()),
    }
