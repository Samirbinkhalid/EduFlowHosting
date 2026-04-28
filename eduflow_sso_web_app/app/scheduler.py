"""
app/scheduler.py
----------------
Background transcription scheduler.

Architecture
------------
One daemon thread is started per uvicorn worker process (called from the
FastAPI lifespan handler).  With 4 uvicorn workers that gives 4 concurrent
scheduler threads across all processes.

Each thread independently polls the `uploads` table for unprocessed records
and uses an atomic SQLite UPDATE … RETURNING to claim a row — so even if
multiple processes poll simultaneously, each record is processed exactly once.

Worker loop (every POLL_INTERVAL seconds):
  1. sync_claim_pending_upload()  — atomic claim; returns row or None
  2. transcribe_audio()           — ElevenLabs API call
  3. Write {uuid}.txt to TRANSCRIPTIONS_DIR
  4. sync_insert_transcription_record()
  5. sync_mark_upload_processed()
  6. Delete {uuid}.m4a from UPLOADS_DIR
     (only after steps 3-5 all succeed; deletion failure is non-fatal)

On any exception at steps 2-6:
  sync_mark_upload_failed()  — increments retry_count;
                               sets is_processed=-1 after MAX_TRANSCRIPTION_RETRIES
"""

import logging
import os
import random
import threading
from pathlib import Path

from app.config import settings
from app import database
from app.services.transcription import transcribe_audio

logger = logging.getLogger(__name__)

POLL_INTERVAL = 10  # seconds between polls when queue is empty

# Shared stop event — set during app shutdown to signal all threads to exit
_stop_event = threading.Event()

# Keep track of the worker thread so main.py can join it on shutdown
_worker_thread: threading.Thread | None = None


def _worker_loop() -> None:
    """Main loop executed by the scheduler thread."""
    # Stagger startup across the 4 worker processes so they don't all poll
    # SQLite at exactly the same instant on every cycle.
    startup_jitter = random.uniform(0, POLL_INTERVAL)
    logger.info(
        "[scheduler] Transcription worker started (pid=%d), jitter=%.1fs",
        os.getpid(),
        startup_jitter,
    )
    _stop_event.wait(startup_jitter)

    while not _stop_event.is_set():
        # ── Cheap read-only pre-check ────────────────────────────────────
        # Avoids acquiring a write lock (and fighting other workers) when
        # there is nothing in the queue.
        try:
            has_work = database.sync_has_pending_uploads()
        except Exception as exc:
            logger.error("[scheduler] DB read error: %s", exc)
            _stop_event.wait(POLL_INTERVAL)
            continue

        if not has_work:
            _stop_event.wait(POLL_INTERVAL)
            continue

        # ── Atomic write claim ───────────────────────────────────────────
        try:
            row = database.sync_claim_pending_upload()
        except Exception as exc:
            logger.error("[scheduler] DB claim error: %s", exc)
            _stop_event.wait(POLL_INTERVAL)
            continue

        if row is None:
            # Another worker claimed the last record between our pre-check
            # and the UPDATE — nothing to do this cycle.
            _stop_event.wait(POLL_INTERVAL)
            continue

        uuid = row["uuid"]
        email = row["user_email"]
        name = row["user_name"]
        audio_path = Path(settings.UPLOADS_DIR).resolve() / f"{uuid}.m4a"
        txt_path = Path(settings.TRANSCRIPTIONS_DIR).resolve() / f"{uuid}.txt"

        logger.info("[scheduler] Processing upload uuid=%s user=%s", uuid, email)

        try:
            # ── Step 2: transcribe ───────────────────────────────────────
            text = transcribe_audio(audio_path)

            # ── Step 3: persist .txt ─────────────────────────────────────
            txt_path.parent.mkdir(parents=True, exist_ok=True)
            txt_path.write_text(text, encoding="utf-8")
            logger.info(
                "[scheduler] Saved transcription %s (%d chars)",
                txt_path.name,
                len(text),
            )

            # ── Step 4: insert transcription DB record ───────────────────
            database.sync_insert_transcription_record(uuid, email, name)

            # ── Step 5: mark upload as processed ────────────────────────
            database.sync_mark_upload_processed(uuid)

            # ── Step 6: delete source .m4a (non-fatal if missing) ───────
            try:
                audio_path.unlink(missing_ok=True)
                logger.info("[scheduler] Deleted source file %s", audio_path.name)
            except Exception as del_exc:
                logger.warning(
                    "[scheduler] Could not delete %s: %s", audio_path.name, del_exc
                )

        except Exception as exc:
            logger.error("[scheduler] Transcription failed for uuid=%s: %s", uuid, exc)
            try:
                database.sync_mark_upload_failed(
                    uuid, settings.MAX_TRANSCRIPTION_RETRIES
                )
            except Exception as db_exc:
                logger.error("[scheduler] Failed to update failure state: %s", db_exc)

        # No sleep here — immediately try next record if the queue has more.
        # The poll-sleep only triggers when has_work was False (empty queue).

    logger.info("[scheduler] Worker exiting (pid=%d)", os.getpid())


def start_scheduler() -> None:
    """
    Start the background transcription worker thread.

    Called once per process from the FastAPI lifespan handler.
    The thread is a daemon so it won't prevent clean process exit.
    """
    global _worker_thread
    _stop_event.clear()
    _worker_thread = threading.Thread(
        target=_worker_loop,
        name="transcription-worker",
        daemon=True,
    )
    _worker_thread.start()
    logger.info("[scheduler] Worker thread started")


def stop_scheduler() -> None:
    """
    Signal the worker thread to stop and wait up to 5 s for it to finish.

    Called from the FastAPI lifespan shutdown phase.
    """
    _stop_event.set()
    if _worker_thread is not None:
        _worker_thread.join(timeout=5)
        logger.info("[scheduler] Worker thread stopped")
