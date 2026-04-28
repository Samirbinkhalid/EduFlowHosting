"""
app/services/transcription.py
------------------------------
Thin wrapper around the ElevenLabs Speech-to-Text API.

Uses the official `elevenlabs` Python SDK (v2+).
Model: scribe_v1  —  language: English (en)

Usage
-----
    from app.services.transcription import transcribe_audio
    text = transcribe_audio(Path("/uploads/abc123.m4a"))
"""

from pathlib import Path

from elevenlabs import ElevenLabs

from app.config import settings

# Module-level client — instantiated once per process.
# The scheduler threads share this instance; the SDK is thread-safe.
_client = ElevenLabs(api_key=settings.ELEVENLABS_API_KEY)


def transcribe_audio(file_path: Path) -> str:
    """
    Transcribe an audio file using ElevenLabs scribe_v1 and return the text.

    Parameters
    ----------
    file_path : Path
        Absolute path to the .m4a (or other supported audio) file.

    Returns
    -------
    str
        The full transcription text.

    Raises
    ------
    Any exception from the ElevenLabs SDK is propagated to the caller so the
    scheduler can handle retries / failure marking.
    """
    with open(file_path, "rb") as audio_file:
        result = _client.speech_to_text.convert(
            file=audio_file,
            model_id="scribe_v1",
            language_code="en",
        )
    return result.text
