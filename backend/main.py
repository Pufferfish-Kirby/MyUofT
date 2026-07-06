# Remember to call venv/Scripts/activate to get here
# Also run uvicorn main:app --reload --port 8000
import logging
import os
from dotenv import load_dotenv
import anthropic
from fastapi import FastAPI, Header, HTTPException, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from scoring import recommend_courses, explain, explain_structured, search_by_message, courses as course_catalog, BREADTH_CATEGORIES
from chat_db import init_db, create_session, list_sessions, get_messages, save_message, update_session_title, delete_messages_from, session_belongs_to
from reviews_db import init_reviews_db, save_review, get_reviews
from program_data import search_programs_by_message, load_programs, Program

# Load ANTHROPIC_API_KEY from .env so we never hardcode secrets in source.
load_dotenv()
claude_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Module-level logger — WHY not print(): logging lets us control verbosity via
# the LOG_LEVEL env var (already in .env.example) and routes messages through
# stderr with timestamps/levels, without pulling in a whole logging framework.
# This is stdlib-only, so it doesn't count as a new dependency.
logger = logging.getLogger(__name__)

# Limiter uses the client's IP address as the rate-limit key so each unique
# visitor gets their own independent counter.  get_remote_address reads from
# the X-Forwarded-For header (if present) then falls back to request.client.host,
# which is the right behaviour both locally and behind a reverse proxy.
limiter = Limiter(key_func=get_remote_address)

# FastAPI() — note the parentheses. Without them `app` would be the class itself,
# not an instance, so every method call below would crash at startup.
app = FastAPI()

# Attach the limiter to app.state so slowapi's decorator can find it at request time.
# WHY app.state and not a global: Starlette's state bag is the idiomatic place to
# store per-application singletons that middleware and decorators need to reach.
app.state.limiter = limiter

# Register slowapi's built-in 429 handler.  Without this, exceeding the limit would
# raise an unhandled RateLimitExceeded exception and return a 500 instead of a 429.
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# WHY call init_db() here instead of in a startup event:
#     FastAPI startup events run after the app object is constructed but
#     before the first request — same timing as calling it right here, but
#     this placement is simpler and immediately obvious.  The function uses
#     CREATE TABLE IF NOT EXISTS so it is safe to call on every restart
#     without wiping data or raising errors.
init_db()
init_reviews_db()  # idempotent — creates course_reviews table if missing

# Load program catalog once at startup — 169 programs, negligible memory.
# try/except so the server starts even if programs.json is somehow missing;
# _build_program_context() degrades gracefully when program_catalog is empty.
try:
    program_catalog = load_programs()
except FileNotFoundError:
    program_catalog = []

# Eagerly warm the embedding pipeline (sentence-transformers model + both
# .npy indices) at startup instead of leaving it lazy.
# WHY: get_model()/the index loaders in embeddings.py are lazy singletons —
# normally a fine pattern, but on Railway the process restarts on every
# deploy, so whoever sends the FIRST chat message after a deploy pays the
# full load cost. Measured locally at 10-40+ seconds (dominated by importing
# torch/sentence-transformers, not the 90MB of weights themselves) stacked on
# top of the real Claude API latency — indistinguishable from the AI itself
# being broken. Running a throwaway search here means that cost lands during
# container startup, before Railway's health check passes and routes real
# traffic, instead of on some unlucky user's first message.
try:
    from embeddings import semantic_search, program_semantic_search
    semantic_search("warmup", top_n=1)
    program_semantic_search("warmup", top_n=1)
except FileNotFoundError:
    pass  # embeddings not built yet — /chat already degrades gracefully in this case

# CORSMiddleware lets the browser make requests from the frontend's origin to
# this API. Without it, browsers block all cross-origin requests before they
# even reach our route handlers.
# WHY read from CORS_ORIGINS instead of hardcoding: .env.example has always
# documented this variable, but nothing actually read it — the origin was
# hardcoded to the Vite dev server, which would silently break every request
# once the frontend moves to a real domain (e.g. Vercel) and the backend
# moves to a real domain (e.g. Railway). Comma-separated so both a Vercel
# production domain and preview-deploy domains can be listed at once.
# WHY a specific origin (or list) instead of "*":
#   The CORS spec forbids combining allow_origins=["*"] with
#   allow_credentials=True — browsers reject the response entirely.
#   Listing exact origins fixes that, and is also safer because it won't
#   accidentally expose the API to every website on the internet.
cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Single source of truth for the breadth category names shown to Claude —
# built from the same BREADTH_CATEGORIES dict that scoring.py filters
# against, so the reference table can never drift out of sync with the
# actual filtering logic.
_BREADTH_REFERENCE = "\n".join(f"  {n}. {name}" for n, name in sorted(BREADTH_CATEGORIES.items()))

# The advisor system prompt is injected on every request rather than stored
# per-session because we're stateless for now. It gives Claude the context it
# needs to answer as a UofT academic advisor instead of a generic assistant.
ADVISOR_SYSTEM_PROMPT = """You are a friendly, knowledgeable academic advisor for the University of Toronto. \
Help students with course selection, program requirements, career direction, and academic planning. \
Be concise and encouraging, and actually answer the question the student asked.

You draw on two different kinds of knowledge, and the rules differ for each:

1. GROUNDED FACTS (strict) — Any specific UofT claim must come only from the
   context provided below the conversation: course codes, what a specific course
   covers, prerequisites, corequisites, exclusions, breadth categories, terms a
   course runs in, and program/degree requirements. Never invent or guess a
   course code or a prerequisite, and never state one from memory. If the context
   doesn't contain a course that fits, describe the *kind* of course the student
   should look for (e.g. "an intro linear algebra course") instead of inventing a
   code, and point them to the Academic Calendar to confirm the exact offering.
   When two courses in the context are genuinely similar, never describe one's
   prerequisites, corequisites, exclusions, or requirements as "similar to" or
   "the same as" the other — each course's own data must be quoted or
   paraphrased from its own entry in the context, even if that means repeating
   near-identical text.

2. GENERAL ADVISING KNOWLEDGE (free) — Use your own knowledge freely for
   everything that isn't a specific UofT fact: how a field or career works, what
   skills it needs, and the sensible order to learn them. This is what makes you a
   good advisor, so lean into it.

For career or topic questions like "what should I take to get into machine
learning?", combine the two: use your general knowledge to lay out the learning
path (foundations first, then the concepts that build on them), and use the
provided course context to fill that path with real UofT course codes. Recommend
concrete courses from the context whenever they fit, and mention prerequisites so
the student knows what a course depends on.

The Academic Calendar (https://artsci.calendar.utoronto.ca/) is a supplement for
verifying specifics like enrolment rules or the latest offering — suggest it to
confirm details, never as a reason to avoid answering.

BREADTH CATEGORIES — the 5 official Arts & Science breadth requirements are:
{breadth_reference}
A course's own breadth string in the context below may be worded slightly
differently (capitalization, minor phrasing) — use this table to name the
category correctly regardless.

FORMATTING — when listing multiple courses, always put real content on the
same line as the bullet marker; never emit a bullet with nothing after it.
Each bullet should name the course code and give at least one concrete reason
it fits. If no course in the context actually matches what was asked, say so
in a sentence instead of producing an empty or placeholder bullet.""".format(breadth_reference=_BREADTH_REFERENCE)


class ChatMessage(BaseModel):
    # "user" or "assistant" — mirrors the Anthropic messages API roles exactly
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    # history lets the frontend send the previous turns so Claude has context
    # for multi-turn conversations without us needing a server-side session store.
    history: list[ChatMessage] = []
    # session_id is optional — when provided, the server persists the exchange
    # to SQLite so conversations survive page reloads and browser closes.
    session_id: int | None = None
    # Set when the user edited a previously-sent message rather than typing a
    # new one. When present (and session_id is too), we delete this message
    # and everything after it before saving the edited version + new reply,
    # so the conversation doesn't fork into two branches in the DB.
    edit_message_id: int | None = None


class ChatResponse(BaseModel):
    response: str
    # IDs of the newly-saved rows, so the frontend can attach them to its
    # local message objects — needed so a message can be edited again later
    # (delete_messages_from requires a real DB id, not an array index).
    user_message_id: int | None = None
    assistant_message_id: int | None = None


# How many semantic-search courses to inject as context per message.
# WHY 12 (raised from 5): career/topic questions like "what should I take to
# get into ML?" need a *sequence* of courses (intro programming → data
# structures → linear algebra → stats → ML), which 5 hits can't cover. Twelve
# courses at ~350 chars of description+fields each is still a small fraction of
# the context window, so the token cost is negligible next to the qualizzty gain.
_COURSE_CONTEXT_TOP_N = 10

# Cap on how much of each course description we inject. Full descriptions run
# 500–1500+ chars; at 12 courses that would bloat the prompt for little gain.
# ~280 chars is enough for Claude to understand what a course is about.
_DESCRIPTION_CHAR_BUDGET = 280


def _truncate_description(text: str, limit: int = _DESCRIPTION_CHAR_BUDGET) -> str:
    """
    Shorten a course description to roughly `limit` chars, cutting at a word
    boundary and appending an ellipsis.

    WHY cut at a word boundary rather than a hard slice:
        A hard text[:280] can end mid-word ("...introduc") which reads as broken
        data. Backing up to the last space keeps the fragment clean. We only back
        up if a space exists reasonably far in, so a single very long token
        doesn't collapse the whole string to empty.
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last_space = cut.rfind(" ")
    # Only trim to the last space if it's not too close to the start, otherwise
    # keep the hard cut (avoids returning almost nothing for space-poor text).
    if last_space > limit * 0.5:
        cut = cut[:last_space]
    return cut.rstrip() + "…"


def _build_course_context(message: str, extra_codes: set[str] | None = None) -> str:
    """
    Search the course catalog for courses relevant to the user's message and
    format them as a context block to append to the system prompt.

    WHY inject here rather than in the system prompt at startup:
        Sending the full 3000+ course catalog to Claude on every request is
        expensive and wastes most of the context window. By filtering to only
        the top few relevant courses per message, we keep the prompt tight while
        still grounding Claude's answers in real UofT course data.

    WHY each course now includes description, breadth and terms (not just
    code+name+prereqs):
        The advisor is only allowed to make specific UofT claims from this
        context (see ADVISOR_SYSTEM_PROMPT). A bare code+name doesn't tell Claude
        what a course actually covers, so it couldn't confidently place a course
        in a learning path or explain why it fits. Feeding a (truncated)
        description, the breadth category, and the terms it runs in lets Claude
        reason about fit and sequencing without inventing anything.

    WHY difficulty/workload are now included:
        Before this, a query like "what are easy breadth courses" gave Claude
        zero grounded numeric data to support an "easy" claim with — it had to
        guess, producing vague or empty-feeling answers. course.difficulty and
        course.workload were already AI-scored and loaded for the separate
        /recommend endpoint's scorer but never surfaced here.

    WHY extra_codes exists (bug fix):
        search_by_message() only does generic semantic search over the raw
        message text — it has no idea a matched program (see
        _build_program_context) just referenced specific course codes like
        "CSC236H1 OR CSC240H1". Semantic hits can easily pick one half of an
        OR-pair (CSC240H1) and miss the other (CSC236H1), so Claude ends up
        saying "CSC236H1 (not detailed in my info)" even though the course
        exists in the catalog with full prerequisite text. extra_codes lets
        the caller pass in codes that MUST be exact-looked-up and included,
        regardless of what semantic search alone would have surfaced.

    Returns an empty string if no relevant courses are found so the system
    prompt stays clean when the message isn't course-related.
    """
    relevant = search_by_message(message, course_catalog, top_n=_COURSE_CONTEXT_TOP_N)
    seen_codes = {course.get_course_code() for course, _ in relevant}

    # Exact lookup for any extra codes not already covered by semantic search.
    # O(1) code -> Course map, same pattern already used in scoring.py.
    if extra_codes:
        code_to_course = {c.get_course_code(): c for c in course_catalog}
        for code in extra_codes:
            if code not in seen_codes and code in code_to_course:
                relevant.append((code_to_course[code], 0.0))
                seen_codes.add(code)

    if not relevant:
        return ""

    lines = [
        "Relevant UofT courses for this query. Use these to ground any specific "
        "course recommendation — do not cite course codes that are not listed here:",
    ]
    for course, score in relevant:
        # Prerequisite text is injected verbatim. It often encodes OR-choices
        # ("CSC236H1/CSC240H1") and grouped requirements — collapsing or
        # "simplifying" that would misrepresent what the student actually needs,
        # so we never reformat it.
        prereqs = course.get_prerequisites() or "none"
        breadth = "; ".join(course.get_breadth()) or "none listed"
        terms = ", ".join(course.get_terms_offered()) or "not listed"
        description = _truncate_description(course.get_description()) or "(no description available)"
        # One labelled block per course. Explicit field labels (rather than a
        # dense one-liner) make it unambiguous to Claude which text is the
        # prereq vs. the breadth category vs. the description.
        lines.append(
            f"\n- {course.get_course_code()} — {course.get_name()} "
            f"({course.get_credits()} credit)\n"
            f"  Description: {description}\n"
            f"  Prerequisites: {prereqs}\n"
            f"  Breadth: {breadth}\n"
            f"  Terms offered: {terms}\n"
            f"  Difficulty: {course.difficulty}/10, Workload: {course.workload}/10 "
            f"(AI-estimated; 1 = easiest/lightest, 10 = hardest/heaviest)"
        )
    return "\n".join(lines)


def _build_program_context(message: str) -> tuple[str, list[Program]]:
    """
    Search the program catalog for programs relevant to the user's message and
    format them as a context block to append to the system prompt.

    WHY top_n=2 instead of 5 (as for courses):
        Each program entry includes formatted_requirements — year sections, groups,
        and administrative notes — which is several times larger than a single
        course line. Two programs already provides substantial context without
        crowding out the course context block.

    WHY this now also returns the matched Program objects (not just the
    string): the caller needs them to look up year-scoped course codes (see
    Program.get_course_codes_for_year in program_data.py) so it can widen the
    course context with the exact courses these programs reference for the
    year the student asked about. Checked with grep that _build_program_context
    has no other callers, so widening the return type here is safe.

    Returns ("", []) when no programs are relevant, the catalog is empty,
    or the program embedding index hasn't been built yet (FileNotFoundError),
    so the server degrades gracefully in all cases.
    """
    if not program_catalog:
        return "", []
    try:
        relevant = search_programs_by_message(message, program_catalog, top_n=2)
    except FileNotFoundError:
        # program_embeddings.npy not built yet — degrade silently
        return "", []
    if not relevant:
        return "", []

    lines = ["Relevant UofT programs for this query (use these to inform your answer):"]
    matched_programs = []
    for prog, score in relevant:
        is_limited = "limited enrolment" in prog.enrolment_general.lower()
        enrol_label = "limited enrolment" if is_limited else "open enrolment"
        lines.append(
            f"- {prog.name} [{prog.type}] ({prog.program_code}): "
            f"{prog.completion_summary}, {enrol_label}"
        )
        lines.append(prog.formatted_requirements)
        matched_programs.append(prog)
    return "\n".join(lines), matched_programs


@app.post("/chat", response_model=ChatResponse)
@limiter.limit("20/minute")
# WHY request: Request is the first parameter:
#     slowapi inspects the route handler's signature to find the Request object so
#     it can read the client IP and track the rate-limit counter.  It MUST be the
#     first parameter and typed as fastapi.Request — slowapi won't find it otherwise.
async def chat(request: Request, data: ChatRequest, x_device_id: str = Header(...)) -> ChatResponse:
    # WHY check ownership before anything else touches session_id: session_id
    # is a guessable/incrementable integer, so without this check any visitor
    # could read another visitor's chat history just by sending its id here
    # (this endpoint both reads via get_messages() below and writes via
    # save_message/delete_messages_from). 404 rather than 403 so a non-owner
    # can't even confirm the session exists.
    if data.session_id is not None and not session_belongs_to(data.session_id, x_device_id):
        raise HTTPException(status_code=404, detail="Chat session not found")

    # If this is an edit of a past message, wipe it and everything saved after
    # it FIRST, before any of the logic below. WHY first: the title-recompute
    # check further down reads get_messages() to see if the session is empty —
    # if we deleted after that check, an edit to the very first message
    # wouldn't correctly reset the title.
    if data.session_id is not None and data.edit_message_id is not None:
        delete_messages_from(data.session_id, data.edit_message_id)

    # Rebuild the full message list: prior turns (from the frontend) + the new user message.
    # Anthropic expects a flat list of {"role": ..., "content": ...} dicts.
    messages = [{'role': msg.role, 'content': msg.content} for msg in data.history]
    messages.append({"role": "user", "content": data.message})

    # Inject relevant courses and programs into the system prompt so Claude can
    # reference real UofT data rather than hallucinating codes or requirements.
    program_context, matched_programs = _build_program_context(data.message)

    # Bridge the program context and course context (bug fix): if the message
    # names a specific year ("second year"), pull the exact course codes that
    # year's section of each matched program references and force-include them
    # in the course context, instead of relying purely on generic semantic
    # search which can pick one half of an "X OR Y" pair and drop the other.
    #
    # WHY local-import _detect_year_level here rather than at module level:
    #     mirrors the existing deferred-import pattern in program_data.py
    #     (search_programs_by_message importing program_semantic_search from
    #     embeddings locally) — it's a private helper (leading underscore) that
    #     belongs to scoring.py's module, so we borrow it rather than
    #     duplicating the year-phrase regex here.
    #
    # WHY only expand when a year IS detected:
    #     Program.get_course_codes_for_year returns [] for unmatched years, so
    #     this would be a no-op anyway — but being explicit keeps the "no year
    #     mentioned -> behave exactly as before" guarantee obvious and testable,
    #     rather than depending on an empty-list side effect.
    from scoring import _detect_year_level

    extra_codes: set[str] = set()
    year = _detect_year_level(data.message)
    if year is not None:
        for prog in matched_programs:
            extra_codes.update(prog.get_course_codes_for_year(year))

    course_context = _build_course_context(data.message, extra_codes=extra_codes)
    system_prompt   = ADVISOR_SYSTEM_PROMPT
    if course_context:
        system_prompt += f"\n\n{course_context}"
    if program_context:
        system_prompt += f"\n\n{program_context}"

    try:
        result = claude_client.messages.create(
            model="claude-haiku-4-5",  # haiku is fast/cheap; swap to sonnet for richer answers
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        )
    except anthropic.APIError as e:
        # WHY log the real exception server-side but return a generic message
        # to the client: interpolating `e` directly into the HTTP response body
        # (the old behaviour) risks leaking internal details from the Anthropic
        # SDK — request IDs, upstream error bodies, sometimes header/auth info —
        # to whoever is calling this endpoint. Logging it here keeps that detail
        # available for debugging without exposing it over the wire.
        logger.error("Claude API error while handling /chat request: %s", e)
        raise HTTPException(
            status_code=502,
            detail="The AI advisor is temporarily unavailable. Please try again shortly.",
        )

    assistant_text = result.content[0].text

    # Persist the exchange to SQLite when the caller supplies a session_id.
    # WHY check existing messages before updating the title:
    #     We only want to auto-title on the very first message so subsequent
    #     messages don't silently overwrite a title the user might expect to
    #     stay stable.  Checking len == 0 is cheaper than a separate COUNT query.
    user_message_id: int | None = None
    assistant_message_id: int | None = None
    if data.session_id is not None:
        existing = get_messages(data.session_id)
        if len(existing) == 0:
            # Truncate to 60 chars so the sidebar stays readable without wrapping.
            title = data.message[:60] + ("..." if len(data.message) > 60 else "")
            update_session_title(data.session_id, title)
        user_message_id = save_message(data.session_id, "user", data.message)
        assistant_message_id = save_message(data.session_id, "assistant", assistant_text)

    return ChatResponse(
        response=assistant_text,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
    )


@app.post("/chats")
@limiter.limit("20/minute")
# WHY 20/minute, same as /chat: creating a session is cheap (one INSERT), but
# unlimited creation would let a single client bloat chat_sessions with junk
# rows indefinitely, so it gets the same conservative budget as /chat.
def new_chat_session(request: Request, x_device_id: str = Header(...)) -> dict:
    """Create a new chat session and return its id, title, and created_at."""
    return create_session(owner_id=x_device_id)


@app.get("/chats")
@limiter.limit("60/minute")
# WHY more generous than the write endpoints: this is a read-only query
# (SELECT + one LEFT JOIN) with no side effects, and the frontend calls it
# after every message send to refresh the sidebar — a tight limit here would
# make normal chatting trip the limiter.
def get_chat_sessions(request: Request, x_device_id: str = Header(...)) -> list:
    """Return this device's chat sessions newest-first, each with a message_count."""
    return list_sessions(owner_id=x_device_id)


@app.get("/chats/{session_id}/messages")
@limiter.limit("60/minute")
def get_chat_messages(request: Request, session_id: int, x_device_id: str = Header(...)) -> list:
    """Return all messages for a session in chronological order."""
    if not session_belongs_to(session_id, x_device_id):
        raise HTTPException(status_code=404, detail="Chat session not found")
    return get_messages(session_id)


class ReviewRequest(BaseModel):
    course_code: str
    rating: int       # 1–5
    review_text: str = ""


class RequestData(BaseModel):
    interests: list[str]
    preferred_difficulty: int
    preferred_workload: int
    completed_courses: list[str] = []

@app.post("/recommend")
@limiter.limit("30/minute")
# WHY 30/minute, more than /chat but not unlimited: this never calls Claude
# (no per-request API cost), but it does score the full ~3200-course catalog
# on every call, so it's not free either — a middle-ground budget between the
# expensive /chat endpoint and the cheap read-only /chats endpoints.
def recommend(request: Request, data: RequestData) -> list:
    preferences = {
        "interests": data.interests,
        "preferred_difficulty": data.preferred_difficulty,
        "preferred_workload": data.preferred_workload,
        "completed_courses": data.completed_courses,
    }
    # Pass the full course catalog, not completed_courses — completed_courses
    # is used inside recommend_courses to filter out ineligible courses via is_eligible().
    courses = recommend_courses(course_catalog, preferences)
    result = []
    for course, score in courses:
        result.append({
            # Use get_name() because __init__ stores the name as self._name
            "name": course.get_course_code(),
            "score": score,
            # Plain string kept for backwards-compatibility / debugging in the future.
            "explanation": explain(course, preferences),
            # Structured list of { type, message, positive } objects — the frontend
            # uses this to render colour-coded reason chips instead of raw text.
            "reasons": explain_structured(course, preferences),
        })
    return result


@app.post("/reviews")
@limiter.limit("10/minute")
# WHY the tightest limit of any endpoint: this is the one place a client can
# write arbitrary free-text (review_text) into the database. A low limit
# blunts basic review-spam/flooding attempts without needing a captcha or
# auth system, which would be over-engineering for a Phase 1 MVP.
def post_review(request: Request, data: ReviewRequest) -> dict:
    if not 1 <= data.rating <= 5:
        raise HTTPException(status_code=400, detail="rating must be between 1 and 5")
    return save_review(data.course_code, data.rating, data.review_text)

@app.get("/reviews/{course_code}")
@limiter.limit("60/minute")
def get_course_reviews(request: Request, course_code: str) -> list:
    return get_reviews(course_code)