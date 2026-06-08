"""
app/routers/user_files.py
-------------------------
Authenticated-user endpoints that serve the "My Files" page and its
JSON data feed.  Data comes from the remote PostgreSQL database.
"""

import time
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, RedirectResponse

from app.auth.dependencies import get_current_user
from app.services.user_data import fetch_user_data

router = APIRouter()

_UI_DIR = Path(__file__).parent.parent.parent / "ui"


@router.get("/myfiles")
async def myfiles_page(request: Request):
    """Serve the My Files page.  Redirects to login if not authenticated."""
    if not request.session.get("user"):
        return RedirectResponse("/auth/login")
    return FileResponse(_UI_DIR / "myfiles.html")


@router.get("/myfiles/data")
async def myfiles_data(current_user: dict = Depends(get_current_user)):
    """Return all five tables filtered by the logged-in user's email.

    Response shape
    --------------
    {
        "uploads":         [{file_name, is_processed, created_at}, …],
        "transcriptions":  [{summarized_content, is_processed}, …],
        "user_stories":    [{processed_description, is_processed}, …],
        "notifications":   [{message, is_processed}, …],
        "actions":         [{type, is_processed, timestamp}, …],
        "generated_at":    <int>,
    }
    """
    email = (current_user.get("email") or "").lower()
    return fetch_user_data(email)
