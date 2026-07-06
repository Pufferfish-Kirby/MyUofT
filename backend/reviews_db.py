# Reviews live in the same myuoft.db file as chat history — one SQLite file is
# simpler to back up and ship than several, and both tables migrate together
# when we move to PostgreSQL in Phase 2.
import sqlite3

# Import DB_PATH from chat_db rather than recomputing it, so both modules always
# agree on the file location (including chat_db's Railway-volume fallback) and
# can't silently drift apart.
from chat_db import DB_PATH as _DB_PATH


def _connect() -> sqlite3.Connection:
    """
    Open a connection with row_factory set to sqlite3.Row so callers can
    access columns by name (row['course_code']) instead of index (row[1]).
    """
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_reviews_db() -> None:
    """
    Create the course_reviews table if it doesn't already exist.

    Safe to call at every server startup — CREATE TABLE IF NOT EXISTS is
    idempotent and will not wipe existing data.
    """
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS course_reviews (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            course_code TEXT    NOT NULL,
            rating      INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            review_text TEXT    DEFAULT '',
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def save_review(course_code: str, rating: int, review_text: str) -> dict:
    """
    Insert a new review row and return it as a dict.

    Reads the row back via lastrowid + a SELECT instead of a RETURNING clause,
    which only works on SQLite 3.35+ — lastrowid runs on the older versions that
    ship with some Python builds.
    """
    conn = _connect()
    cursor = conn.execute(
        "INSERT INTO course_reviews (course_code, rating, review_text) VALUES (?, ?, ?)",
        (course_code, rating, review_text),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM course_reviews WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    conn.close()
    return dict(row)


def get_reviews(course_code: str) -> list[dict]:
    """
    Return all reviews for a course, newest first.

    Orders newest-first because recent opinions matter most to current students —
    a review of a recently restructured course beats a years-old one.
    """
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM course_reviews WHERE course_code = ? ORDER BY created_at DESC",
        (course_code,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_avg_rating(course_code: str) -> float | None:
    """
    Return the average rating for a course, or None if no reviews exist yet.

    Returns None rather than 0.0 so callers can tell "no data" apart from a real
    zero average — the scoring engine treats None as its signal to fall back to
    RATING_NEUTRAL.
    """
    conn = _connect()
    row = conn.execute(
        "SELECT AVG(rating) FROM course_reviews WHERE course_code = ?",
        (course_code,),
    ).fetchone()
    conn.close()
    avg = row[0]
    return float(avg) if avg is not None else None


# Runs at import time because scoring.py calls get_avg_rating() while loading the
# catalog on import, before main.py could call this itself — so the table has to
# exist the moment this module loads. Safe to run eagerly since it's idempotent.
init_reviews_db()
