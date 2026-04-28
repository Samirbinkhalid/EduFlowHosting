"""
app/services/r2_upload.py
--------------------------
Thin wrapper around boto3 for uploading transcription text to Cloudflare R2.

The boto3 S3 client is module-level (instantiated once per process) because it
is thread-safe and relatively expensive to construct.

Usage
-----
    from app.services.r2_upload import upload_transcription
    upload_transcription(uuid, text, user_name, user_email, created_at_epoch)

Object layout
-------------
    Bucket : settings.R2_BUCKET_NAME  (mentormindweb-audio-uploads)
    Key    : {uuid}.txt               (flat, no prefix)
    Tags   : user_name, user_email, created_at (ISO 8601 UTC)
"""

from datetime import datetime, timezone

import boto3

from app.config import settings

# Thread-safe client — constructed once when the module is first imported.
# region_name="auto" is required for Cloudflare R2 with boto3.
_client = boto3.client(
    "s3",
    endpoint_url=settings.R2_ENDPOINT_URL,
    aws_access_key_id=settings.R2_ACCESS_KEY_ID,
    aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
    region_name="auto",
)


def upload_transcription(
    uuid: str,
    text: str,
    user_name: str,
    user_email: str,
    created_at_epoch: float,
) -> None:
    """
    Upload a transcription text file to Cloudflare R2.

    Parameters
    ----------
    uuid            : The UUID that identifies this transcription (used as the
                      object key stem).
    text            : Full transcription text content.
    user_name       : Display name of the user who owns the file.
    user_email      : Email address of the user who owns the file.
    created_at_epoch: Unix timestamp (float) for when the upload was created;
                      converted to an ISO 8601 UTC string for the object metadata.

    The call is idempotent — calling it multiple times with the same UUID
    simply overwrites the object, so retries are safe.
    """
    key = f"{uuid}.txt"
    created_at_iso = datetime.fromtimestamp(created_at_epoch, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    _client.put_object(
        Bucket=settings.R2_BUCKET_NAME,
        Key=key,
        Body=text.encode("utf-8"),
        ContentType="text/plain; charset=utf-8",
        Metadata={
            "user_name": user_name,
            "user_email": user_email,
            "created_at": created_at_iso,
        },
    )
