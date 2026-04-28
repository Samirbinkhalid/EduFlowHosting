"""
app/services/postgres_sync.py
------------------------------
Thin psycopg2 wrapper for inserting transcription records into the remote
PostgreSQL database.

A fresh connection is created per call so that each worker thread is never
sharing a connection object (psycopg2 connections are not thread-safe).

Target table schema (columns we write)
---------------------------------------
    file_name          TEXT    — "{uuid}.txt"
    author_name        TEXT    — display name from SSO
    author_email       TEXT    — email from SSO
    content            TEXT    — the UUID; external services resolve the full
                                 text from R2 using file_name or this value

Columns left to DEFAULT
-----------------------
    id                 SERIAL PRIMARY KEY
    timestamp          TIMESTAMPTZ DEFAULT now()
    summarized_content TEXT    DEFAULT NULL
    processing         BOOL    DEFAULT false
    is_processed       BOOL    DEFAULT false
"""

import psycopg2

from app.config import settings


def _get_conn() -> psycopg2.extensions.connection:
    """Open a new psycopg2 connection to the remote PostgreSQL server."""
    return psycopg2.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        dbname=settings.POSTGRES_DB,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        connect_timeout=10,
    )


def insert_transcription(
    file_name: str,
    author_name: str,
    author_email: str,
    content: str,
) -> None:
    """
    Insert one transcription row into the remote `transcriptions` table.

    Uses psycopg2's ``with conn:`` context manager which automatically commits
    on success and rolls back on any exception.

    Parameters
    ----------
    file_name    : Object key / filename, e.g. "{uuid}.txt".
    author_name  : Display name of the user who submitted the recording.
    author_email : Email address of the user who submitted the recording.
    content      : The UUID string — external services use this (or file_name)
                   to fetch the actual transcription text from R2.
    """
    conn = _get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO transcriptions (file_name, author_name, author_email, content)
                VALUES (%s, %s, %s, %s)
                """,
                (file_name, author_name, author_email, content),
            )
    conn.close()
