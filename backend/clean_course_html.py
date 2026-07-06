"""
clean_course_html.py — One-time script to strip leftover HTML from course text fields.

The TTB scraper copies text straight from the calendar's rich-text fields, so
tags like <p> and <a href="..."> end up in the course JSON. They're just noise
to students reading a chat bubble and to Claude reading the system prompt.

Uses the standard-library html.parser rather than a regex (which breaks on
malformed or nested tags) or BeautifulSoup (an extra dependency); it also
unescapes entities like &amp; in the same pass.

Cleans both courses_slim.json and courses_all_enriched.json. The enriched file
is built on top of the slim one, so patching both keeps them in sync without
re-running the ~3200 paid Claude enrichment calls.

Usage (from inside backend/):
    python clean_course_html.py
"""
from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

# Fields known to contain scraped rich-text (verified via manual inspection —
# 'description' and 'name' were already clean, so they're left untouched).
_TEXT_FIELDS = ["prerequisites", "corequisites", "exclusions", "recommended_preparation"]

_FILES = ["courses_slim.json", "courses_all_enriched.json"]


class _TagStripper(HTMLParser):
    """Collects only the text data between tags, dropping the tags themselves."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)  # auto-unescapes &amp; etc.
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        self._chunks.append(data)

    def get_text(self) -> str:
        return "".join(self._chunks)


def strip_html(text: str) -> str:
    """Remove HTML tags and unescape entities, collapsing whitespace left behind."""
    if not text or "<" not in text:
        # Fast path: most fields have no markup, so skip the parser when there's no '<'.
        return text

    parser = _TagStripper()
    parser.feed(text)
    cleaned = parser.get_text()

    # Collapse whitespace runs to single spaces so removed tags don't leave
    # sentences run together or oddly spaced.
    return " ".join(cleaned.split())


def clean_file(path: Path) -> None:
    with open(path, encoding="utf-8") as f:
        courses = json.load(f)

    changed = 0
    for course in courses:
        for field in _TEXT_FIELDS:
            value = course.get(field)
            if isinstance(value, str):
                new_value = strip_html(value)
                if new_value != value:
                    course[field] = new_value
                    changed += 1

    with open(path, "w", encoding="utf-8") as f:
        json.dump(courses, f, indent=2, ensure_ascii=False)

    print(f"{path.name}: cleaned {changed} field(s) across {len(courses)} courses")


if __name__ == "__main__":
    base_dir = Path(__file__).parent
    for filename in _FILES:
        file_path = base_dir / filename
        if not file_path.exists():
            print(f"Skipping {filename} — not found")
            continue
        clean_file(file_path)
