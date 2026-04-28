"""
app/database.py
---------------
Database helpers — both async (for FastAPI route handlers) and synchronous
(for background scheduler threads that run outside the async event loop).

SQLite file is stored under settings.DATA_DIR so it works locally and in Docker.
WAL journal mode is enabled for concurrent multi-worker access.

Schema
------
uploads
  uuid         TEXT PRIMARY KEY   — UUID of the extracted .m4a file
  user_email   TEXT NOT NULL      — from SSO session
  user_name    TEXT NOT NULL      — from SSO session
  created_at   INTEGER NOT NULL   — Unix epoch (seconds)
  is_processed INTEGER NOT NULL DEFAULT 0
               —  0  = pending transcription
               —  2  = claimed / in-progress (scheduler lock)
               —  1  = transcription complete; .m4a deleted
               — -1  = permanently failed (exceeded MAX_TRANSCRIPTION_RETRIES)
  retry_count  INTEGER NOT NULL DEFAULT 0
               — incremented on each transcription failure

transcriptions
  uuid         TEXT PRIMARY KEY   — same UUID as the upload / .txt filename stem
  user_email   TEXT NOT NULL
  user_name    TEXT NOT NULL
  created_at   INTEGER NOT NULL   — Unix epoch when transcription was saved
  is_processed INTEGER NOT NULL DEFAULT 0
               —  0  = pending R2 + Postgres sync
               —  2  = claimed / in-progress (sync scheduler lock)
               —  1  = R2 upload + Postgres insert complete
               — -1  = permanently failed (exceeded MAX_SYNC_RETRIES)
  retry_count  INTEGER NOT NULL DEFAULT 0
               — incremented on each sync failure
"""

import sqlite3
import time
from pathlib import Path

import aiosqlite

from app.config import settings


# ── Path helpers ──────────────────────────────────────────────────────────────


def _db_path() -> str:
    """Return the absolute path to the SQLite database file."""
    data_dir = Path(settings.DATA_DIR).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "mentormind.db")


# ── Schema init (async, called once at app startup) ───────────────────────────


async def init_db() -> None:
    """Create tables and run any pending migrations."""
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute("PRAGMA journal_mode=WAL")

        # uploads table (original schema)
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS uploads (
                uuid         TEXT    PRIMARY KEY,
                user_email   TEXT    NOT NULL,
                user_name    TEXT    NOT NULL,
                created_at   INTEGER NOT NULL,
                is_processed INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        # Migration: add retry_count if it doesn't exist yet (safe to run repeatedly)
        try:
            await db.execute(
                "ALTER TABLE uploads ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0"
            )
        except Exception:
            pass  # column already exists — fine

        # transcriptions table
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS transcriptions (
                uuid         TEXT    PRIMARY KEY,
                user_email   TEXT    NOT NULL,
                user_name    TEXT    NOT NULL,
                created_at   INTEGER NOT NULL,
                is_processed INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        # Migration: add retry_count to transcriptions if it doesn't exist yet
        try:
            await db.execute(
                "ALTER TABLE transcriptions ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0"
            )
        except Exception:
            pass  # column already exists — fine

        await db.commit()


# ── Async helpers (used by FastAPI route handlers) ────────────────────────────


async def insert_upload_record(uuid: str, email: str, name: str) -> None:
    """Insert a new upload record with is_processed=0 (default)."""
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            """
            INSERT INTO uploads (uuid, user_email, user_name, created_at, is_processed)
            VALUES (?, ?, ?, ?, 0)
            """,
            (uuid, email, name, int(time.time())),
        )
        await db.commit()


async def fetch_all_uploads() -> list:
    """Return every row from the uploads table, newest first."""
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT uuid, user_email, user_name, created_at, is_processed, retry_count
            FROM uploads
            ORDER BY created_at DESC
            """
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def fetch_all_transcriptions() -> list:
    """Return every row from the transcriptions table, newest first."""
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT uuid, user_email, user_name, created_at, is_processed, retry_count
            FROM transcriptions
            ORDER BY created_at DESC
            """
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


# ── Synchronous helpers (used by scheduler threads) ───────────────────────────
# These use the stdlib sqlite3 module directly — no event-loop required.


def _sync_connect() -> sqlite3.Connection:
    """Open a synchronous WAL-mode connection to the DB.

    timeout=30 means SQLite will retry for up to 30 s when another process
    holds a write lock before raising OperationalError — enough headroom for
    4 concurrent workers sharing the same file.
    """
    conn = sqlite3.connect(_db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    # Busy handler is set via timeout above; additionally tell SQLite to use
    # WAL checkpointing passively so readers never block writers.
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def sync_has_pending_uploads() -> bool:
    """Cheap read-only check — avoids acquiring a write lock when queue is empty."""
    conn = _sync_connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM uploads WHERE is_processed = 0 LIMIT 1"
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def sync_claim_pending_upload() -> dict | None:
    """
    Atomically claim the oldest pending upload for transcription.

    Uses a single UPDATE … WHERE uuid = (SELECT … LIMIT 1) statement so that
    SQLite's write serialisation ensures only one process/thread wins each row.
    The RETURNING clause gives back the claimed row without a second query.

    Returns the claimed row as a dict, or None if no pending rows exist.
    """
    conn = _sync_connect()
    try:
        cursor = conn.execute(
            """
            UPDATE uploads
               SET is_processed = 2
             WHERE uuid = (
                   SELECT uuid FROM uploads
                    WHERE is_processed = 0
                    ORDER BY created_at ASC
                    LIMIT 1
             )
            RETURNING uuid, user_email, user_name
            """
        )
        # IMPORTANT: fetchone() MUST come before commit().
        # Calling commit() while the RETURNING cursor is still open raises
        # "cannot commit transaction - SQL statements in progress".
        row = cursor.fetchone()
        conn.commit()
        return dict(row) if row else None
    finally:
        conn.close()


def sync_mark_upload_processed(uuid: str) -> None:
    """Mark an upload as successfully transcribed (is_processed=1)."""
    conn = _sync_connect()
    try:
        conn.execute("UPDATE uploads SET is_processed = 1 WHERE uuid = ?", (uuid,))
        conn.commit()
    finally:
        conn.close()


def sync_mark_upload_failed(uuid: str, max_retries: int) -> None:
    """
    Increment retry_count for this upload.

    If retry_count reaches max_retries, set is_processed = -1 (permanently
    failed) so the scheduler never picks it up again.  Otherwise reset
    is_processed = 0 so a later poll cycle can retry it.
    """
    conn = _sync_connect()
    try:
        conn.execute(
            "UPDATE uploads SET retry_count = retry_count + 1 WHERE uuid = ?",
            (uuid,),
        )
        cursor = conn.execute("SELECT retry_count FROM uploads WHERE uuid = ?", (uuid,))
        row = cursor.fetchone()
        new_count = row["retry_count"] if row else max_retries

        if new_count >= max_retries:
            conn.execute("UPDATE uploads SET is_processed = -1 WHERE uuid = ?", (uuid,))
        else:
            # Release the claim so the scheduler can retry
            conn.execute("UPDATE uploads SET is_processed = 0 WHERE uuid = ?", (uuid,))

        conn.commit()
    finally:
        conn.close()


def sync_insert_transcription_record(uuid: str, email: str, name: str) -> None:
    """Insert a row into the transcriptions table (is_processed=0 by default)."""
    conn = _sync_connect()
    try:
        conn.execute(
            """
            INSERT INTO transcriptions (uuid, user_email, user_name, created_at, is_processed)
            VALUES (?, ?, ?, ?, 0)
            """,
            (uuid, email, name, int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()


# ── Synchronous helpers for the sync scheduler (R2 + Postgres) ───────────────


def sync_has_pending_transcriptions() -> bool:
    """Cheap read-only check — avoids write-lock contention when sync queue is empty."""
    conn = _sync_connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM transcriptions WHERE is_processed = 0 LIMIT 1"
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def sync_claim_pending_transcription() -> dict | None:
    """
    Atomically claim the oldest pending transcription for R2 + Postgres sync.

    Same pattern as sync_claim_pending_upload(): single UPDATE … RETURNING
    with fetchone() before commit() to avoid "SQL statements in progress".

    Returns the claimed row as a dict (uuid, user_email, user_name, created_at),
    or None if no pending rows exist.
    """
    conn = _sync_connect()
    try:
        cursor = conn.execute(
            """
            UPDATE transcriptions
               SET is_processed = 2
             WHERE uuid = (
                   SELECT uuid FROM transcriptions
                    WHERE is_processed = 0
                    ORDER BY created_at ASC
                    LIMIT 1
             )
            RETURNING uuid, user_email, user_name, created_at
            """
        )
        row = cursor.fetchone()  # MUST be before commit()
        conn.commit()
        return dict(row) if row else None
    finally:
        conn.close()


def sync_mark_transcription_processed(uuid: str) -> None:
    """Mark a transcription as successfully synced to R2 + Postgres (is_processed=1)."""
    conn = _sync_connect()
    try:
        conn.execute(
            "UPDATE transcriptions SET is_processed = 1 WHERE uuid = ?", (uuid,)
        )
        conn.commit()
    finally:
        conn.close()


def sync_mark_transcription_failed(uuid: str, max_retries: int) -> None:
    """
    Increment retry_count for this transcription sync attempt.

    If retry_count reaches max_retries, set is_processed = -1 (permanently
    failed).  Otherwise reset is_processed = 0 so the next poll can retry.
    """
    conn = _sync_connect()
    try:
        conn.execute(
            "UPDATE transcriptions SET retry_count = retry_count + 1 WHERE uuid = ?",
            (uuid,),
        )
        cursor = conn.execute(
            "SELECT retry_count FROM transcriptions WHERE uuid = ?", (uuid,)
        )
        row = cursor.fetchone()
        new_count = row["retry_count"] if row else max_retries

        if new_count >= max_retries:
            conn.execute(
                "UPDATE transcriptions SET is_processed = -1 WHERE uuid = ?", (uuid,)
            )
        else:
            conn.execute(
                "UPDATE transcriptions SET is_processed = 0 WHERE uuid = ?", (uuid,)
            )

        conn.commit()
    finally:
        conn.close()
