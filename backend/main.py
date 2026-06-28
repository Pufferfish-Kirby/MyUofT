# Remember to call venv/Scripts/activate to get here
# Also run uvicorn main:app --reload --port 8000
import os
from dotenv import load_dotenv
import anthropic
from fastapi import FastAPI, HTTPException, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from scoring import recommend_courses, explain, explain_structured, search_by_message, courses as course_catalog
from chat_db import init_db, create_session, list_sessions, get_messages, save_message, update_session_title
from reviews_db import init_reviews_db, save_review, get_reviews
from program_data import search_programs_by_message, load_programs

# Load ANTHROPIC_API_KEY from .env so we never hardcode secrets in source.
load_dotenv()
claude_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

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

# CORSMiddleware lets the browser make requests from the React dev server
# (localhost:5173) to this API (localhost:8000). Without it, browsers block
# all cross-origin requests before they even reach our route handlers.
# WHY a specific origin instead of "*":
#   The CORS spec forbids combining allow_origins=["*"] with
#   allow_credentials=True — browsers reject the response entirely.
#   Listing the exact Vite dev-server URL fixes that, and is also safer
#   because it won't accidentally expose the API to every website on the internet.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server default port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# The advisor system prompt is injected on every request rather than stored
# per-session because we're stateless for now. It gives Claude the context it
# needs to answer as a UofT academic advisor instead of a generic assistant.
ADVISOR_SYSTEM_PROMPT = """You are an academic advisor for the University of Toronto.
Help students with course selection, program requirements, and academic planning.
Be concise, accurate, and friendly. When recommending courses, mention prerequisites when relevant. Do not
hallucinate prerequisites, course codes, or anything you are not sure about. 
"Only answer using the courses provided in the context below. 
If the context does not contain enough information to answer, 
say so clearly and suggest the student check the UofT calendar directly. 
Do not recommend courses that are not in the provided context."""


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


class ChatResponse(BaseModel):
    response: str


def _build_course_context(message: str) -> str:
    """
    Search the course catalog for courses relevant to the user's message and
    format them as a short context block to append to the system prompt.

    WHY inject here rather than in the system prompt at startup:
        Sending the full 3000+ course catalog to Claude on every request is
        expensive and wastes most of the context window. By filtering to only
        the top 5 relevant courses per message, we keep the prompt tight while
        still grounding Claude's answers in real UofT course data.

    Returns an empty string if no relevant courses are found so the system
    prompt stays clean when the message isn't course-related.
    """
    relevant = search_by_message(message, course_catalog, top_n=5)
    if not relevant:
        return ""

    lines = ["Relevant UofT courses for this query (use these to inform your answer):"]
    for course, score in relevant:
        lines.append(
            f"- {course.get_course_code()} — {course.get_name()} "
            f"(prereqs: {course.get_prerequisites() or 'none'})"
        )
    return "\n".join(lines)


def _build_program_context(message: str) -> str:
    """
    Search the program catalog for programs relevant to the user's message and
    format them as a context block to append to the system prompt.

    WHY top_n=2 instead of 5 (as for courses):
        Each program entry includes formatted_requirements — year sections, groups,
        and administrative notes — which is several times larger than a single
        course line. Two programs already provides substantial context without
        crowding out the course context block.

    Returns empty string when no programs are relevant, the catalog is empty,
    or the program embedding index hasn't been built yet (FileNotFoundError),
    so the server degrades gracefully in all cases.
    """
    if not program_catalog:
        return ""
    try:
        relevant = search_programs_by_message(message, program_catalog, top_n=2)
    except FileNotFoundError:
        # program_embeddings.npy not built yet — degrade silently
        return ""
    if not relevant:
        return ""

    lines = ["Relevant UofT programs for this query (use these to inform your answer):"]
    for prog, score in relevant:
        is_limited = "limited enrolment" in prog.enrolment_general.lower()
        enrol_label = "limited enrolment" if is_limited else "open enrolment"
        lines.append(
            f"- {prog.name} [{prog.type}] ({prog.program_code}): "
            f"{prog.completion_summary}, {enrol_label}"
        )
        lines.append(prog.formatted_requirements)
    return "\n".join(lines)


@app.post("/chat", response_model=ChatResponse)
@limiter.limit("20/minute")
# WHY request: Request is the first parameter:
#     slowapi inspects the route handler's signature to find the Request object so
#     it can read the client IP and track the rate-limit counter.  It MUST be the
#     first parameter and typed as fastapi.Request — slowapi won't find it otherwise.
async def chat(request: Request, data: ChatRequest) -> ChatResponse:
    # Rebuild the full message list: prior turns (from the frontend) + the new user message.
    # Anthropic expects a flat list of {"role": ..., "content": ...} dicts.
    messages = [{'role': msg.role, 'content': msg.content} for msg in data.history]
    messages.append({"role": "user", "content": data.message})

    # Inject relevant courses and programs into the system prompt so Claude can
    # reference real UofT data rather than hallucinating codes or requirements.
    course_context  = _build_course_context(data.message)
    program_context = _build_program_context(data.message)
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
        raise HTTPException(status_code=502, detail=f"Claude API error: {e}")

    assistant_text = result.content[0].text

    # Persist the exchange to SQLite when the caller supplies a session_id.
    # WHY check existing messages before updating the title:
    #     We only want to auto-title on the very first message so subsequent
    #     messages don't silently overwrite a title the user might expect to
    #     stay stable.  Checking len == 0 is cheaper than a separate COUNT query.
    if data.session_id is not None:
        existing = get_messages(data.session_id)
        if len(existing) == 0:
            # Truncate to 60 chars so the sidebar stays readable without wrapping.
            title = data.message[:60] + ("..." if len(data.message) > 60 else "")
            update_session_title(data.session_id, title)
        save_message(data.session_id, "user", data.message)
        save_message(data.session_id, "assistant", assistant_text)

    return ChatResponse(response=assistant_text)


@app.post("/chats")
def new_chat_session() -> dict:
    """Create a new chat session and return its id, title, and created_at."""
    return create_session()


@app.get("/chats")
def get_chat_sessions() -> list:
    """Return all chat sessions newest-first, each with a message_count."""
    return list_sessions()


@app.get("/chats/{session_id}/messages")
def get_chat_messages(session_id: int) -> list:
    """Return all messages for a session in chronological order."""
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
def recommend(data: RequestData) -> list:
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
def post_review(data: ReviewRequest) -> dict:
    if not 1 <= data.rating <= 5:
        raise HTTPException(status_code=400, detail="rating must be between 1 and 5")
    return save_review(data.course_code, data.rating, data.review_text)

@app.get("/reviews/{course_code}")
def get_course_reviews(course_code: str) -> list:
    return get_reviews(course_code)