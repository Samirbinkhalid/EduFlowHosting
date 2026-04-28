"""
app/routers/upload.py
---------------------
TUS 1.0.0 resumable-upload server implemented directly in FastAPI.

Why not a library?
  No well-maintained Python TUS *server* library is compatible with
  FastAPI >= 0.115 at the time of writing.  The protocol's core is
  straightforward enough to implement directly and gives us full control
  over auth, size limits, and post-upload hooks.

Protocol summary (https://tus.io/protocols/resumable-upload)
-------------------------------------------------------------
  OPTIONS  /upload/           Advertise TUS capabilities (no auth needed)
  POST     /upload/           Create a new upload slot
  HEAD     /upload/{id}       Query current byte offset
  PATCH    /upload/{id}       Upload the next chunk

Storage layout  (settings.TUS_UPLOADS_DIR, default /tmp/tus_uploads)
----------------------------------------------------------------------
  <upload_id>/
    data        — the file being assembled, byte-by-byte
    meta.json   — {"total_size": N, "offset": N,
                    "filename": "…", "filetype": "…"}

  File-based state means all four uvicorn workers share the same view
  of every in-progress upload without any in-process co-ordination.

Post-completion hook (triggered in the final PATCH)
----------------------------------------------------
  1. audio.extract_audio(data_path) → uuid
  2. database.insert_upload_record(uuid, email, name)
  3. shutil.rmtree(<upload_dir>)   — ephemeral TUS dir removed
"""

import json
import base64
import shutil
import uuid as _uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status

from app.auth.dependencies import get_authorized_user
from app import database
from app.services import audio
from app.config import settings

# ------------------------------------------------------------------ #
# Constants                                                            #
# ------------------------------------------------------------------ #
TUS_VERSION = "1.0.0"
MAX_SIZE_BYTES = 500 * 1024 * 1024  # 500 MB hard limit
CHUNK_CONTENT_TYPE = "application/offset+octet-stream"

router = APIRouter()


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #


def _tus_uploads_dir() -> Path:
    """Resolve TUS_UPLOADS_DIR from settings at call time and ensure it exists."""
    d = Path(settings.TUS_UPLOADS_DIR).resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _upload_dir(upload_id: str) -> Path:
    return _tus_uploads_dir() / upload_id


def _data_path(upload_id: str) -> Path:
    return _upload_dir(upload_id) / "data"


def _meta_path(upload_id: str) -> Path:
    return _upload_dir(upload_id) / "meta.json"


def _read_meta(upload_id: str) -> dict:
    meta_file = _meta_path(upload_id)
    if not meta_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload not found.",
        )
    return json.loads(meta_file.read_text())


def _write_meta(upload_id: str, meta: dict) -> None:
    _meta_path(upload_id).write_text(json.dumps(meta))


def _tus_headers() -> dict:
    """Standard TUS response headers included in every reply."""
    return {"Tus-Resumable": TUS_VERSION}


# ------------------------------------------------------------------ #
# Routes                                                               #
# ------------------------------------------------------------------ #


@router.options("/")
async def tus_options() -> Response:
    """Advertise TUS server capabilities.

    No authentication required — the client probes this before it has
    a chance to learn whether it is authorised.
    """
    headers = {
        "Tus-Resumable": TUS_VERSION,
        "Tus-Version": TUS_VERSION,
        "Tus-Max-Size": str(MAX_SIZE_BYTES),
        "Tus-Extension": "creation",
        "Cache-Control": "no-store",
    }
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=headers)


@router.post("/")
async def tus_create(
    request: Request,
    current_user: dict = Depends(get_authorized_user),
    upload_length: str = Header(..., alias="Upload-Length"),
    upload_metadata: str = Header(default="", alias="Upload-Metadata"),
) -> Response:
    """Create a new upload slot.

    Validates:
    - Upload-Length header is present and ≤ 500 MB.
    - tus-resumable header matches the server version.

    Returns a Location header pointing to the upload resource.
    """
    # --- size guard ----------------------------------------------------
    try:
        total_size = int(upload_length)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload-Length must be an integer.",
        )

    if total_size > MAX_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the 500 MB limit ({total_size} bytes received).",
        )

    # --- parse optional Upload-Metadata --------------------------------
    # Format: "key base64value, key2 base64value2"
    meta_dict: dict[str, str] = {}
    for item in upload_metadata.split(","):
        item = item.strip()
        if not item:
            continue
        parts = item.split(" ", 1)
        key = parts[0]
        try:
            value = base64.b64decode(parts[1]).decode("utf-8") if len(parts) > 1 else ""
        except Exception:
            value = ""
        meta_dict[key] = value

    # --- create storage ------------------------------------------------
    upload_id = str(_uuid.uuid4())
    upload_dir = _upload_dir(upload_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    _data_path(upload_id).touch()  # empty file, ready for PATCH
    _write_meta(
        upload_id,
        {
            "total_size": total_size,
            "offset": 0,
            "filename": meta_dict.get("filename", ""),
            "filetype": meta_dict.get("filetype", ""),
        },
    )

    location = str(request.url_for("tus_head", upload_id=upload_id))
    headers = {
        **_tus_headers(),
        "Location": location,
        "Upload-Offset": "0",
    }
    return Response(status_code=status.HTTP_201_CREATED, headers=headers)


@router.head("/{upload_id}")
async def tus_head(
    upload_id: str,
    current_user: dict = Depends(get_authorized_user),
) -> Response:
    """Return the current byte offset for a given upload.

    Used by tus-js-client to determine how many bytes have already
    been received so it can resume from the correct position.
    """
    meta = _read_meta(upload_id)
    headers = {
        **_tus_headers(),
        "Upload-Offset": str(meta["offset"]),
        "Upload-Length": str(meta["total_size"]),
        "Cache-Control": "no-store",
    }
    return Response(status_code=status.HTTP_200_OK, headers=headers)


@router.patch("/{upload_id}")
async def tus_patch(
    upload_id: str,
    request: Request,
    current_user: dict = Depends(get_authorized_user),
    content_type: str = Header(..., alias="Content-Type"),
    upload_offset: str = Header(..., alias="Upload-Offset"),
) -> Response:
    """Receive the next chunk of bytes and append them to the upload file.

    When the final chunk brings offset == total_size:
      - ffmpeg extracts the audio track → settings.UPLOADS_DIR/<uuid>.m4a
      - A record is inserted into the SQLite database (is_processed=0)
      - The ephemeral TUS directory is deleted from settings.TUS_UPLOADS_DIR
    """
    # --- validate content-type -----------------------------------------
    if content_type != CHUNK_CONTENT_TYPE:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Content-Type must be '{CHUNK_CONTENT_TYPE}'.",
        )

    # --- load meta & validate offset -----------------------------------
    meta = _read_meta(upload_id)
    try:
        client_offset = int(upload_offset)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload-Offset must be an integer.",
        )

    if client_offset != meta["offset"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Upload-Offset mismatch: server has {meta['offset']}, "
                f"client sent {client_offset}."
            ),
        )

    # --- append chunk to file ------------------------------------------
    chunk = await request.body()
    data_file = _data_path(upload_id)
    with data_file.open("ab") as fh:
        fh.write(chunk)

    new_offset = meta["offset"] + len(chunk)
    meta["offset"] = new_offset
    _write_meta(upload_id, meta)

    headers = {
        **_tus_headers(),
        "Upload-Offset": str(new_offset),
    }

    # --- check if upload is complete -----------------------------------
    if new_offset == meta["total_size"]:
        # Run extraction + DB insert; clean up TUS dir afterwards.
        # Any exception here is surfaced as a 500 so tus-js-client
        # marks the upload as failed (it will not retry a 5xx on the
        # final PATCH by default).
        data_path = str(data_file)
        audio_uuid = await audio.extract_audio(data_path)
        await database.insert_upload_record(
            uuid=audio_uuid,
            email=current_user.get("email", ""),
            name=current_user.get("name", ""),
        )
        # Clean up ephemeral TUS directory
        shutil.rmtree(str(_upload_dir(upload_id)), ignore_errors=True)

    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers=headers,
    )
