from authlib.integrations.starlette_client import OAuth
from app.config import settings

oauth = OAuth()

oauth.register(
    name="google",
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        # openid → ID token; email/profile → basic claims
        "scope": "openid email profile",
        "response_type": "code",
        "token_endpoint_auth_method": "client_secret_post",
    },
)
