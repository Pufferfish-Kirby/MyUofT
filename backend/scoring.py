# ok this is where we will define our scoring system
class Course:
    def __init__(self,
        name: str,
        description: str,
        tags: list[str] | None = None,
        prerequisites: list[str] | None = None,
        corequisites: list[str] | None = None,
        credits: float = 0.5,
        workload: int = 3,
        difficulty: int = 5,
        rating: float | None = None,
        reviews: list[str] | None = None,
    ) -> None:
        self._name = name
        self.tags = tags if tags is not None else []
        self.description = description
        self._prerequisites = prerequisites if prerequisites is not None else []
        self._corequisites = corequisites if corequisites is not None else []
        self._credits = credits
        self.workload = workload
        self.difficulty = difficulty
        self.rating = rating
        self.reviews = reviews if reviews is not None else []
    
    def get_name(self) -> str:
        return self._name
    def get_prerequisites(self) -> list[str]:
        return self._prerequisites
    def get_corequisites(self) -> list[str]:
        return self._corequisites
    def get_credits(self) -> float:
        return self._credits
    def is_eligible(self, completed: list[str]) -> bool:
        return all(prereq in completed for prereq in self.prerequisites)

class AcademicHistory:  # this is here once we can link the history to get courses they can take/can't take
    courses: list[Course]

    def __init__(self, courses: list[Course]) -> None:
        self._courses = courses

    def get_courses(self) -> list[Course]:
        return self._courses
    def add_course(self, course: Course) -> None:
        self._courses.append(course)

# Weights must sum to 1.0. Difficulty and workload are proximity-based
# (how close the course is to what the student wants), while rating is
# quality-based (higher is always better). Keeping them separate makes
# it easy to add new signals (e.g., interest match, major relevance) later.
#
# WHY these specific values:
#   Interest is still the biggest signal (35%) since a course that's
#   completely off-topic shouldn't score well even if the workload is perfect.
#   Rating was bumped to 20% because it's the most objective quality signal
#   we have — when all else is equal, students should get well-rated courses.
#   Difficulty and workload are each 22.5% — meaningful but not overriding.
INTEREST_WEIGHT   = 0.35
WEIGHT_DIFFICULTY = 0.225
WEIGHT_WORKLOAD   = 0.225
WEIGHT_RATING     = 0.20

# Synonym map: when a student types a natural-language interest, expand it
# to the technical tags we use on courses. This bridges the gap between
# "coding" (what students say) and "programming" (what our tags say).
# Phase 2 will replace this with embedding-based similarity; for now a
# manually curated map is cheap, transparent, and easy to extend.
INTEREST_SYNONYMS: dict[str, list[str]] = {
    "coding":       ["programming", "python", "java", "software", "computing", "code", "computer"],
    "programming":  ["coding", "python", "java", "software", "computing", "code", "computer"],
    "math":         ["mathematics", "calculus", "algebra", "statistics", "analysis", "proofs"],
    "mathematics":  ["math", "calculus", "algebra", "statistics", "analysis", "proofs"],
    "stats":        ["statistics", "data", "probability", "analysis"],
    "data":         ["statistics", "data science", "machine learning", "analysis", "python"],
    "ai":           ["machine learning", "artificial intelligence", "neural", "python", "data"],
    "biology":      ["life sciences", "biochemistry", "molecular", "genetics", "cell"],
    "chemistry":    ["organic", "inorganic", "biochemistry", "molecular", "reactions"],
    "psychology":   ["behavior", "social-science", "mental", "cognition", "research"],
    "writing":      ["english", "literature", "composition", "rhetoric", "essay"],
    "history":      ["historical", "civilization", "political", "social"],
    "economics":    ["micro", "macro", "finance", "markets", "policy"],
    "business":     ["management", "finance", "marketing", "economics", "strategy"],
    "design":       ["art", "visual", "creative", "ux", "interface"],
    "networks":     ["systems", "computer", "distributed", "internet", "protocol"],
    "security":     ["cryptography", "systems", "networks", "privacy", "cyber"],
}

# Scales for each field — used to normalize raw values to 0–10.
DIFFICULTY_MIN, DIFFICULTY_MAX = 1, 10   # course.difficulty range
WORKLOAD_MIN,   WORKLOAD_MAX   = 1, 5    # course.workload range
RATING_MIN,     RATING_MAX     = 1, 5    # course.rating range (e.g., UofT eval scale)

# When a course has no rating yet, we assume a neutral mid-point rather
# than penalizing it for lacking data.
RATING_NEUTRAL = (RATING_MIN + RATING_MAX) / 2

def _interest_score(course: "Course", interests: list[str]) -> float:
    """
    Score how well a course matches the student's interests (0–10).

    Matching works in two passes:
      1. Synonym expansion: "coding" expands to ["programming", "python", ...]
         so students don't need to know our internal tag vocabulary.
      2. Text search: each (expanded) interest term is checked against the
         course's tags AND its description words, case-insensitively.
         This catches cases where the tag doesn't exist but the description
         says "This course covers programming techniques…".

    WHY divide by interests length (not tags length):
        We want to reward courses that cover MANY of the student's interests,
        not just courses with few tags (which would make narrow courses look better).
        A course matching 2 out of 3 interests scores 6.67; one matching 1 out of 3
        scores 3.33 — proportional to how much of the student's agenda it covers.
    """
    if not interests:
        return 0.0

    # Build a single lowercase blob of all searchable text for this course.
    # We include tags, description, and the course code itself so that e.g.
    # "CSC" in the name can be matched by a "computer science" interest expansion.
    searchable = " ".join(course.tags + [course.description, course.get_name]).lower()

    matched = 0
    for raw_interest in interests:
        interest = raw_interest.lower().strip()
        if not interest:
            continue

        # Expand via synonym map, then also check the raw interest term itself.
        expanded_terms = INTEREST_SYNONYMS.get(interest, []) + [interest]

        # A single term match is enough to count this interest as satisfied.
        if any(term in searchable for term in expanded_terms):
            matched += 1

    return (matched / len(interests)) * 10.0

def _proximity_score(value: int | float, preferred: int | float, min_val: float, max_val: float) -> float:
    """
    Return a 0–10 score based on how close `value` is to `preferred`.

    A perfect match gives 10; the maximum possible distance gives 0.
    This lets students say "I want a workload of 2" and courses near 2
    score high while courses near 5 score low, regardless of direction.
    """
    max_distance = max_val - min_val          # e.g. 9 for difficulty, 4 for workload
    distance = abs(value - preferred)
    proximity = 1.0 - (distance / max_distance)   # 1.0 = perfect match, 0.0 = opposite end
    return proximity * 10.0


def _rating_score(rating: float | None) -> float:
    """
    Convert a raw rating (1–5 scale) to a 0–10 score.

    Unlike difficulty and workload, rating is not proximity-based —
    a higher rating is always better regardless of student preference.
    If no rating exists yet, fall back to the neutral mid-point so
    unrated courses aren't unfairly punished.
    """
    raw = rating if rating is not None else RATING_NEUTRAL
    # Normalize from [RATING_MIN, RATING_MAX] → [0, 10]
    return ((raw - RATING_MIN) / (RATING_MAX - RATING_MIN)) * 10.0


def score_course(course: "Course", preferences: dict) -> float:
    """
    Score a course from 0.0 to 10.0 (1 decimal place) based on how well
    it matches the student's preferences.

    Expected keys in `preferences`:
        preferred_difficulty (int, 1–10): how hard the student wants courses to be
        preferred_workload   (int, 1–5):  how much weekly effort they want

    Weights:
        difficulty  22.5%  — proximity to preferred difficulty
        workload    22.5%  — proximity to preferred workload
        rating      20%  — normalized course rating (higher is always better)
        interest    35%  — how well the course matches the student's interests

    Future signals (not yet implemented) will slot in here once we have
    interest vectors and program-fit data, and weights will be adjusted.
    """
    preferred_difficulty = preferences.get("preferred_difficulty", 5)
    preferred_workload   = preferences.get("preferred_workload", 3)

    diff_score   = _proximity_score(course.difficulty, preferred_difficulty, DIFFICULTY_MIN, DIFFICULTY_MAX)
    work_score   = _proximity_score(course.workload,   preferred_workload,   WORKLOAD_MIN,   WORKLOAD_MAX)
    rating_score = _rating_score(course.rating)
    interest_score = _interest_score(course, preferences.get("interests", []))

    raw = (
        WEIGHT_DIFFICULTY * diff_score +
        WEIGHT_WORKLOAD   * work_score +
        WEIGHT_RATING     * rating_score +
        INTEREST_WEIGHT   * interest_score
    )

    # Clamp to [0, 10] as a safety net, then round to 1 decimal place.
    return round(max(0.0, min(10.0, raw)), 1)


def recommend_courses(course_list: list["Course"], preferences: dict, top_n: int = None) -> list[tuple["Course", float]]:
    """
    Return courses sorted by their score (highest first).

    Each item in the returned list is a (course, score) tuple so the caller
    can display the score alongside the name without re-computing it.

    Args:
        course_list:  the pool of courses to rank (e.g. all courses in the DB)
        preferences:  same dict passed to score_course
        top_n:        if given, only return the top N results; otherwise return all

    This is intentionally a thin wrapper around score_course — the real
    intelligence lives there. As we add more signals (interest match, major fit)
    this function stays the same; only score_course changes.
    """
    eligible = [
        c for c in course_list
        if c.is_eligible(preferences.get("completed_courses", []))
    ]
    scored = [(course, score_course(course, preferences)) for course in eligible]

    # Filter out weak matches — showing a course with a score below 5 implies
    # it's at least somewhat relevant, which is misleading to the student.
    # If this filter removes everything (e.g. very niche input), the frontend
    # should show a "no strong matches" message rather than low-scoring filler.
    min_score = preferences.get("min_score", 5.0)
    scored = [(course, score) for course, score in scored if score >= min_score]

    # Sort descending by score; use public getter for stable tiebreak ordering.
    scored.sort(key=lambda pair: (-pair[1], pair[0].get_name()))

    return scored[:top_n] if top_n is not None else scored


# How far a course's difficulty/workload can be from the student's preference
# before we stop calling it a "match". Keeps explain() language honest —
# we won't say "matches your difficulty preference" if the gap is large.
_DIFFICULTY_MATCH_THRESHOLD = 2   # out of a 1–10 scale
_WORKLOAD_MATCH_THRESHOLD   = 1   # out of a 1–5 scale
_GOOD_RATING_THRESHOLD      = 4.0 # out of 5 — "well rated"


def explain_structured(course: "Course", preferences: dict) -> list[dict]:
    """
    Same logic as explain(), but returns a list of structured reason objects
    instead of a single joined string.

    WHY structured instead of a flat string:
        A plain string forces the frontend to parse meaning back out of English
        prose — fragile and unextendable. Structured reasons let the UI render
        each signal with its own icon, colour, or tooltip without any string splitting.

    Each reason dict has:
        type     (str)  — "difficulty" | "workload" | "rating" | "interest"
                          Lets the frontend pick an icon or colour per category.
        message  (str)  — the same human-readable phrase from explain()
        positive (bool) — True means "this is a green/positive signal",
                          False means "worth noting but cautionary".
                          The frontend uses this to decide chip colour.

    The list is ordered: difficulty → workload → rating → interest,
    matching the order in explain() so both outputs feel consistent.
    """
    reasons: list[dict] = []

    preferred_difficulty = preferences.get("preferred_difficulty", 5)
    preferred_workload   = preferences.get("preferred_workload", 3)

    # --- Difficulty ---
    diff_gap = abs(course.difficulty - preferred_difficulty)
    if diff_gap <= _DIFFICULTY_MATCH_THRESHOLD:
        reasons.append({
            "type": "difficulty",
            "message": "matches your preferred difficulty level",
            "positive": True,
        })
    elif course.difficulty < preferred_difficulty:
        reasons.append({
            "type": "difficulty",
            "message": "lighter than your usual preference (good for a busy semester)",
            "positive": True,
        })
    else:
        reasons.append({
            "type": "difficulty",
            "message": "more challenging than your preference (great if you want a stretch)",
            "positive": False,
        })

    # --- Workload ---
    work_gap = abs(course.workload - preferred_workload)
    if work_gap == _WORKLOAD_MATCH_THRESHOLD:
        reasons.append({
            "type": "workload",
            "message": "fits your workload preference",
            "positive": True,
        })
    elif course.workload < preferred_workload:
        reasons.append({
            "type": "workload",
            "message": "lower workload than you requested, but can still work",
            "positive": True,
        })
    elif course.workload > preferred_workload and 1 < work_gap <= 2:
        reasons.append({
            "type": "workload",
            "message": "heavier workload than you requested, but still manageable",
            "positive": False,
        })
    else:
        reasons.append({
            "type": "workload",
            "message": "a lot heavier than you requested",
            "positive": False,
        })

    # --- Rating ---
    # Same silence rule as explain(): only surface rating when it's notable.
    if course.rating is not None:
        if course.rating >= _GOOD_RATING_THRESHOLD:
            reasons.append({
                "type": "rating",
                "message": f"well rated by students ({course.rating}/5)",
                "positive": True,
            })
        elif course.rating < 3.0:
            reasons.append({
                "type": "rating",
                "message": f"lower student rating ({course.rating}/5) — worth considering",
                "positive": False,
            })

    # --- Interest match ---
    interests = preferences.get("interests", [])
    if interests:
        searchable = " ".join(course.tags + [course.description, course._name]).lower()
        matched_interests = [
            i for i in interests
            if any(t in searchable for t in INTEREST_SYNONYMS.get(i.lower().strip(), []) + [i.lower().strip()])
        ]
        if matched_interests:
            reasons.append({
                "type": "interest",
                "message": f"aligns with your interest in {', '.join(matched_interests)}",
                "positive": True,
            })
        else:
            reasons.append({
                "type": "interest",
                "message": "does not directly match your stated interests — consider as a breadth requirement",
                "positive": False,
            })

    return reasons


def explain(course: "Course", preferences: dict) -> str:
    """
    Generate a plain-English explanation of why a course was recommended.

    This is rule-based for now (fast, transparent, no AI cost). Each rule
    appends a short phrase; the phrases are joined into one readable sentence.
    When we add interest tags and major-fit signals later, new rules slot in
    here without touching the scoring logic.

    Returns an empty string if nothing notable matches — callers should handle
    that gracefully (e.g. "No specific reasons found.").
    """
    reasons = []

    preferred_difficulty = preferences.get("preferred_difficulty", 5)
    preferred_workload   = preferences.get("preferred_workload", 3)

    # --- Difficulty ---
    diff_gap = abs(course.difficulty - preferred_difficulty)
    if diff_gap <= _DIFFICULTY_MATCH_THRESHOLD:
        reasons.append("matches your preferred difficulty level")
    elif course.difficulty < preferred_difficulty:
        # Student wants harder courses; this one is lighter — still useful to flag.
        reasons.append("lighter than your usual preference (good for a busy semester)")
    else:
        reasons.append("more challenging than your preference (great if you want a stretch)")

    # --- Workload ---
    work_gap = abs(course.workload - preferred_workload)
    if work_gap <= _WORKLOAD_MATCH_THRESHOLD:
        reasons.append("fits your workload preference")
    elif course.workload < preferred_workload:
        reasons.append("lower workload than you requested")
    else:
        reasons.append("heavier workload than you requested")

    # --- Rating ---
    # Only mention rating when it exists and is actually notable; silence is
    # better than "no rating yet" cluttering every explanation.
    if course.rating is not None:
        if course.rating >= _GOOD_RATING_THRESHOLD:
            reasons.append(f"well rated by students ({course.rating}/5)")
        elif course.rating < 3.0:
            reasons.append(f"lower student rating ({course.rating}/5) — worth considering")

    # --- Interest match ---
    # Tell the student *why* this course appeared — or warn them if it's a
    # weak interest match so they know to look closer before enrolling.
    interests = preferences.get("interests", [])
    if interests:
        # Reuse the same expanded-term logic from _interest_score so the
        # explanation is always consistent with the actual score.
        searchable = " ".join(course.tags + [course.description, course._name]).lower()
        matched_interests = [
            i for i in interests
            if any(t in searchable for t in INTEREST_SYNONYMS.get(i.lower().strip(), []) + [i.lower().strip()])
        ]
        if matched_interests:
            reasons.append(f"aligns with your interest in {', '.join(matched_interests)}")
        else:
            reasons.append("does not directly match your stated interests — consider as a breadth requirement")

    return ", ".join(reasons) if reasons else "No specific reasons found."


courses = [
    Course(
        name="CSC108H1",
        description="Introduction to Computer Science",
        tags=["programming", "python", "computing", "problem-solving"],
        prerequisites=[],
        corequisites=[],
        credits=0.5,
        workload=3,
        difficulty=5,
        rating=None,
        reviews=None,
    ),
    Course(
        name="MAT137Y1",
        description="Calculus with Proofs",
        tags=["calculus", "proofs", "mathematics", "theory"],
        prerequisites=[],
        corequisites=[],
        credits=1.0,
        workload=4,
        difficulty=7,
        rating=None,
        reviews=None,
    ),
    Course(
        name="PSY100H1",
        description="Introduction to Psychology",
        tags=["psychology", "behavior", "social-science", "research"],
        prerequisites=[],
        corequisites=[],
        credits=0.5,
        workload=2,
        difficulty=4,
        rating=None,
        reviews=None,
    ),
    Course(
        name="MAT135H1",
        description="Calculus I",
        tags=["calculus", "algebra", "mathematics", "analysis"],
        prerequisites=[],
        corequisites=[],
        credits=0.5,
        workload=3,
        difficulty=5,
        rating=None,
        reviews=None,
    ),
    Course(
        name="MAT136H1",
        description="Calculus II",
        tags=["calculus", "integration", "mathematics", "applications"],
        prerequisites=["MAT135H1"],
        corequisites=[],
        credits=0.5,
        workload=3,
        difficulty=6,
        rating=None,
        reviews=None,
    ),
]

