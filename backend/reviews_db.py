# WHY share the same myuoft.db file as chat history:
#   A single SQLite file is simpler to back up, ship, and reason about than
#   multiple DB files for a local MVP.  One file = one copy command, one git
#   ignore entry, one restore step.  When we migrate to PostgreSQL in Phase 2,
#   both tables move together in the same migration.
import sqlite3
from pathlib import Path

# Resolve the DB path relative to this file so the module works regardless of
# the working directory the server is launched from (backend/, project root, etc.)
_DB_PATH = Path(__file__).parent / "myuoft.db"


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

    WHY use lastrowid + a second SELECT instead of RETURNING:
        The RETURNING clause requires SQLite 3.35+ (2021).  Using lastrowid is
        compatible with older SQLite versions that ship with Python 3.9–3.10 on
        some systems, while also being simpler to read.
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

    WHY ORDER BY created_at DESC:
        The most recent opinions are most relevant to current students — a 2024
        review of a restructured course matters more than a 2019 review.
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

    Returns None (not 0.0) so callers can distinguish "no data" from
    "data exists and the average happens to be zero" — the scoring engine
    uses None as a signal to apply the RATING_NEUTRAL fallback instead of
    treating the course as having a real 0-star rating.
    """
    conn = _connect()
    row = conn.execute(
        "SELECT AVG(rating) FROM course_reviews WHERE course_code = ?",
        (course_code,),
    ).fetchone()
    conn.close()
    avg = row[0]
    return float(avg) if avg is not None else None


# WHY run at import time: scoring.py loads the full course catalog at module
# import and calls get_avg_rating() for every course.  main.py cannot call
# init_reviews_db() before importing scoring, so the table must exist as soon
# as this module is loaded — same idempotent CREATE TABLE IF NOT EXISTS pattern.
init_reviews_db()
