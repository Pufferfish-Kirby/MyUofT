"""
program_data.py — Program data class and RAG search for UofT programs.

Mirrors the role scoring.py plays for courses. Provides:
  - Program dataclass with formatted_requirements for Claude context injection
  - load_programs() to read programs.json
  - search_programs_by_message() for semantic retrieval

Kept separate from scoring.py so importing it doesn't trigger scoring.py's
full course-catalog load and database queries — build_program_embeddings.py
imports this module and shouldn't pay that cost.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PROGRAMS_FILE = Path(__file__).parent / "app" / "data" / "programs.json"

_COURSE_CODE_RE = re.compile(r'\b([A-Z]{2,4}\d{3}[HY]?\d?[A-Z]?)\b')

_PROGRAM_STOP_WORDS: frozenset[str] = frozenset({
    "do", "does", "did", "can", "could", "would", "should", "will", "shall",
    "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had",
    "i", "me", "my", "we", "you", "your", "it", "its",
    "a", "an", "the", "any", "some", "no", "all",
    "to", "for", "of", "in", "on", "at", "by", "from", "with", "about",
    "and", "or", "but", "so", "if", "as",
    "want", "need", "like", "know", "think", "tell", "show", "give",
    "recommend", "suggest", "find", "get", "take",
    "please", "just", "really", "very", "more", "also",
    "what", "which", "who", "where", "when", "how", "why",
    "there", "here", "this", "that", "these", "those",
    "up", "out", "into", "than", "then", "now",
    # Program-specific noise — these appear in almost every program query
    # and carry no discriminating signal for finding a specific program.
    "program", "programs", "course", "courses",
    "credit", "credits",
    "enrol", "enrolment", "enroll", "enrollment",
    "require", "required", "requirement", "requirements",
    "available", "university", "toronto", "uoft",
})

# Match type keywords in this order, most specific first. "major" comes last
# because it's the most ambiguous — "major requirements" often just means "main
# requirements", and titles like "Specialist Major" would match it too early.
_PROGRAM_TYPE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bspecialist\b", re.IGNORECASE), "Specialist"),
    (re.compile(r"\bminor\b", re.IGNORECASE), "Minor"),
    (re.compile(r"\bcertificate\b", re.IGNORECASE), "Other"),
    (re.compile(r"\bmajor\b", re.IGNORECASE), "Major"),
]


def _strip_program_filler(text: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    meaningful = [t for t in tokens if t not in _PROGRAM_STOP_WORDS]
    return " ".join(meaningful) if meaningful else text


def _detect_program_type(text: str) -> str | None:
    for pattern, program_type in _PROGRAM_TYPE_PATTERNS:
        if pattern.search(text):
            return program_type
    return None


def _format_year_section(section: dict) -> str:
    lines = []
    heading = section.get("heading", "Requirements")
    credits = section.get("credits")
    header = f"{heading} ({credits} credits):" if credits else f"{heading}:"
    lines.append(header)

    # requirements: each item is either a str or a dict {text, options}
    for req in section.get("requirements") or []:
        if isinstance(req, str) and req.strip():
            lines.append(f"  - {req.strip()}")
        elif isinstance(req, dict):
            text = req.get("text", "")
            options = req.get("options") or []
            if options:
                # Each option is a list of courses (AND together within the option)
                formatted_options = " OR ".join(
                    "(" + ", ".join(o) + ")" if len(o) > 1 else o[0]
                    for o in options if o
                )
                lines.append(f"  - {text}: {formatted_options}")
            elif text:
                lines.append(f"  - {text}")

    # groups: Group A / B / C course selections
    for group in section.get("groups") or []:
        name = group.get("name", "Group")
        courses = group.get("courses", "")
        lines.append(f"  {name}: {courses}")

    # criteria: selection rules (truncate each to 200 chars)
    criteria = section.get("criteria") or []
    if criteria:
        lines.append("  Criteria:")
        for c in criteria:
            c = c.strip()
            lines.append(f"    - {c[:200]}{'...' if len(c) > 200 else ''}")

    # integrative_activity (truncate to 200 chars)
    ia = section.get("integrative_activity", "")
    if ia:
        ia = ia.strip()
        lines.append(f"  Integrative activity: {ia[:200]}{'...' if len(ia) > 200 else ''}")

    # notes (truncate each to 150 chars)
    for note in section.get("notes") or []:
        note = note.strip()
        if note:
            lines.append(f"  Note: {note[:150]}{'...' if len(note) > 150 else ''}")

    return "\n".join(lines)


# Maps a year level to its completion_requirements JSON key. Years 3 and 4 are
# intentionally absent — they fall back to "upper_years" (see
# _course_codes_for_year), since programs usually lump 3rd/4th year together.
_YEAR_SECTION_KEYS: dict[int, str] = {
    1: "first_year",
    2: "second_year",
}


def _course_codes_for_year(comp: dict, year: int) -> list[str]:
    """
    Pull course codes from just one year's completion-requirements section,
    rather than the whole program. Scoping it this way keeps a "what's my
    second year?" question from getting first/third/fourth year codes dumped
    into the prompt too (Program.course_codes covers the entire program).

    Years 3 and 4 fall back to "upper_years" when they have no dedicated key,
    since programs usually lump those two years together there. Years 1 and 2
    never fall back — a missing key means no such requirements, and falling
    back would wrongly pin upper-year courses onto a first/second year question.
    Returns an empty list when nothing matches.
    """
    key = _YEAR_SECTION_KEYS.get(year)
    section = comp.get(key) if key else None
    if not section and year in (3, 4):
        section = comp.get("upper_years")
    if not section or not isinstance(section, dict):
        return []
    section_text = json.dumps(section)
    return sorted(set(m.group(1) for m in _COURSE_CODE_RE.finditer(section_text)))


def _format_completion_requirements(comp: dict) -> str:
    """
    Render every field in completion_requirements into readable text so Claude
    can answer any program question from it. The admin fields (engineering
    courses, transfer credits, combining) are each included because each maps
    to a real student question, so dropping one silently breaks that answer.
    """
    parts = []

    # Year-based sections (in chronological order)
    for key in ("first_year", "second_year", "third_year", "fourth_year", "upper_years"):
        section = comp.get(key)
        if section and isinstance(section, dict):
            parts.append(_format_year_section(section))

    # Flat requirements list (some programs use this instead of year sections)
    # Items can be strings or {text, options} dicts — handle both.
    flat_reqs = comp.get("requirements")
    if flat_reqs and isinstance(flat_reqs, list):
        req_lines = ["Requirements:"]
        for req in flat_reqs:
            if isinstance(req, str) and req.strip():
                req_lines.append(f"  - {req.strip()}")
            elif isinstance(req, dict):
                text = req.get("text", "")
                options = req.get("options") or []
                if options:
                    formatted_options = " OR ".join(
                        "(" + ", ".join(o) + ")" if len(o) > 1 else o[0]
                        for o in options if o
                    )
                    req_lines.append(f"  - {text}: {formatted_options}")
                elif text:
                    req_lines.append(f"  - {text}")
        if len(req_lines) > 1:
            parts.append("\n".join(req_lines))

    # Administrative fields — answer common student questions
    if comp.get("engineering_courses"):
        parts.append(f"Engineering courses: {comp['engineering_courses']}")

    if comp.get("combining"):
        parts.append(f"Combining with other programs: {comp['combining']}")

    if comp.get("transfer_credits"):
        parts.append(f"Transfer credits: {comp['transfer_credits']}")

    return "\n\n".join(parts)


@dataclass
class Program:
    program_code: str
    name: str
    type: str                    # "Specialist" | "Major" | "Minor" | "Other"
    enrolment_general: str       # empty string if null/missing
    completion_summary: str      # e.g. "(8.0 credits, including...)"
    formatted_requirements: str  # output of _format_completion_requirements()
    course_codes: list[str]      # all UofT course codes extracted via regex
    asip: str | None
    # Course codes scoped to a single year, e.g. year_course_codes[2] is the
    # second-year codes only. Filled by _course_codes_for_year at load time so
    # a single-year question doesn't pull in the whole program's codes. Years
    # with no requirements found simply aren't present as keys.
    year_course_codes: dict[int, list[str]] = field(default_factory=dict)

    def get_program_code(self) -> str:
        return self.program_code

    def get_course_codes_for_year(self, year: int) -> list[str]:
        """Course codes for one year section only (empty list if none found)."""
        return self.year_course_codes.get(year, [])

    def to_text(self) -> str:
        """
        Produce a flat string for embedding only — Claude never sees this, it
        sees formatted_requirements. Name and type come first because the model
        truncates from the right at its token limit, so identity has to precede
        course codes; the 800-char cap keeps us within its effective range.
        """
        parts = [self.name, self.type]
        if self.completion_summary:
            parts.append(self.completion_summary)
        # Enrolment hint (first 120 chars) captures "limited enrolment" signal
        if self.enrolment_general:
            parts.append(self.enrolment_general[:120].rstrip())
        base = " ".join(parts)
        remaining = 800 - len(base) - 1
        if self.course_codes and remaining > 0:
            codes_str = " ".join(self.course_codes)
            parts.append(codes_str[:remaining])
        return " ".join(parts).strip()


def load_programs() -> list[Program]:
    """
    Load all programs from programs.json into Program objects. Course codes are
    pulled by regexing json.dumps(p) — the whole record as text — rather than
    walking the structure, since completion_requirements has 10+ keys at varying
    depths and a text regex catches them all in one pass regardless of shape.
    """
    with open(_PROGRAMS_FILE, encoding="utf-8") as f:
        data = json.load(f)

    programs = []
    for p in data:
        # One program has enrolment_requirements: null — guard against it
        enrol = p.get("enrolment_requirements") or {}
        comp = p.get("completion_requirements") or {}

        # Extract all unique UofT course codes from the entire program record
        all_text = json.dumps(p)
        codes = sorted(set(m.group(1) for m in _COURSE_CODE_RE.finditer(all_text)))

        # Pre-compute per-year codes at load time rather than per request,
        # since programs.json only changes on re-scrape and 169 programs x 4
        # years is negligible work.
        year_codes = {
            year: yc
            for year in (1, 2, 3, 4)
            if (yc := _course_codes_for_year(comp, year))
        }

        programs.append(Program(
            program_code=p["program_code"],
            name=p["name"],
            type=p.get("type", "Other"),
            enrolment_general=enrol.get("general") or "",
            completion_summary=comp.get("summary") or "",
            formatted_requirements=_format_completion_requirements(comp),
            course_codes=codes,
            asip=p.get("asip"),
            year_course_codes=year_codes,
        ))

    return programs


def search_programs_by_message(
    message: str,
    programs: list[Program],
    top_n: int = 3,
) -> list[tuple[Program, float]]:
    """
    Find the most relevant programs for a free-text message.

    Three-step pipeline mirroring search_by_message() in scoring.py:
      1. Type detection — restricts candidate pool to one program type when
         the user mentions "specialist", "major", "minor", or "certificate".
      2. Stop-word stripping — removes conversational filler before embedding.
      3. Semantic search with optional type mask.

    program_semantic_search is imported locally to avoid a circular-dependency
    risk and so this module stays importable even before the embeddings index
    is built — the import is only needed at actual search time.
    """
    from embeddings import program_semantic_search

    program_type = _detect_program_type(message)
    allowed_codes: set[str] | None = None
    if program_type is not None:
        allowed_codes = {p.program_code for p in programs if p.type == program_type}

    query = _strip_program_filler(message)

    code_to_program = {p.program_code: p for p in programs}
    results: list[tuple[Program, float]] = []
    for code, score in program_semantic_search(query, top_n=top_n, allowed_codes=allowed_codes):
        if code in code_to_program:
            results.append((code_to_program[code], score))
    return results
