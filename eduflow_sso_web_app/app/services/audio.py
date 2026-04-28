"""
app/services/audio.py
---------------------
Extracts the audio stream from an assembled video/audio file (mp4 / m4a)
and saves it as <uuid>.m4a inside settings.UPLOADS_DIR.

Strategy
--------
- Use ffmpeg-python (thin Python wrapper around the ffmpeg CLI binary).
- Flags: -vn (no video), -acodec copy (copy audio stream without re-encoding
  — fast, lossless, preserves original quality).
- The blocking ffmpeg.run() call is dispatched to a thread-pool executor
  via asyncio.to_thread() so the uvicorn event loop is never blocked.

Output path
-----------
Resolved from settings.UPLOADS_DIR so the same code works for both
`uv run serve` (defaults to ./uploads/) and Docker (/app/uploads via
UPLOADS_DIR env var).
"""

import asyncio
import uuid as _uuid
from pathlib import Path

import ffmpeg

from app.config import settings


def _uploads_dir() -> Path:
    """Resolve UPLOADS_DIR at call time and ensure it exists."""
    d = Path(settings.UPLOADS_DIR).resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


async def extract_audio(source_path: str) -> str:
    """Extract the audio track from *source_path* and save to UPLOADS_DIR.

    Parameters
    ----------
    source_path:
        Absolute path to the fully assembled TUS upload file (mp4 or m4a).

    Returns
    -------
    str
        The UUID (without extension) of the saved .m4a file.

    Raises
    ------
    ffmpeg.Error
        If ffmpeg exits with a non-zero return code (e.g. corrupt input).
    """
    audio_uuid = str(_uuid.uuid4())
    output_path = str(_uploads_dir() / f"{audio_uuid}.m4a")

    # Build the ffmpeg pipeline:
    #   -i <source>   input file
    #   -vn           drop all video streams
    #   -acodec copy  copy audio codec as-is (no re-encode)
    stream = ffmpeg.input(source_path).output(output_path, vn=None, acodec="copy")

    # ffmpeg.run() is a blocking subprocess call — run it off the event loop.
    await asyncio.to_thread(
        ffmpeg.run,
        stream,
        overwrite_output=True,
        quiet=True,  # suppress ffmpeg's verbose stderr chatter
    )

    return audio_uuid
