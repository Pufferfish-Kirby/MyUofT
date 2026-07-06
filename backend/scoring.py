# ok this is where we will define our scoring system
import json
import re
from pathlib import Path
from reviews_db import get_avg_rating

# Use __file__ so this works regardless of which directory the process is launched from.
# Without this, `open("courses_slim.json")` resolves against CWD, which breaks when
# build_embeddings.py or tests are run from the project root instead of backend/.
_DATA_FILE = Path(__file__).parent / "courses_all_enriched.json"  # enriched file adds AI-generated difficulty/workload per course
with open(_DATA_FILE, "r", encoding="utf-8") as file:
    data = json.load(file)

class Course:
    def __init__(self,
        code: str,
        name: str,
        description: str,
        tags: list[str] | None = None,
        prerequisites: str | None = None,
        corequisites: str | None = None,
        credits: float = 0.5,
        workload: int = 5,
        difficulty: int = 5,
        rating: float | None = None,
        reviews: list[str] | None = None,
        breadth: list[str] | None = None,
        sessions: list[str] | None = None,
    ) -> None:
        self._code = code
        self._name = name
        self.tags = tags if tags is not None else []
        self.description = description
        self._prerequisites = prerequisites if prerequisites is not None else ""
        self._corequisites = corequisites if corequisites is not None else ""
        self._credits = credits
        self.workload = workload
        self.difficulty = difficulty
        self.rating = rating
        self.reviews = reviews if reviews is not None else []
        # Kept as their own fields (not folded into `tags`) so the chat context
        # builder can surface them verbatim to Claude. `tags` intentionally
        # flattens department+breadth for keyword scoring, which loses the
        # "this is a breadth requirement" vs "this is a department" distinction —
        # for RAG context we want the real breadth categories, unmangled.
        self._breadth = breadth if breadth is not None else []
        self._sessions = sessions if sessions is not None else []

    def get_course_code(self) -> str:
        return self._code
    def get_name(self) -> str:
        return self._name
    def get_description(self) -> str:
        return self.description
    def get_prerequisites(self) -> list[str]:
        return self._prerequisites
    def get_corequisites(self) -> list[str]:
        return self._corequisites
    def get_credits(self) -> float:
        return self._credits
    def get_breadth(self) -> list[str]:
        # Raw breadth-requirement strings as scraped, e.g.
        # "The Physical and Mathematical Universes (5)". Returned as-is so the
        # trailing category number is preserved — callers can show it verbatim.
        return self._breadth
    def get_sessions(self) -> list[str]:
        # Raw UofT session codes (e.g. "20269", "20271"). Prefer
        # get_terms_offered() for anything user-facing.
        return self._sessions
    def get_terms_offered(self) -> list[str]:
        # Translate the opaque 5-digit session codes into human-readable terms.
        # WHY: the scraped data stores sessions as codes like "20269"/"20271"
        # whose last digit encodes the term (UofT convention: 9=Fall, 1=Winter,
        # 5=Summer). Claude can't reason about these codes, so we decode them to
        # "Fall"/"Winter"/"Summer" before injecting into the prompt context.
        # De-duplicated (a Y course can list the same term across two years)
        # while preserving first-seen order.
        term_by_last_digit = {"9": "Fall", "1": "Winter", "5": "Summer"}
        terms: list[str] = []
        for code in self._sessions:
            term = term_by_last_digit.get(code[-1:]) if code else None
            if term and term not in terms:
                terms.append(term)
        return terms
    def is_eligible(self, completed: list[str]) -> bool:
        # A course is eligible only if EVERY top-level clause is satisfied
        # (AND), and a clause is satisfied if ANY ONE of its options is fully
        # completed (OR) -- see parse_prerequisites() for the grammar this
        # respects (including parenthesized AND-pairs like "(STA237H1,
        # STA238H1)", which need both codes completed together, not either).
        clauses = parse_prerequisites(self._prerequisites)
        return all(
            any(all(code in completed for code in option) for option in options)
            for options in clauses
        )

    def to_text(self) -> str:
        # Joins the most signal-rich fields into one string for embedding.
        # Code first so the model sees the department prefix (MAT, CSC, etc.)
        # before the name, giving code-prefix queries a strong anchor.
        tags_str = " | ".join(self.tags) if self.tags else ""
        return f"{self._code} {self._name}. {self.description} {tags_str}".strip()

class AcademicHistory:  # this is here once we can link the history to get courses they can take/can't take
    courses: list[Course]

    def __init__(self, courses: list[Course]) -> None:
        self._courses = courses

    def get_courses(self) -> list[Course]:
        return self._courses
    def add_course(self, course: Course) -> None:
        self._courses.append(course)

# Weightings
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
    # General programming intents — these are the "hub" terms everything else maps to
    "coding":           ["programming", "python", "java", "software", "computing", "code", "computer",
                         "algorithms", "web", "javascript"],
    "programming":      ["coding", "python", "java", "software", "computing", "code", "computer",
                         "algorithms", "web", "javascript"],
    # Specific languages/technologies — map back to the hub so "python" == "coding" in matching power
    "python":           ["programming", "coding", "software", "computing", "code", "computer", "scripting"],
    "java":             ["programming", "coding", "software", "computing", "code", "computer", "object-oriented"],
    "javascript":       ["programming", "coding", "software", "web", "computing", "code", "computer"],
    "software":         ["programming", "coding", "python", "java", "computing", "code", "computer"],
    "computing":        ["programming", "coding", "python", "java", "software", "code", "computer"],
    "algorithms":       ["programming", "computing", "discrete", "complexity", "data structures", "problem"],
    "web":              ["programming", "software", "html", "css", "javascript", "frontend", "interface"],
    # Math family
    "math":             ["mathematics", "calculus", "algebra", "statistics", "analysis", "proofs", "proof",
                         "theorem", "discrete", "linear", "differential", "logic", "rigorous", "number theory"],
    "mathematics":      ["math", "calculus", "algebra", "statistics", "analysis", "proofs", "proof",
                         "theorem", "discrete", "linear", "differential", "logic", "rigorous"],
    "stats":            ["statistics", "probability", "analysis", "stochastic", "inference", "regression"],
    # Data / AI family
    "data":             ["statistics", "data science", "machine learning", "analysis", "python", "dataset"],
    "ai":               ["machine learning", "artificial intelligence", "neural", "deep learning",
                         "natural language", "computer vision", "reinforcement", "prediction"],
    "machine learning": ["ai", "artificial intelligence", "neural", "deep learning", "data",
                         "prediction", "statistics"],
    # Sciences
    "biology":          ["life sciences", "biochemistry", "molecular", "genetics", "cell"],
    "chemistry":        ["organic", "inorganic", "biochemistry", "molecular", "reactions"],
    "psychology":       ["behavior", "social-science", "mental", "cognition", "research"],
    # Humanities / Social
    "writing":          ["english", "literature", "composition", "rhetoric", "essay"],
    "history":          ["historical", "civilization", "political", "social"],
    "economics":        ["micro", "macro", "finance", "markets", "policy"],
    "business":         ["management", "finance", "marketing", "economics", "strategy"],
    # Other
    "design":           ["art", "visual", "creative", "ux", "interface"],
    "networks":         ["systems", "computer", "distributed", "internet", "protocol"],
    "security":         ["cryptography", "systems", "networks", "privacy", "cyber"],
}

# Scales for each field — used to normalize raw values to 0–10.
DIFFICULTY_MIN, DIFFICULTY_MAX = 1, 10   # course.difficulty range
WORKLOAD_MIN,   WORKLOAD_MAX   = 1, 10   # course.workload range
RATING_MIN,     RATING_MAX     = 1, 5    # course.rating range (e.g., UofT eval scale)

# When a course has no rating yet, we assume a neutral mid-point rather
# than penalizing it for lacking data.
RATING_NEUTRAL = (RATING_MIN + RATING_MAX) / 2

# JSON TO COURSE CONVERSION
courses = []  
for c in data:
    # tags: department + breadth requirements give cheap topic signals without a tagging pipeline
    pseudo_tags = [c.get('department', '')] + c.get('breadth_requirements', [])
    courses.append(Course(
        c['code'],
        c['name'],           # English title e.g. "Calculus and Analysis I" — richest keyword source
        c['description'],
        tags=pseudo_tags,
        prerequisites=c['prerequisites'],
        corequisites=c['corequisites'],
        credits=c['credit_value'],
        difficulty=c.get("difficulty") or 5,  # AI-scored 1–10; fallback to 5 if null/missing/0
        workload=c.get("workload") or 5,       # AI-scored 1–10; fallback to 5 if null/missing/0
        # Pre-computed once at startup into Course objects rather than queried per request,
        # keeping the hot recommendation path O(n) without DB calls on every /recommend hit.
        rating=get_avg_rating(c['code']),  # None when no reviews exist; Course uses RATING_NEUTRAL fallback
        # Kept separately (in addition to being folded into pseudo_tags above) so
        # the chat RAG context can present the real breadth categories + terms.
        breadth=c.get('breadth_requirements', []),
        sessions=c.get('sessions', []),
    ))

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

    # Search three fields separately so we can weight by signal strength.
    # WHY: a binary "anywhere in the text" match treats CSC108's title "Computer
    # Programming" the same as a chemistry course that incidentally mentions
    # "software" once in its description. Title hits are near-definitive;
    # description hits are weak evidence at best.
    title_blob = (course.get_name() + " " + course.get_course_code()).lower()
    tags_blob  = " ".join(course.tags).lower()        # department + breadth requirements
    desc_blob  = course.description.lower()

    # Per-field weights. Title=1.0 means a single title hit alone gives full
    # credit for that interest; description=0.4 means a description-only hit
    # is real but soft evidence. Tags (department) sit in between.
    TITLE_W, TAGS_W, DESC_W = 1.0, 0.7, 0.4

    total = 0.0
    for raw_interest in interests:
        interest = raw_interest.lower().strip()
        if not interest:
            continue

        expanded_terms = INTEREST_SYNONYMS.get(interest, []) + [interest]

        # Take the strongest field where any synonym hits — don't double-count
        # the same interest just because it appears in multiple fields.
        best = 0.0
        for term in expanded_terms:
            if term in title_blob:
                best = max(best, TITLE_W)
            elif term in tags_blob:
                best = max(best, TAGS_W)
            elif term in desc_blob:
                best = max(best, DESC_W)
        total += best

    return min(10.0, (total / len(interests)) * 10.0)

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


def score_course(course: "Course", preferences: dict, interest_score: float | None = None) -> float:
    """
    Score a course from 0.0 to 10.0 (1 decimal place) based on how well
    it matches the student's preferences.

    Expected keys in `preferences`:
        preferred_difficulty (int, 1–10): how hard the student wants courses to be
        preferred_workload   (int, 1–10): how much weekly effort they want

    Weights:
        difficulty  22.5%  — proximity to preferred difficulty
        workload    22.5%  — proximity to preferred workload
        rating      20%    — normalized course rating (higher is always better)
        interest    35%    — how well the course matches the student's interests

    The optional `interest_score` parameter lets callers inject a pre-computed
    value (e.g. a normalised semantic similarity score from recommend_courses).
    When omitted, the keyword-based _interest_score() is used as a fallback so
    this function remains usable without a pre-built embedding index.
    """
    preferred_difficulty = preferences.get("preferred_difficulty", 5)
    preferred_workload   = preferences.get("preferred_workload", 3)

    diff_score   = _proximity_score(course.difficulty, preferred_difficulty, DIFFICULTY_MIN, DIFFICULTY_MAX)
    work_score   = _proximity_score(course.workload,   preferred_workload,   WORKLOAD_MIN,   WORKLOAD_MAX)
    rating_score = _rating_score(course.rating)

    if interest_score is None:
        interest_score = _interest_score(course, preferences.get("interests", []))

    raw = (
        WEIGHT_DIFFICULTY * diff_score +
        WEIGHT_WORKLOAD   * work_score +
        WEIGHT_RATING     * rating_score +
        INTEREST_WEIGHT   * interest_score
    )

    # Clamp to [0, 10] as a safety net, then round to 1 decimal place.
    return round(max(0.0, min(10.0, raw)), 1)


def recommend_courses(course_list: list["Course"], preferences: dict, top_n: int = 5) -> list[tuple["Course", float]]:
    """
    Return the top courses sorted by score (highest first).

    Uses a two-phase approach:
      1. Semantic pre-filter — for each interest, call semantic_search() to
         get the top 50 embedding-nearest courses. Take the union across all
         interests, keeping the best similarity score per course. This limits
         scoring to the ~50-150 most conceptually relevant candidates instead
         of the entire 3000-course catalog, which prevents keyword false-positives
         (e.g. a history-of-computing course scoring the same as CSC108 because
         both mention the word "computing").
      2. Full scoring — run score_course() on each candidate, injecting the
         normalised semantic similarity as the interest score component. The
         similarity is normalised relative to the top match so the best
         candidate always receives 10/10 and others scale down proportionally.

    WHY normalise relative to the top match rather than using raw cosine similarity:
        Raw cosine values vary by query ("coding" might have a max sim of 0.65
        while "machine learning" peaks at 0.82). Normalising removes this
        query-to-query variance so the interest weight (35%) is consistent
        regardless of how well the embedding space separates a particular topic.

    Args:
        course_list:  the pool of courses to rank (all courses in the DB)
        preferences:  same dict passed to score_course
        top_n:        cap on returned results; None returns all passing min_score
    """
    from embeddings import semantic_search  # local import avoids circular dep at module load

    interests = preferences.get("interests", [])
    completed = preferences.get("completed_courses", [])

    if interests:
        # Query the embedding index once per interest and union the results.
        # top_n=50 per interest gives ample candidate coverage without scoring
        # the full catalog. Courses that match multiple interests keep the best sim.
        code_to_sim: dict[str, float] = {}
        for interest in interests:
            for code, sim in semantic_search(interest, top_n=50):
                code_to_sim[code] = max(code_to_sim.get(code, 0.0), sim)

        # Normalise to [0, 10] so the top semantic match always scores 10/10.
        max_sim = max(code_to_sim.values()) if code_to_sim else 1.0

        code_to_course = {c.get_course_code(): c for c in course_list}
        candidates: list[tuple["Course", float]] = [
            (code_to_course[code], min(10.0, (sim / max_sim) * 10.0))
            for code, sim in code_to_sim.items()
            if code in code_to_course
        ]

        eligible = [
            (course, interest_score)
            for course, interest_score in candidates
            if course.is_eligible(completed)
        ]
    else:
        # No interests provided — fall back to full catalog with interest score = 0.
        # Courses are ranked purely by difficulty/workload/rating proximity.
        eligible = [
            (course, 0.0)
            for course in course_list
            if course.is_eligible(completed)
        ]

    scored = [
        (course, score_course(course, preferences, interest_score))
        for course, interest_score in eligible
    ]

    # Filter out weak matches — a score below 5 implies marginal relevance,
    # which is misleading. If this removes everything, the frontend should show
    # a "no strong matches" message rather than showing low-scoring filler.
    min_score = preferences.get("min_score", 5.0)
    scored = [(c, s) for c, s in scored if s >= min_score]

    scored.sort(key=lambda pair: (-pair[1], pair[0].get_course_code()))
    return scored[:top_n] if top_n is not None else scored


# How far a course's difficulty/workload can be from the student's preference
# before we stop calling it a "match". Keeps explain() language honest —
# we won't say "matches your difficulty preference" if the gap is large.
_DIFFICULTY_MATCH_THRESHOLD = 2   # out of a 1–10 scale
_WORKLOAD_MATCH_THRESHOLD   = 2   # out of a 1–10 scale
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
    if work_gap <= _WORKLOAD_MATCH_THRESHOLD:
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
        searchable = " ".join(course.tags + [course.description, course.get_name()]).lower()
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
        searchable = " ".join(course.tags + [course.description, course.get_name()]).lower()
        matched_interests = [
            i for i in interests
            if any(t in searchable for t in INTEREST_SYNONYMS.get(i.lower().strip(), []) + [i.lower().strip()])
        ]
        if matched_interests:
            reasons.append(f"aligns with your interest in {', '.join(matched_interests)}")
        else:
            reasons.append("does not directly match your stated interests — consider as a breadth requirement")

    return ", ".join(reasons) if reasons else "No specific reasons found."

def _extract_interests_from_text(text: str) -> list[str]:
    """
    Pull interest keywords out of free text by matching against INTEREST_SYNONYMS.

    Two passes so multi-word phrases like "machine learning" are caught before
    their component words ("machine", "learning") are checked individually.
    Once a phrase is matched it's blanked out so the single-word pass doesn't
    double-count the same concept.

    Returns deduplicated list in first-seen order.
    """
    text_lower = text.lower()
    found: list[str] = []
    seen: set[str] = set()

    # Full vocabulary: keys of the map plus every synonym value
    # WHY include values: a student might type "programming" directly, which is a
    # synonym value but not a key — we still want to treat it as a known interest.
    all_known: set[str] = set(INTEREST_SYNONYMS.keys())
    for synonyms in INTEREST_SYNONYMS.values():
        all_known.update(synonyms)

    # Pass 1: longest multi-word phrases first so "machine learning" wins over "machine"
    multi_word = sorted((t for t in all_known if " " in t), key=len, reverse=True)
    for phrase in multi_word:
        if phrase in text_lower and phrase not in seen:
            found.append(phrase)
            seen.add(phrase)
            text_lower = text_lower.replace(phrase, " ")

    # Pass 2: remaining single words — use regex to strip punctuation before matching
    for word in re.findall(r"[a-z]+", text_lower):
        if word in all_known and word not in seen:
            found.append(word)
            seen.add(word)

    return found


# Matches UofT course codes with or without the suffix: MAT148, MAT148H1, CSC108H5S, ECO101Y1
_COURSE_CODE_RE = re.compile(r'\b([A-Z]{2,4}\d{3}[HY]?\d?)\b', re.IGNORECASE)

# Words that carry no semantic signal for course retrieval. Stripping these before
# embedding prevents conversational phrasing ("Do you have any coding courses to
# recommend to a first year") from pulling the query vector toward generic filler
# and away from the meaningful terms ("coding", "first year").
# WHY a frozenset: O(1) membership test; we check every token so speed matters.
_STOP_WORDS: frozenset[str] = frozenset({
    # question/conversational openers
    "do", "does", "did", "can", "could", "would", "should", "will", "shall",
    "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had",
    # pronouns
    "i", "me", "my", "we", "you", "your", "it", "its",
    # articles / determiners
    "a", "an", "the", "any", "some", "no", "all",
    # prepositions / conjunctions
    "to", "for", "of", "in", "on", "at", "by", "from", "with", "about",
    "and", "or", "but", "so", "if", "as",
    # filler verbs & adverbs in course queries
    "want", "need", "like", "know", "think", "tell", "show", "give",
    "recommend", "suggest", "find", "get", "take",
    "please", "just", "really", "very", "more", "also",
    # question words (after stripping these the nouns/topics remain)
    "what", "which", "who", "where", "when", "how", "why",
    # other high-frequency noise
    "there", "here", "this", "that", "these", "those",
    "up", "out", "into", "than", "then", "now",
})


def _strip_filler(text: str) -> str:
    """
    Remove stop words from a free-text query before embedding.

    Keeps only tokens that carry subject-matter signal so the embedding
    vector reflects the student's actual topic intent rather than conversational
    framing. Preserves the relative order of meaningful tokens.

    Example:
        "Do you have any coding courses to recommend to a first year"
        → "coding courses first year"
    """
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    meaningful = [t for t in tokens if t not in _STOP_WORDS]
    # Fall back to the original text if stripping removes everything
    # (e.g. a one-word stop word query — rare but safe to handle).
    return " ".join(meaningful) if meaningful else text


# ── Query expansion ──────────────────────────────────────────────────────────
# Maps a single student-vocabulary token to a replacement string that includes
# the original token plus its canonical equivalent. Applied AFTER stop-word
# stripping so only content tokens are expanded.
#
# WHY keep this dict small and explicit rather than reusing INTEREST_SYNONYMS:
#     INTEREST_SYNONYMS drives the /recommend scoring path and contains many
#     synonyms per key. Here we only want to fix known embedding blind spots
#     (e.g. "coding" ≈ "programming" in student speech but the model doesn't
#     always bridge them). Adding entries speculatively risks over-broadening
#     the query and hurting precision. Only add when a real query is observed
#     missing courses it should find.
_QUERY_EXPANSIONS: dict[str, str] = {
    "coding": "coding programming",
    "ml":     "ml machine learning",
    "ai":     "ai artificial intelligence",
    "cs":     "cs computer science",
    "stats":  "stats statistics",
}


def _expand_query(text: str) -> str:
    """
    Replace known shorthand tokens with an expanded form that includes both
    the original token and its canonical synonym.

    WHY token-by-token replacement rather than substring:
        Substring replacement on "coding" inside "decoding" would corrupt the
        word. Splitting on whitespace first ensures only whole-word tokens match,
        which is correct because stop-word stripping already normalises to a
        space-separated token stream.

    WHY the expansion keeps the original token ("coding programming" not just
    "programming"):
        The expanded string contributes to the embedding vector. Dropping the
        original token would lose any unique signal it carries; including both
        lets the model see both vocabularies simultaneously.
    """
    tokens = text.split()
    return " ".join(_QUERY_EXPANSIONS.get(t, t) for t in tokens)


# ── Year-level detection and filtering ───────────────────────────────────────
# UofT course codes encode the year level in the first digit of the 3-digit
# number: CSC108H1 → year 1, MAT207H1 → year 2, CSC309H1 → year 3, etc.
# These helpers extract that signal from both the user's query and course codes
# so we can restrict semantic search to the relevant year pool before embedding.

# Each tuple is (regex_pattern, year_integer). Patterns use word boundaries and
# optional hyphen/space between the ordinal and "year" to catch "first-year",
# "first year", and "1st year" variants. re.IGNORECASE is applied at call time.
_YEAR_PATTERNS: list[tuple[str, int]] = [
    (r"\bfirst[\s\-]?year\b",  1),
    (r"\b1st[\s\-]?year\b",    1),
    (r"\byear[\s\-]?1\b",      1),
    # "introductory" is treated as year-1 because all intro-level courses at UofT
    # are coded 1xx. This is a soft heuristic — if it causes false positives for
    # upper-year intro topics, add a subject-qualifier guard here.
    (r"\bintroductory\b",      1),
    (r"\bsecond[\s\-]?year\b", 2),
    (r"\b2nd[\s\-]?year\b",    2),
    (r"\byear[\s\-]?2\b",      2),
    (r"\bthird[\s\-]?year\b",  3),
    (r"\b3rd[\s\-]?year\b",    3),
    (r"\byear[\s\-]?3\b",      3),
    (r"\bfourth[\s\-]?year\b", 4),
    (r"\b4th[\s\-]?year\b",    4),
    (r"\byear[\s\-]?4\b",      4),
]


def _detect_year_level(text: str) -> int | None:
    """
    Scan text for year-level phrases and return the corresponding year (1–4),
    or None if no year phrase is found.

    WHY run on the raw (un-stripped) message:
        _strip_filler does not remove "first", "second", or "introductory" (none
        are in _STOP_WORDS), so detection would work either way. Running on the
        raw message is still the safer policy: if _STOP_WORDS ever grows to
        include those words, detection would silently break if we ran it post-strip.

    WHY first-match wins:
        Users almost never state contradictory years ("first year third year") in
        a single query. First-match is deterministic, predictable, and easy to
        debug — majority-vote would add complexity with no real benefit here.
    """
    for pattern, year in _YEAR_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return year
    return None


def _get_course_year(code: str) -> int | None:
    """
    Extract the year level (1–4) from a UofT course code.

    UofT convention: the first digit of the 3-digit number encodes the year.
        CSC108H1  → year 1  (the '1' in '108')
        MAT207H1  → year 2  (the '2' in '207')
        CSC309H1  → year 3
        CSC404H1  → year 4
        CSC099Y1  → year 0  (special/pre-credit; returns None)

    WHY return None for year-0 codes rather than 0:
        None cleanly signals "unknown or ineligible". Callers can use
        `_get_course_year(code) == year` as a filter predicate without needing
        to special-case 0 separately. Year-0 specials like CSC099Y1 are
        precisely the false-positives we want to exclude from year filters.
    """
    m = re.search(r"[A-Za-z]{2,4}(\d)\d{2}", code)
    if m:
        yr = int(m.group(1))
        return yr if yr in (1, 2, 3, 4) else None
    return None


def _filter_by_year(course_list: list["Course"], year: int) -> list["Course"]:
    """
    Return only the courses whose code encodes the requested year level.

    WHY return a new list instead of mutating:
        course_list is the global catalog passed in by the caller. Mutating it
        would corrupt all subsequent calls for the lifetime of the process.
    """
    return [c for c in course_list if _get_course_year(c.get_course_code()) == year]


def _strip_year_phrases(text: str) -> str:
    """
    Remove year-level phrases from an already-stop-word-stripped query.

    Called AFTER _detect_year_level has already captured the year as an integer,
    so the year signal is not lost — only its textual form is erased from the
    query that gets embedded.

    WHY this is separate from _strip_filler:
        _strip_filler is a token-level stop-word remover. "first year" is a
        two-word phrase that token stripping can't remove atomically — stripping
        "first" alone would leave "year" behind, and "year" alone in the query
        would still pull the embedding toward courses with "year" in their text.
        Regex-based phrase removal handles multi-word patterns cleanly.

    WHY strip after detection, not before:
        We need the matched year integer before we remove the phrase. If we
        stripped first, _detect_year_level would have nothing to match against.

    Example:
        "coding courses first year"   → "coding courses"
        "introductory programming"    → "programming"
        "second year machine learning"→ "machine learning"
    """
    result = text
    for pattern, _ in _YEAR_PATTERNS:
        result = re.sub(pattern, "", result, flags=re.IGNORECASE)
    # Collapse any double spaces left by removed phrases
    return re.sub(r"\s+", " ", result).strip()


# ── Breadth-category detection and filtering ─────────────────────────────────
# UofT's Faculty of Arts & Science defines 5 breadth categories that every
# course is tagged with in the scraped data as a raw string ending in "(N)"
# (e.g. "Thought, Belief and Behaviour (2)"). Unlike year level, a query can
# legitimately name MULTIPLE categories at once ("breadth 2 and 4"), so
# detection below returns a set, not a single int like _detect_year_level does.
BREADTH_CATEGORIES: dict[int, str] = {
    1: "Creative and Cultural Representations",
    2: "Thought, Belief and Behaviour",
    3: "Society and its Institutions",
    4: "Living Things and Their Environment",
    5: "The Physical and Mathematical Universes",
}

# Matches "breadth", "breadth category", "breadth categories", "breadth
# requirement(s)" — the digit(s) themselves are pulled out separately by
# _BREADTH_NUMBER_RE from a small window AFTER this keyword match, not from
# the whole message (see _detect_breadth_categories).
_BREADTH_KEYWORD_RE = re.compile(
    r"\bbreadth(?:[\s\-]?(?:category|categories|requirement|requirements))?\b",
    re.IGNORECASE,
)
_BREADTH_NUMBER_RE = re.compile(r"\b([1-5])\b")
_BREADTH_TRAILING_NUM_RE = re.compile(r"\((\d)\)\s*$")


def _detect_breadth_categories(text: str) -> set[int] | None:
    """
    Scan text for breadth-category phrases ("breadth 2", "breadth category 4",
    "breadth requirement 2 and 4") and return the set of category numbers
    named, or None if no breadth phrase is found.

    WHY a set instead of a single int (unlike _detect_year_level):
        A student can ask about two breadth requirements they still need to
        satisfy in one query ("easy breadth 2 and 4 courses"). Year level is
        near-always singular in practice; breadth is not, so the return type
        has to support 2+ values from the start rather than being retrofitted.

    WHY search from the keyword match onward, not the whole message:
        Extracting digits from the entire message would false-positive on
        unrelated numbers ("I've done 4 courses so far, need breadth 2").
        Anchoring the number search to text after the breadth keyword keeps
        detection scoped to what's actually being asked about breadth.
    """
    match = _BREADTH_KEYWORD_RE.search(text)
    if not match:
        return None
    tail = text[match.end():match.end() + 40]  # numbers stated right after the keyword, not anywhere in the message
    numbers = {int(n) for n in _BREADTH_NUMBER_RE.findall(tail)}
    return numbers or None


def _get_breadth_numbers(course: "Course") -> set[int]:
    """
    Parse the trailing "(N)" category number off each raw breadth string.

    WHY parse per-call instead of caching on Course at load time:
        Some scraped values are placeholders ("None", "TBA") with no trailing
        digit. The regex simply yields nothing for those, so no special-casing
        is needed here — a course with only placeholder breadth values
        correctly produces an empty set and is excluded by any breadth filter.
    """
    numbers: set[int] = set()
    for raw in course.get_breadth():
        m = _BREADTH_TRAILING_NUM_RE.search(raw)
        if m:
            numbers.add(int(m.group(1)))
    return numbers


def _filter_by_breadth(course_list: list["Course"], categories: set[int]) -> list["Course"]:
    """
    Return only courses tagged with AT LEAST ONE of the requested breadth
    categories.

    WHY "any of" (OR) rather than "all of" (AND):
        A single course in this dataset is tagged with at most one breadth
        requirement, so requiring a course match ALL requested categories
        would return zero results whenever 2+ categories are named — exactly
        the "breadth 2 and 4" query this feature exists to answer. OR composes
        correctly: "breadth 2 and 4 courses" means "show me options for
        breadth 2 OR breadth 4", not "a single course tagged both".
    """
    return [c for c in course_list if _get_breadth_numbers(c) & categories]


def _strip_breadth_phrases(text: str) -> str:
    """
    Remove the breadth keyword phrase from an already stop-word-stripped
    query, mirroring _strip_year_phrases's reasoning: leaving "breadth" in the
    query would pull the embedding toward courses whose *description* happens
    to mention "breadth" rather than courses *tagged* with the requested
    category — the mask (see search_by_message) already guarantees the
    latter, so the word is redundant/noisy text for the embedding.

    WHY this only strips the keyword, not the trailing digit(s) (unlike year,
    which strips the whole phrase including the number):
        Bare digits 1-5 are far more collision-prone to regex-strip safely
        than a year phrase like "first year" — stray connector words ("and",
        ",") around them make a clean removal fragile. A lone leftover "2 4"
        token is low-signal noise for a 384-dim sentence embedding and not
        worth a brittle regex; this is a deliberate simplification, not an
        oversight.
    """
    return re.sub(r"\s+", " ", _BREADTH_KEYWORD_RE.sub("", text)).strip()


# ── Difficulty ("easy"/"hard") signal detection ──────────────────────────────
# course.difficulty is an AI-scored 1-10 int already loaded (see the Course
# construction loop above) but never consulted anywhere in the chat retrieval
# path — only in the separate /recommend scorer (score_course()). This wires
# the same field into search_by_message() so "easy breadth 2 courses" queries
# can actually bias toward low-difficulty results instead of silently ignoring
# the word "easy".
_EASY_RE = re.compile(
    r"\b(easy|easier|easiest|simple|beginner[\s\-]?friendly|low[\s\-]?difficulty|not[\s\-]?too[\s\-]?hard)\b",
    re.IGNORECASE,
)
_HARD_RE = re.compile(
    r"\b(hard|harder|hardest|difficult|challenging|advanced|rigorous|high[\s\-]?difficulty)\b",
    re.IGNORECASE,
)


def _detect_difficulty_bias(text: str) -> str | None:
    """
    Detect whether the student wants easier or harder courses.

    Returns "easy", "hard", or None (no signal). Checked in that order — if a
    message contains both keyword families (rare, e.g. "not too hard but
    still a bit challenging"), "easy" wins, mirroring _detect_year_level's
    deterministic first-match-wins policy rather than modelling contradictory
    intent.
    """
    if _EASY_RE.search(text):
        return "easy"
    if _HARD_RE.search(text):
        return "hard"
    return None


def _find_courses_by_code(message: str, course_list: list["Course"]) -> list[tuple["Course", float]]:
    """
    Direct course-code lookup before any interest scoring runs.

    WHY this exists: interest extraction strips digits (re.findall(r"[a-z]+"...))
    so "MAT148" becomes just "mat", which substring-matches hundreds of unrelated
    courses ("cli-mat-e", "mat-hematics"). This step catches course-code patterns
    first and pins matched courses at max score so they always appear in the top N.
    """
    found: list[tuple["Course", float]] = []
    seen_codes: set[str] = set()
    for m in _COURSE_CODE_RE.finditer(message):
        query = m.group(1).upper()
        for course in course_list:
            code = course.get_course_code().upper()
            # startswith so "MAT148" matches "MAT148H1", "MAT148H5", etc.
            if code.startswith(query) and code not in seen_codes:
                found.append((course, 10.0))
                seen_codes.add(code)
    return found

def _split_top_level(text: str, sep: str) -> list[str]:
    """
    Split `text` on `sep` characters that sit outside any parentheses.

    WHY not str.split(sep): a raw prerequisite string like
    "(STA237H1, STA238H1)/CSC108H1" has a comma INSIDE the parens meaning
    "both of these together", which is a different thing from a comma at the
    top level meaning "this clause, and separately, that clause". Plain
    str.split can't tell those apart. Tracking paren depth while scanning
    left-to-right lets us only split where `sep` is acting at the CURRENT
    nesting level -- a `sep` seen while depth > 0 belongs to whatever group
    is currently open, so it's left alone.
    """
    parts = []
    depth = 0
    start = 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == sep and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return parts


def parse_prerequisites(text: str) -> list[list[list[str]]]:
    """
    Parse a raw UofT prerequisite string into a nested AND/OR structure.

    UofT prerequisite text follows this grammar:
        prereqs := clause ("," clause)*      -- ALL clauses required (AND)
        clause  := option ("/" option)*      -- ANY ONE option satisfies (OR)
        option  := "(" code ("," code)* ")"  -- ALL codes in the pair required (AND)
                 | code                      -- a single course code

    Returns a list of clauses; each clause is a list of options (any one of
    which satisfies that clause); each option is a list of course codes that
    must ALL be completed together (length 1 for a plain code, length 2+ for
    a parenthesized AND-pair like "(STA237H1, STA238H1)").

    Example:
        "ECO220Y1/(STA237H1, STA238H1), CSC108H1/CSC148H1"
        -> [
             [["ECO220Y1"], ["STA237H1", "STA238H1"]],  # clause 1 (OR of 2 options)
             [["CSC108H1"], ["CSC148H1"]],               # clause 2 (OR of 2 options)
           ]
        meaning: (ECO220Y1 OR (STA237H1 AND STA238H1)) AND (CSC108H1 OR CSC148H1)
    """
    if not text or not text.strip():
        return []
    return [clause for clause in (_parse_clause(c) for c in _split_top_level(text, ",")) if clause]


def _parse_clause(text: str) -> list[list[str]]:
    """
    Parse one AND-clause into its OR-options: split on "/" and parse each
    piece with _parse_option, which recurses back into _parse_clause if that
    piece turns out to be a parenthesized group. This mutual recursion is
    what lets the grammar handle nesting in general, even though real UofT
    prerequisite text never goes more than one paren deep in practice.
    """
    options = [_parse_option(opt.strip()) for opt in _split_top_level(text, "/")]
    return [opt for opt in options if opt]


def _parse_option(text: str) -> list[str]:
    """
    Parse a single OR-option into the course code(s) it requires.

    Recursive case: "(...)" -- e.g. "(STA237H1, STA238H1)" -- is a
    parenthesized AND-group. Strip the brackets and recurse through
    _parse_clause on the inside (the same comma/slash grammar applies inside
    parens as at the top level), then flatten every code that comes back:
    everything inside an AND-group must hold at once, so how it was grouped
    internally no longer matters once we're returning to the caller.

    Base case: no parens left, so pull out whatever course code(s) are here
    with the shared _COURSE_CODE_RE.
    """
    if text.startswith("(") and text.endswith(")"):
        nested = _parse_clause(text[1:-1])
        return [code for option in nested for code in option]
    return _COURSE_CODE_RE.findall(text)

def search_by_message(message: str, course_list: list["Course"], top_n: int = 5) -> list[tuple["Course", float]]:
    """
    Find the most relevant courses for a free-text message.

    Pipeline:
      1. Exact course-code detection — pins matched courses at score 10.0.
         Always wins over semantic; handles "tell me about CSC108H1" queries.
      2a. Year-level detection — scans the raw message for phrases like "first
         year", "introductory", "2nd year". When found, the candidate pool is
         restricted to courses whose code digit matches that year.
      2b. Breadth-category detection — scans the raw message for phrases like
         "breadth 2", "breadth category 4", "breadth requirement 2 and 4".
         When found, the candidate pool is restricted to courses tagged with
         at least one of the named categories. Combines with the year filter
         by intersection (a query can name both), while multiple breadth
         numbers within one query combine by union (see _filter_by_breadth).
      3. Stop-word stripping — removes conversational filler so the embedding
         query reflects topic intent, not phrasing style.
      4a. Year-phrase stripping — removes the now-consumed year signal from the
         query string. Without this step, "first year" would remain and pull the
         embedding toward courses that *mention* "first year" in their text
         (e.g. CSC099Y1 "First-Year Learning Community") rather than courses
         *coded at* year 1 (CSC1xx).
      4b. Breadth-phrase stripping — same reasoning as 4a, for the word
         "breadth" (see _strip_breadth_phrases).
      5. Query expansion — broadens sparse terms to include canonical synonyms
         (e.g. "coding" → "coding programming") so vocabulary mismatches between
         student language and course catalog language are bridged.
      6. Semantic search with year/breadth mask, optionally re-ranked by a
         detected difficulty ("easy"/"hard") bias — cosine similarity over the
         embedding index, restricted to the filtered candidate pool via a
         numpy boolean mask, then re-sorted by a similarity/difficulty blend
         when the student asked for easier or harder courses.

    WHY year/breadth filtering happens before embedding (not after):
        The embedding index has N≈3206 rows. Without pre-filtering, the top-N
        selection could be dominated by courses from the wrong year/category
        that happen to have high semantic similarity. With the mask, argsort
        only considers matching rows so the final top_n results are
        guaranteed to come from the correct pool — no silent under-delivery.

    WHY difficulty is a re-rank, not a third mask:
        Stacking a hard difficulty-range filter on top of an already-narrow
        breadth mask risks zero results (e.g. no breadth-2 course happens to
        be "very easy"). Re-ranking a slightly larger candidate pool instead
        guarantees the response always contains the best available options
        for the requested category, just ordered toward the requested
        difficulty rather than filtered by it.

    WHY _extract_interests_from_text() and INTEREST_SYNONYMS are not used here:
        Those were designed for the /recommend flow where the student explicitly
        declares interests. For freeform chat this function uses embedding
        similarity instead, which handles arbitrary natural language without a
        manually curated synonym map.
    """
    from embeddings import semantic_search  # local import avoids circular dependency at module load

    # Step 1: exact course-code lookup — highest priority, no semantic needed
    code_hits = _find_courses_by_code(message, course_list)
    code_hit_codes = {c.get_course_code() for c, _ in code_hits}

    remaining = top_n - len(code_hits)
    semantic_hits: list[tuple["Course", float]] = []

    if remaining > 0:
        # Step 2a/2b: year + breadth detection — both must run on the raw
        # message before any stripping, so their trigger phrases are still
        # present to match against.
        year = _detect_year_level(message)
        breadth_categories = _detect_breadth_categories(message)

        # Build the allowed_codes mask by intersecting every active filter
        # type. None means "no mask" — score all rows.
        #
        # WHY intersection (AND) across filter types but union (OR) within
        # breadth categories: a query naming both a year AND a breadth
        # category ("second year breadth 2 courses") should match courses
        # satisfying BOTH constraints, but a query naming two breadth
        # categories ("breadth 2 and 4") should match courses satisfying
        # EITHER one (see _filter_by_breadth docstring) — different asks, so
        # it's OR inside one filter type and AND across filter types.
        allowed_codes: set[str] | None = None
        if year is not None:
            allowed_codes = {c.get_course_code() for c in _filter_by_year(course_list, year)}
        if breadth_categories is not None:
            breadth_codes = {c.get_course_code() for c in _filter_by_breadth(course_list, breadth_categories)}
            allowed_codes = breadth_codes if allowed_codes is None else allowed_codes & breadth_codes

        # Step 3: strip conversational filler
        semantic_query = _strip_filler(message)

        # Step 4a: strip the year phrase that was already captured as a filter.
        # Leaving it in would attract courses that *mention* "first year" rather
        # than courses *at* year 1, which the mask already guarantees.
        if year is not None:
            semantic_query = _strip_year_phrases(semantic_query)

        # Step 4b: strip the breadth keyword that was already captured as a
        # filter, for the same reason as 4a.
        if breadth_categories is not None:
            semantic_query = _strip_breadth_phrases(semantic_query)

        # Step 5: expand shorthand terms to include canonical synonyms
        semantic_query = _expand_query(semantic_query)

        # Step 6: semantic search with optional year/breadth mask, then
        # optional difficulty re-ranking.
        difficulty_bias = _detect_difficulty_bias(message)

        # WHY request a larger pool (3x) when a difficulty bias is active:
        #     Difficulty re-ranking needs candidates to actually have room to
        #     reorder — if we only ever fetched `remaining` results there'd be
        #     nothing left to re-sort and semantic order would just pass
        #     through unchanged. Overfetching then truncating AFTER the
        #     blended sort keeps the final list still topically relevant (not
        #     just "the easiest courses in the catalog regardless of topic")
        #     while giving difficulty a real say in the final order.
        fetch_n = (remaining * 3 if difficulty_bias else remaining) + len(code_hits)

        # O(1) code → Course lookup to resolve codes returned by semantic_search()
        code_to_course = {c.get_course_code(): c for c in course_list}
        candidates: list[tuple["Course", float]] = []
        for code, score in semantic_search(
            semantic_query,
            top_n=fetch_n,
            allowed_codes=allowed_codes,
        ):
            if code not in code_hit_codes and code in code_to_course:
                candidates.append((code_to_course[code], score))

        if difficulty_bias is not None:
            # Blend: semantic similarity stays dominant (weight 0.7) so a
            # highly relevant but medium-difficulty course still beats a
            # barely-relevant trivial one. Difficulty contributes 0.3,
            # normalized to a 0-1 range so it's on comparable footing with
            # cosine similarity.
            #
            # WHY a blend and not a pure difficulty sort:
            #     A pure difficulty sort would ignore topic relevance
            #     entirely — "easy breadth 2 courses" would return the single
            #     easiest course in the WHOLE catalog if it happened to be
            #     tagged breadth 2, even if three other breadth-2 courses
            #     were a much better topical fit and only slightly harder.
            #     The mask already restricts the pool to breadth 2; this
            #     blend just orders WITHIN that pool.
            def _blended(entry: tuple["Course", float]) -> float:
                course, sim = entry
                norm_difficulty = (course.difficulty - DIFFICULTY_MIN) / (DIFFICULTY_MAX - DIFFICULTY_MIN)  # 0=easiest, 1=hardest
                difficulty_component = (1 - norm_difficulty) if difficulty_bias == "easy" else norm_difficulty
                return 0.7 * sim + 0.3 * difficulty_component

            candidates.sort(key=_blended, reverse=True)

        # score stays the raw cosine similarity here (not the blended value)
        # since callers (e.g. _build_course_context) don't currently surface
        # score at all — the blend is only used to decide ORDER, not to
        # replace the similarity value in the returned tuple.
        semantic_hits = candidates[:remaining]

    return code_hits + semantic_hits