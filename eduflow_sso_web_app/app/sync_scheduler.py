"""
app/sync_scheduler.py
---------------------
Background R2 + Postgres sync scheduler.

Architecture
------------
One daemon thread is started per uvicorn worker process (called from the
FastAPI lifespan handler, alongside the transcription scheduler).  With 4
uvicorn workers that gives 4 concurrent sync threads across all processes.

Each thread independently polls the `transcriptions` table for records where
is_processed=0 (pending sync) and uses an atomic SQLite UPDATE … RETURNING to
claim a row — so even if multiple processes poll simultaneously, each record
is processed exactly once.

Worker loop (every POLL_INTERVAL seconds):
  1. sync_has_pending_transcriptions()     — cheap read-only pre-check
  2. sync_claim_pending_transcription()    — atomic claim (is_processed → 2)
  3. Read {uuid}.txt from TRANSCRIPTIONS_DIR
  4. r2_upload.upload_transcription()      — put_object to Cloudflare R2
  5. postgres_sync.insert_transcription()  — INSERT into remote PG
  6. sync_mark_transcription_processed()   — is_processed → 1

On any exception at steps 3-5:
  sync_mark_transcription_failed()  — increments retry_count;
                                      sets is_processed=-1 after MAX_SYNC_RETRIES

Design notes (mirrors app/scheduler.py)
----------------------------------------
* Startup jitter desynchronises the 4 worker processes.
* Read-only pre-check avoids write-lock contention on an idle queue.
* fetchone() before conn.commit() — never call commit() while a RETURNING
  cursor is still open (raises "SQL statements in progress").
* R2 put_object is idempotent, so retrying after a Postgres failure is safe.
"""

import logging
import os
import random
import threading
from pathlib import Path

from app.config import settings
from app import database
from app.services.r2_upload import upload_transcription
from app.services.postgres_sync import insert_transcription

logger = logging.getLogger(__name__)

POLL_INTERVAL = 10  # seconds between polls when queue is empty

# Shared stop event — set during app shutdown to signal the thread to exit
_stop_event = threading.Event()

# Reference kept so main.py can join the thread on shutdown
_worker_thread: threading.Thread | None = None


def _worker_loop() -> None:
    """Main loop executed by the sync scheduler thread."""
    startup_jitter = random.uniform(0, POLL_INTERVAL)
    logger.info(
        "[sync_scheduler] Sync worker started (pid=%d), jitter=%.1fs",
        os.getpid(),
        startup_jitter,
    )
    _stop_event.wait(startup_jitter)

    while not _stop_event.is_set():
        # ── Cheap read-only pre-check ────────────────────────────────────
        # Avoids acquiring a write lock when the sync queue is empty.
        try:
            has_work = database.sync_has_pending_transcriptions()
        except Exception as exc:
            logger.error("[sync_scheduler] DB read error: %s", exc)
            _stop_event.wait(POLL_INTERVAL)
            continue

        if not has_work:
            _stop_event.wait(POLL_INTERVAL)
            continue

        # ── Atomic write claim ───────────────────────────────────────────
        try:
            row = database.sync_claim_pending_transcription()
        except Exception as exc:
            logger.error("[sync_scheduler] DB claim error: %s", exc)
            _stop_event.wait(POLL_INTERVAL)
            continue

        if row is None:
            # Another worker claimed the last record between pre-check and UPDATE.
            _stop_event.wait(POLL_INTERVAL)
            continue

        uuid = row["uuid"]
        user_email = row["user_email"]
        user_name = row["user_name"]
        created_at = row["created_at"]  # Unix integer timestamp
        txt_path = Path(settings.TRANSCRIPTIONS_DIR).resolve() / f"{uuid}.txt"

        logger.info(
            "[sync_scheduler] Syncing transcription uuid=%s user=%s",
            uuid,
            user_email,
        )

        try:
            # ── Step 3: read transcription text ──────────────────────────
            text = txt_path.read_text(encoding="utf-8")

            # ── Step 4: upload to Cloudflare R2 ──────────────────────────
            upload_transcription(
                uuid=uuid,
                text=text,
                user_name=user_name,
                user_email=user_email,
                created_at_epoch=float(created_at),
            )
            logger.info("[sync_scheduler] R2 upload complete for uuid=%s", uuid)

            # ── Step 5: insert into remote PostgreSQL ─────────────────────
            insert_transcription(
                file_name=f"{uuid}.txt",
                author_name=user_name,
                author_email=user_email,
                content=uuid,
            )
            logger.info("[sync_scheduler] Postgres insert complete for uuid=%s", uuid)

            # ── Step 6: mark sync as done ─────────────────────────────────
            database.sync_mark_transcription_processed(uuid)

            # ── Step 7: delete local .txt (non-fatal if missing) ──────────
            try:
                txt_path.unlink(missing_ok=True)
                logger.info("[sync_scheduler] Deleted local file %s", txt_path.name)
            except Exception as del_exc:
                logger.warning(
                    "[sync_scheduler] Could not delete %s: %s",
                    txt_path.name,
                    del_exc,
                )

        except Exception as exc:
            logger.error("[sync_scheduler] Sync failed for uuid=%s: %s", uuid, exc)
            try:
                database.sync_mark_transcription_failed(uuid, settings.MAX_SYNC_RETRIES)
            except Exception as db_exc:
                logger.error(
                    "[sync_scheduler] Failed to update failure state: %s", db_exc
                )

        # No sleep here — immediately try next record if the queue has more.
        # The poll-sleep only triggers when has_work was False (empty queue).

    logger.info("[sync_scheduler] Worker exiting (pid=%d)", os.getpid())


def start_scheduler() -> None:
    """
    Start the background R2 + Postgres sync worker thread.

    Called once per process from the FastAPI lifespan handler.
    The thread is a daemon so it won't prevent clean process exit.
    """
    global _worker_thread
    _stop_event.clear()
    _worker_thread = threading.Thread(
        target=_worker_loop,
        name="upload-transcription-and-sync-postgres",
        daemon=True,
    )
    _worker_thread.start()
    logger.info("[sync_scheduler] Sync worker thread started")


def stop_scheduler() -> None:
    """
    Signal the sync worker thread to stop and wait up to 5 s for it to finish.

    Called from the FastAPI lifespan shutdown phase.
    """
    _stop_event.set()
    if _worker_thread is not None:
        _worker_thread.join(timeout=5)
        logger.info("[sync_scheduler] Sync worker thread stopped")
