from typing import Optional

import httpx
from fastapi import Request, HTTPException, status

from app.config import settings


def get_current_user(request: Request) -> dict:
    """
    FastAPI dependency — injects the logged-in user from session.
    Raises 401 if the session has no user (i.e. not authenticated).
    """
    user: Optional[dict] = request.session.get("user")
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user


def get_optional_user(request: Request) -> Optional[dict]:
    """
    Same as get_current_user but returns None instead of raising,
    useful for pages that work for both guests and logged-in users.
    """
    return request.session.get("user")


def get_admin_user(request: Request) -> dict:
    """FastAPI dependency — admin-only gate.

    Requires:
      1. A valid SSO session (delegates to get_current_user → 401 if absent).
      2. The session email must be in settings.ADMIN_EMAILS (→ 403 if not).

    No external webhook is called — admin access is controlled entirely by
    the ADMIN_EMAILS env var, so it works offline and is instantaneous.
    """
    user = get_current_user(request)
    email = (user.get("email") or "").lower()
    if email not in settings.ADMIN_EMAILS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return user


async def get_authorized_user(request: Request) -> dict:
    """FastAPI dependency — two-factor authorisation gate.

    Step 1 — SSO session check (via get_current_user):
        Raises 401 if the user has no active Microsoft SSO session.

    Step 2 — Activation webhook check (USERS_URL):
        Calls GET <USERS_URL>?email=<email> to verify the user is activated
        in the external system.

        Response mapping:
          200       → authorised, return the user dict
          404       → account not activated → 403 Forbidden
          5xx       → authorisation service error → 503 Service Unavailable
          timeout   → authorisation service unreachable → 503

    This mirrors the same two-step check performed on the frontend in
    initAuth() / app.js so that the upload endpoint cannot be reached by
    SSO-authenticated-but-not-activated users.
    """
    # Step 1: must have a valid SSO session
    user = get_current_user(request)

    # Step 2: check activation webhook
    email = (user.get("email") or "").lower()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            perm_res = await client.get(
                settings.USERS_URL,
                params={"email": email},
            )

        if perm_res.status_code == 200:
            return user

        if perm_res.status_code == 404:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account not activated. Please ask Codeline to activate your account.",
            )

        # Any other non-200 (5xx, etc.)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authorisation service is temporarily unavailable. Please try again later.",
        )

    except HTTPException:
        raise  # re-raise our own HTTPExceptions unchanged

    except (httpx.TimeoutException, httpx.RequestError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authorisation service is temporarily unavailable. Please try again later.",
        )
