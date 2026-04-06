# ok this is where we will define our scoring system
class Course:

    name: str
    description: str
    prerequisites: list[str]
    corequisites: list[str]
    credits: int
    workload: str
    difficulty: int
    rating: float
    reviews: list[str]
    def __init__(self, name: str, description: str, prerequisites: list[str] = None, corequisites: list[str] = None, credits: float = 0.5, workload: int = 3, difficulty: int = 5, rating: float = None, reviews: list[str] = None) -> None:
        self.name = name
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

# Weights must sum to 1.0. Difficulty and workload are proximity-based
# (how close the course is to what the student wants), while rating is
# quality-based (higher is always better). Keeping them separate makes
# it easy to add new signals (e.g., interest match, major relevance) later.
WEIGHT_DIFFICULTY = 0.40
WEIGHT_WORKLOAD   = 0.40
WEIGHT_RATING     = 0.20

# Scales for each field — used to normalize raw values to 0–10.
DIFFICULTY_MIN, DIFFICULTY_MAX = 1, 10   # course.difficulty range
WORKLOAD_MIN,   WORKLOAD_MAX   = 1, 5    # course.workload range
RATING_MIN,     RATING_MAX     = 1, 5    # course.rating range (e.g., UofT eval scale)

# When a course has no rating yet, we assume a neutral mid-point rather
# than penalizing it for lacking data.
RATING_NEUTRAL = (RATING_MIN + RATING_MAX) / 2


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
        difficulty  40%  — proximity to preferred difficulty
        workload    40%  — proximity to preferred workload
        rating      20%  — normalized course rating (higher is always better)

    Future signals (not yet implemented) will slot in here once we have
    interest vectors and program-fit data, and weights will be adjusted.
    """
    preferred_difficulty = preferences.get("preferred_difficulty", 5)
    preferred_workload   = preferences.get("preferred_workload", 3)

    diff_score   = _proximity_score(course.difficulty, preferred_difficulty, DIFFICULTY_MIN, DIFFICULTY_MAX)
    work_score   = _proximity_score(course.workload,   preferred_workload,   WORKLOAD_MIN,   WORKLOAD_MAX)
    rating_score = _rating_score(course.rating)

    raw = (
        WEIGHT_DIFFICULTY * diff_score +
        WEIGHT_WORKLOAD   * work_score +
        WEIGHT_RATING     * rating_score
    )

    # Clamp to [0, 10] as a safety net, then round to 1 decimal place.
    return round(max(0.0, min(10.0, raw)), 1)


courses = [
    Course(name="CSC108H1", description="Introduction to Computer Science", prerequisites=[], corequisites=[], credits=0.5, workload=3, difficulty=5, rating=None, reviews=None),
    Course(name="MAT137Y1", description="Calculus with Proofs", prerequisites=[], corequisites=[], credits=1.0, workload=3, difficulty=5, rating=None, reviews=None),
    Course(name="PSY100H1", description="Introduction to Psychology", prerequisites=[], corequisites=[], credits=0.5, workload=3, difficulty=5, rating=None, reviews=None),
    Course(name="MAT135H1", description="Calculus I", prerequisites=[], corequisites=[], credits=0.5, workload=3, difficulty=5, rating=None, reviews=None),
    Course(name="MAT136H1", description="Calculus II", prerequisites=["MAT135H1"], corequisites=[], credits=0.5, workload=3, difficulty=5, rating=None, reviews=None),
]

