"""
chat_db.py — thin SQLite helper for persisting chat sessions and messages.

Uses the stdlib sqlite3 module directly instead of SQLAlchemy — two tiny tables
don't need an ORM's overhead, and this stays zero-dependency for the local MVP.
"""

import os
import sqlite3
from pathlib import Path
from typing import Optional

# Resolve the DB path relative to this file so it works no matter where uvicorn
# is launched from. If a Railway Volume is attached, Railway sets this env var to
# a persistent mount — we store the DB there so it survives redeploys, since
# Railway's default filesystem is wiped on every restart. Unset locally, so it
# falls back to sitting next to this file.
DB_DIR = Path(os.getenv("RAILWAY_VOLUME_MOUNT_PATH", Path(__file__).parent))
DB_PATH = DB_DIR / "myuoft.db"


def _get_conn() -> sqlite3.Connection:
    """
    Open a fresh connection for each call.

    A new connection per call instead of one shared module-level one, because
    sqlite3 connections aren't thread-safe and FastAPI runs handlers in a thread
    pool — sharing one would risk corruption.
    """
    conn = sqlite3.connect(DB_PATH)
    # Return rows as dicts so callers can do row["id"] instead of row[0].
    conn.row_factory = sqlite3.Row
    # SQLite leaves foreign-key enforcement off by default, so turn it on here
    # for our ON DELETE CASCADE to actually fire.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """
    Create tables if they don't exist.

    Uses CREATE TABLE IF NOT EXISTS so this is idempotent — safe to run on every
    startup without wiping data or erroring on an already-created database.
    """
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT    NOT NULL DEFAULT 'New Chat',
                owner_id   TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL
                               REFERENCES chat_sessions(id) ON DELETE CASCADE,
                role       TEXT    NOT NULL,   -- 'user' or 'assistant'
                content    TEXT    NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()

        # Manually add owner_id to tables that predate this column. CREATE TABLE
        # IF NOT EXISTS skips existing tables entirely, so fresh installs get the
        # column for free but older databases need it patched on here.
        existing_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(chat_sessions)")
        }
        if "owner_id" not in existing_columns:
            conn.execute("ALTER TABLE chat_sessions ADD COLUMN owner_id TEXT")
            conn.commit()
    finally:
        conn.close()


def create_session(owner_id: str, title: str = "New Chat") -> dict:
    """
    Insert a new chat session row and return it as a plain dict.

    Returns: { id, title, created_at }
    """
    conn = _get_conn()
    try:
        cursor = conn.execute(
            "INSERT INTO chat_sessions (title, owner_id) VALUES (?, ?)",
            (title, owner_id),
        )
        conn.commit()
        # Fetch the freshly inserted row so we get the DB-generated created_at.
        row = conn.execute(
            "SELECT id, title, created_at FROM chat_sessions WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def list_sessions(owner_id: str) -> list[dict]:
    """
    Return owner_id's sessions newest-first, each with a message_count field.

    Gets the count via a single LEFT JOIN rather than a follow-up query per
    session, so the sidebar can show counts without N+1 round-trips.
    """
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT
                s.id,
                s.title,
                s.created_at,
                COUNT(m.id) AS message_count
            FROM chat_sessions s
            LEFT JOIN chat_messages m ON m.session_id = s.id
            WHERE s.owner_id = ?
            GROUP BY s.id
            ORDER BY s.created_at DESC
        """, (owner_id,)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def session_belongs_to(session_id: int, owner_id: str) -> bool:
    """
    Check whether a session exists and is owned by owner_id.

    Session ids are guessable integers, so any endpoint taking one must verify
    ownership rather than trust the caller. Callers check this once up front and
    404 on a mismatch, keeping the ownership guard in one place.
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM chat_sessions WHERE id = ? AND owner_id = ?",
            (session_id, owner_id),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_messages(session_id: int) -> list[dict]:
    """
    Return all messages for a session in chronological order.

    Returns: [{ id, role, content }, ...]
    Includes id because editing a past message needs a stable per-message handle
    to tell the DB which row (and everything after it) to discard — array index
    isn't reliable once messages have been stored and reloaded.
    """
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT id, role, content FROM chat_messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def save_message(session_id: int, role: str, content: str) -> int:
    """Insert one message into the session and return its new id."""
    conn = _get_conn()
    try:
        cursor = conn.execute(
            "INSERT INTO chat_messages (session_id, role, content) VALUES (?, ?, ?)",
            (session_id, role, content),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def delete_messages_from(session_id: int, message_id: int) -> None:
    """
    Delete a message and every message after it (by id) within one session.

    Editing a past message discards the now-stale tail so the edit starts fresh,
    like ChatGPT's "edit and resend" — simpler than supporting real branches.
    Cuts on id, not created_at, because whole-second timestamps can tie between a
    message and its reply, while the autoincrement id is strictly ordered.
    """
    conn = _get_conn()
    try:
        conn.execute(
            "DELETE FROM chat_messages WHERE session_id = ? AND id >= ?",
            (session_id, message_id),
        )
        conn.commit()
    finally:
        conn.close()


def update_session_title(session_id: int, title: str) -> None:
    """
    Overwrite a session's title.

    Sessions start as "New Chat" since the topic is unknown at creation; once the
    first user message arrives we set the title to a snippet of it, giving the
    sidebar meaningful labels without asking the user to name anything.
    """
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE chat_sessions SET title = ? WHERE id = ?",
            (title, session_id),
        )
        conn.commit()
    finally:
        conn.close()
