# ok this is where we will define our scoring system
class AcademicHistory:
    courses: list[Course]

    def __init__(self, courses: list[Course]) -> None:
        self._courses = courses

    def get_courses(self) -> list[Course]:
        return self._courses
    def add_course(self, course: Course) -> None:
        self._courses.append(course)

class Course:

    name: str
    description: str
    prerequisites: list[str]
    corequisites: list[str]
    credits: int
    tags: list[str]
    workload: str
    difficulty: int
    rating: float
    reviews: list[str]
    def __init__(self, name: str, tags: list[str], description: str, prerequisites: list[str] = None, corequisites: list[str] = None, credits: float = 0.5, workload: int = 3, difficulty: int = 5, rating: float = None, reviews: list[str] = None) -> None:
        self._name = name
        self.tags = tags
        self.description = description
        self.prerequisites = prerequisites if prerequisites is not None else []
        self.corequisites = corequisites if corequisites is not None else []
        self.credits = credits
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

# Weights must sum to 1.0. Difficulty and workload are proximity-based
# (how close the course is to what the student wants), while rating is
# quality-based (higher is always better). Keeping them separate makes
# it easy to add new signals (e.g., interest match, major relevance) later.
INTEREST_WEIGHT = 0.35
WEIGHT_DIFFICULTY = 0.25
WEIGHT_WORKLOAD   = 0.25
WEIGHT_RATING     = 0.15

# Scales for each field — used to normalize raw values to 0–10.
DIFFICULTY_MIN, DIFFICULTY_MAX = 1, 10   # course.difficulty range
WORKLOAD_MIN,   WORKLOAD_MAX   = 1, 5    # course.workload range
RATING_MIN,     RATING_MAX     = 1, 5    # course.rating range (e.g., UofT eval scale)

# When a course has no rating yet, we assume a neutral mid-point rather
# than penalizing it for lacking data.
RATING_NEUTRAL = (RATING_MIN + RATING_MAX) / 2

def _interest_score(course, interests):
    matches = len(set(course.tags) & set(interests))
    return (matches / len(course.tags)) * 10 if course.tags else 0

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
        difficulty  25%  — proximity to preferred difficulty
        workload    25%  — proximity to preferred workload
        rating      15%  — normalized course rating (higher is always better)
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
    if c.is_eligible(preferences.get("completed_courses", []))]
    scored = [(course, score_course(course, preferences)) for course in eligible]

    # Sort descending by score; use course name as tiebreaker for stable ordering.
    scored.sort(key=lambda pair: (-pair[1], pair[0].name))

    return scored[:top_n] if top_n is not None else scored


# How far a course's difficulty/workload can be from the student's preference
# before we stop calling it a "match". Keeps explain() language honest —
# we won't say "matches your difficulty preference" if the gap is large.
_DIFFICULTY_MATCH_THRESHOLD = 2   # out of a 1–10 scale
_WORKLOAD_MATCH_THRESHOLD   = 1   # out of a 1–5 scale
_GOOD_RATING_THRESHOLD      = 4.0 # out of 5 — "well rated"


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

    return ", ".join(reasons)


courses = [
    Course(name="CSC108H1", description="Introduction to Computer Science", prerequisites=[], corequisites=[], credits=0.5, workload=3, difficulty=5, rating=None, reviews=None),
    Course(name="MAT137Y1", description="Calculus with Proofs", prerequisites=[], corequisites=[], credits=1.0, workload=3, difficulty=5, rating=None, reviews=None),
    Course(name="PSY100H1", description="Introduction to Psychology", prerequisites=[], corequisites=[], credits=0.5, workload=3, difficulty=5, rating=None, reviews=None),
    Course(name="MAT135H1", description="Calculus I", prerequisites=[], corequisites=[], credits=0.5, workload=3, difficulty=5, rating=None, reviews=None),
    Course(name="MAT136H1", description="Calculus II", prerequisites=["MAT135H1"], corequisites=[], credits=0.5, workload=3, difficulty=5, rating=None, reviews=None),
]

