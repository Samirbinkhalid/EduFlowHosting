"""
app/services/user_data.py
--------------------------
Read-only queries against the remote PostgreSQL database that fetch
all five user-facing tables filtered by email.  Each query runs as a
separate execute() call on a single connection so there is no
reconnect overhead.
"""

import time

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


def fetch_user_data(email: str) -> dict:
    """Return all five tables filtered by *email* using one connection.

    Parameters
    ----------
    email : str
        Lower-cased email address of the authenticated user.

    Returns
    -------
    dict
        {
            "uploads":         [{file_name, is_processed, created_at}, …],
            "transcriptions":  [{summarized_content, is_processed}, …],
            "user_stories":    [{processed_description, is_processed}, …],
            "notifications":   [{message, is_processed}, …],
            "actions":         [{type, is_processed, timestamp}, …],
            "generated_at":    <int>,
        }
    """
    conn = _get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT file_name, is_processed, created_at
                FROM uploaded_files
                WHERE LOWER(author_email) = %s
                ORDER BY created_at DESC
                LIMIT 50
                """,
                (email,),
            )
            uploads = [
                dict(zip(["file_name", "is_processed", "created_at"], r))
                for r in cur.fetchall()
            ]

            cur.execute(
                """
                SELECT summarized_content, is_processed
                FROM transcriptions
                WHERE LOWER(author_email) = %s
                ORDER BY timestamp DESC
                LIMIT 50
                """,
                (email,),
            )
            transcriptions = [
                dict(zip(["summarized_content", "is_processed"], r))
                for r in cur.fetchall()
            ]

            cur.execute(
                """
                SELECT processed_description, is_processed
                FROM user_stories
                WHERE LOWER(created_for_email) = %s
                ORDER BY timestamp DESC
                LIMIT 50
                """,
                (email,),
            )
            user_stories = [
                dict(zip(["processed_description", "is_processed"], r))
                for r in cur.fetchall()
            ]

            cur.execute(
                """
                SELECT message, is_processed
                FROM notifications
                WHERE LOWER(for_user_email) = %s
                ORDER BY timestamp DESC
                LIMIT 50
                """,
                (email,),
            )
            notifications = [
                dict(zip(["message", "is_processed"], r))
                for r in cur.fetchall()
            ]

            cur.execute(
                """
                SELECT a.type, a.is_processed, a.timestamp
                FROM actions a
                JOIN user_stories us ON a.user_story_id = us.id
                WHERE LOWER(us.created_for_email) = %s
                ORDER BY a.timestamp DESC
                LIMIT 50
                """,
                (email,),
            )
            actions = [
                dict(zip(["type", "is_processed", "timestamp"], r))
                for r in cur.fetchall()
            ]

    conn.close()

    return {
        "uploads": uploads,
        "transcriptions": transcriptions,
        "user_stories": user_stories,
        "notifications": notifications,
        "actions": actions,
        "generated_at": int(time.time()),
    }
