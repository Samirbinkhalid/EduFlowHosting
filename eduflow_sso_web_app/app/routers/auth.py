from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from authlib.integrations.base_client import OAuthError

from app.auth.oauth_client import oauth
from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
async def login(request: Request):
    """
    Redirect the browser to Google's login page.
    authlib stores a one-time 'state' nonce in the session automatically
    to protect against CSRF.
    """
    redirect_uri = settings.redirect_uri
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/")
async def auth_callback(request: Request):
    """
    Google redirects here after the user authenticates.
    authlib validates the state, exchanges the code for tokens,
    and verifies the ID token signature & claims automatically.
    """
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as exc:
        # Could be a CSRF mismatch, user cancellation, or misconfiguration
        return RedirectResponse(
            url=f"{settings.POST_LOGOUT_REDIRECT}?error={exc.error}"
        )

    # The ID token is already parsed and validated by authlib
    user_info: dict = token.get("userinfo") or {}

    # Persist only what you need in the encrypted, signed cookie session
    request.session["user"] = {
        "sub": user_info.get("sub"),           # unique Google subject ID
        "email": user_info.get("email"),
        "name": user_info.get("name"),
        "given_name": user_info.get("given_name"),
        "family_name": user_info.get("family_name"),
    }

    return RedirectResponse(url=settings.POST_LOGIN_REDIRECT)


@router.get("/logout")
async def logout(request: Request):
    """
    Clear the local session and redirect to the post-logout page.
    Google does not provide a front-channel SSO logout endpoint,
    so only the local session is cleared.
    """
    request.session.clear()
    return RedirectResponse(url=settings.POST_LOGOUT_REDIRECT)


@router.get("/me")
async def me(request: Request):
    """
    Returns the currently authenticated user from the session.
    Useful for JavaScript clients / SPAs to check login state.
    """
    user = request.session.get("user")
    if not user:
        return {"authenticated": False}
    return {"authenticated": True, "user": user}
