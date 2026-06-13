"""
Enriches ALL courses in the dataset with AI-estimated difficulty and workload.

WHY this file exists vs. enrich_courses.py:
  enrich_courses.py was a quick experiment that scored a small CSC sample to
  validate the data shape. This script is the production run — it processes
  every course across all departments so the full dataset carries difficulty
  and workload metadata, not just a CS slice.

Three deliberate changes from the original:
  1. No sampling — every course in courses_slim.json is scored.
  2. Persona is an undeclared major student, not a CS student. Difficulty
     scores for a course like CSC108 look very different to someone who has
     never coded vs. someone who is already an average CS undergrad.
  3. Workload scale is 1–10 (not 1–5), giving finer resolution to distinguish
     e.g. a light 3-hr/week course from a moderate 5-hr/week one.

Run from the backend/ directory:
    python scripts/enrich_all_courses.py

Output lands on the desktop as courses_all_enriched.json so it stays out of
the repo and does NOT overwrite the CS-sample file from enrich_courses.py.
"""

import json
import os
import re
from pathlib import Path

import anthropic
from dotenv import load_dotenv

# Walk up from the script to find the .env file — dotenv searches parent
# directories automatically, so this works whether .env is in backend/ or root.
load_dotenv()

# Script lives at backend/scripts/, so parent.parent = backend/
COURSES_PATH = Path(__file__).parent.parent / "courses_slim.json"

# WHY a different filename: keeps this full-dataset run separate from the
# CSC-only sample so both files can coexist on the desktop for comparison.
OUTPUT_FILENAME = "courses_all_enriched.json"


def resolve_output_path(filename: str) -> Path:
    """
    Pick a writable output directory.

    WHY not Path.home() / "Desktop" alone: on Windows with OneDrive folder
    redirection, Desktop lives at ~/OneDrive/Desktop and ~/Desktop may not
    exist — open() then raises FileNotFoundError even though scoring succeeded.
    """
    candidates = [
        Path.home() / "Desktop",
        Path.home() / "OneDrive" / "Desktop",
        Path(__file__).parent.parent / "data",
    ]
    for directory in candidates:
        if directory.exists():
            return directory / filename
    # Last resort: create backend/data/ rather than fail after a long API run.
    fallback = candidates[-1]
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback / filename


OUTPUT_PATH = resolve_output_path(OUTPUT_FILENAME)


def course_prefix(code: str) -> str:
    """
    Extract the department prefix from a UofT course code (e.g. CSC from CSC207H1).

    WHY a regex instead of joining all letters: codes end in H1/Y1/F/S, so
    "".join(c for c in code if c.isalpha()) yields CSCH/ABPY — never matching
    STEM_PREFIXES entries like CSC or ABP.
    """
    match = re.match(r"^([A-Za-z]+)", code)
    return match.group(1).upper() if match else ""


def estimate_scores(
    client: anthropic.Anthropic,
    course: dict,
) -> dict[str, int | str | None]:
    """
    Ask Claude Haiku to score a course on difficulty and weekly workload.

    WHY ask for JSON directly (not wrapped in markdown): we parse
    programmatically; asking for bare JSON is simpler than stripping fences,
    and Haiku reliably follows this instruction when told explicitly.

    WHY include prerequisites in the prompt: a course titled "Advanced
    Topics in X" has very different difficulty if its prereq is one intro
    course vs. several upper-year courses — the prereq chain is often the
    strongest difficulty signal available.
    """
    code = course.get("code", "")
    name = course.get("name", "")
    description = course.get("description", "").strip()
    prereqs = course.get("prerequisites", "").strip()

    # WHY the undeclared-major persona instead of a CS-student persona:
    # This dataset spans ALL departments (humanities, sciences, social sciences,
    # etc.). Calibrating for a CS student would wildly misrepresent difficulty
    # for non-technical courses — a philosophy seminar might look trivially easy
    # to a CS student but genuinely challenging to someone encountering academic
    # argument and close reading for the first time. An undeclared-major student
    # is the most neutral baseline that applies fairly across every department.
    prompt = f"""You are estimating difficulty and weekly workload for a University of Toronto course planner.

Calibrate every score from the perspective of an AVERAGE UofT undeclared-major student — someone who:
- Has NOT declared a major and is still exploring what subjects interest them
- Has NO assumed programming, lab, or specialist background — may never have coded before and has no particular strength in any academic discipline yet
- Has a broad but shallow academic background: some high school math and science, possibly one or two first-year university courses, but no deep expertise in anything
- Is encountering most subject areas for the first time without specialist context to draw on
- Is NOT a top-10% student or a high-achieving specialist — think the typical first- or second-year student figuring out university
- Earns roughly a C+ (68%) on average, consistent with the typical grade distribution in UofT courses — use this as a calibration anchor for what "manageable with effort" actually looks like
- Experiences normal first- and second-year time pressure from multiple courses, extracurriculars, and adjustment to university life

Do NOT calibrate for the star student who breezes through everything, or the struggling student who finds every course hard. Aim for the middle of the bell curve.
Calibrate difficulty especially from the lens of someone encountering this subject for the first time, with no specialist context.

Course: {code} — {name}
Description: {description if description else "(no description available)"}
Prerequisites: {prereqs if prereqs else "None"}

Return ONLY a JSON object — no markdown fences, no extra text:
{{
  "difficulty": <integer 1–10>,
  "workload": <integer 1–10>,
  "reasoning": "<one sentence, no semicolons — explain the dominant factor only. COUNT your words before returning. If your reasoning exceeds 20 words, rewrite it shorter. Do not exceed 20 words under any circumstances.>"
}}

Difficulty scale (from the undeclared-major student's perspective):
  1–3 = introductory — little to no prior knowledge assumed; concepts are self-contained and approachable for any curious student
  4–6 = intermediate — builds on some foundation (high school math, prior first-year course, or general literacy in the subject); requires genuine engagement but is manageable with consistent effort
  7–9 = advanced — demands real disciplinary maturity or accumulated background that most students only develop over time; upper-year prerequisites are actually needed
  10  = graduate-level or unusually demanding even by 4th-year standards

Workload scale (hours per week outside of lecture/tutorial, for an average student):
  1–2  = very light  (≈1–3 hrs/week  — occasional readings or very small, infrequent assignments)
  3–4  = light       (≈3–5 hrs/week  — regular readings or short problem sets most weeks)
  5–6  = moderate    (≈6–9 hrs/week  — consistent weekly assignments with meaningful depth; a typical 300-level course)
  7–8  = heavy       (≈10–14 hrs/week — large projects, frequent deliverables, or difficult problem sets; most students feel real time pressure)
  9–10 = very heavy  (15+ hrs/week   — capstone or unusually output-intensive course; students routinely report it consuming most of their semester)

Calibration anchors for workload:
  A first-year survey course with weekly readings and one essay per month   → 2
  A 200-level course with biweekly assignments and one midterm paper        → 4
  A 300-level course with a multi-week project and demanding problem sets   → 6
  A mid-level STEM course (e.g. a 300-level CS/math/physics course) with weekly
    problem sets, a lab or coding component every 1–2 weeks, and a multi-week
    project due near the end of term — the kind of course where a typical student
    spends 10–12 hrs/week between debugging, derivations, and write-ups          → 7
  A 400-level seminar with weekly response papers and a major research essay→ 8
  A capstone or intensive lab course requiring sustained full-semester output→ 9
Use these anchors to sanity-check your estimate. Err toward the lower end of each band when uncertain — it is better to underestimate slightly than to inflate scores."""

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()

    # Strip markdown fences defensively — Haiku sometimes adds them anyway
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    try:
        parsed = json.loads(raw)
        return {
            "difficulty": int(parsed["difficulty"]),
            "workload": int(parsed["workload"]),
            "difficulty_reasoning": str(parsed.get("reasoning", "")),
        }
    except (json.JSONDecodeError, KeyError, ValueError):
        # Store the raw text so we can debug bad responses without re-running
        return {
            "difficulty": None,
            "workload": None,
            "difficulty_reasoning": f"PARSE_ERROR: {raw[:200]}",
        }


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set — add it to your .env file or environment"
        )

    client = anthropic.Anthropic(api_key=api_key)

    print(f"Loading courses from {COURSES_PATH}")
    with open(COURSES_PATH, encoding="utf-8") as f:
        all_courses: list[dict] = json.load(f)

    # ── SAMPLE MODE (optional) ────────────────────────────────────────────────
    # Set SAMPLE_MODE = True to score one random course per department (max 10)
    # instead of the full catalog — useful for prompt tuning without full API cost.
    SAMPLE_MODE = True
    STEM_ONLY_SAMPLE = True
    STEM_PREFIXES = {
        "CSC", "MAT", "STA", "PHY", "CHM", "BIO", "BCH", "EEB", "PSY",
        "ENV", "ESS", "AST", "ECE", "MSE", "CHE", "MIE", "CIV", "BME",
        "APS", "MGY", "IMM", "HMB", "ANT", "GGR", "PCL", "JEE",
    }

    if SAMPLE_MODE:
        import random

        seen_prefixes: set[str] = set()
        sampled: list[dict] = []
        shuffled = all_courses[:]
        random.shuffle(shuffled)

        if STEM_ONLY_SAMPLE:
            shuffled = [
                c for c in shuffled
                if course_prefix(c.get("code", "")) in STEM_PREFIXES
            ]

        for course in shuffled:
            prefix = course_prefix(course.get("code", ""))
            if prefix and prefix not in seen_prefixes:
                seen_prefixes.add(prefix)
                sampled.append(course)
            if len(sampled) == 10:
                break
        all_courses = sampled
    # ── END SAMPLE MODE ───────────────────────────────────────────────────────

    # WHY no sampling or filtering here: unlike enrich_courses.py which took a
    # CSC-only sample for a quick proof-of-concept, this script's whole purpose
    # is to produce a complete enriched dataset. Every course gets scored so
    # that difficulty/workload metadata is uniformly available at query time —
    # no gaps that would silently break "heavy semester" warnings for non-CS courses.
    print(f"\nEnriching {len(all_courses)} courses:")

    enriched: list[dict] = []
    for i, course in enumerate(all_courses, 1):
        code = course.get("code", "")
        print(f"\n[{i}/{len(all_courses)}] Scoring {code}...")

        scores = estimate_scores(client, course)

        if scores["difficulty"] is not None:
            # WHY /10 for both: workload is now on a 1–10 scale to match difficulty
            # and give finer resolution between e.g. 3 hrs/week and 5 hrs/week.
            print(f"  difficulty={scores['difficulty']}/10  workload={scores['workload']}/10")
        else:
            print(f"  ERROR: {scores['difficulty_reasoning']}")

        print(f"  {scores['difficulty_reasoning']}")

        enriched.append({**course, **scores})

    output_path = resolve_output_path(OUTPUT_FILENAME)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(enriched, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(enriched)} enriched courses → {output_path}")


if __name__ == "__main__":
    main()
