from authlib.integrations.starlette_client import OAuth
from app.config import settings

oauth = OAuth()

oauth.register(
    name="microsoft",
    client_id=settings.AZURE_CLIENT_ID,
    client_secret=settings.AZURE_CLIENT_SECRET,
    server_metadata_url=(
        f"https://login.microsoftonline.com/{settings.AZURE_TENANT_ID}"
        "/v2.0/.well-known/openid-configuration"
    ),
    client_kwargs={
        # openid  → ID token; email/profile → basic claims; offline_access → refresh token
        "scope": "openid email profile offline_access",
        "response_type": "code",
        # Validate ID token claims automatically
        "token_endpoint_auth_method": "client_secret_post",
    },
)
