# Remember to call venv/Scripts/activate to get here
# Also run uvicorn main:app --reload --port 8000
import os
from dotenv import load_dotenv
import anthropic
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from scoring import recommend_courses, explain, explain_structured, courses as course_catalog

# Load ANTHROPIC_API_KEY from .env so we never hardcode secrets in source.
load_dotenv()
claude_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# FastAPI() — note the parentheses. Without them `app` would be the class itself,
# not an instance, so every method call below would crash at startup.
app = FastAPI()

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
Be concise, accurate, and friendly. When recommending courses, always mention prerequisites."""


class ChatMessage(BaseModel):
    # "user" or "assistant" — mirrors the Anthropic messages API roles exactly
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    # history lets the frontend send the previous turns so Claude has context
    # for multi-turn conversations without us needing a server-side session store.
    history: list[ChatMessage] = []


class ChatResponse(BaseModel):
    response: str


@app.post("/chat", response_model=ChatResponse)
async def chat(data: ChatRequest) -> ChatResponse:
    # Rebuild the full message list: prior turns (from the frontend) + the new user message.
    # Anthropic expects a flat list of {"role": ..., "content": ...} dicts.
    messages = [{'role': msg.role, 'content': msg.content} for msg in data.history]
    messages.append({"role": "user", "content": data.message})

    try:
        result = claude_client.messages.create(
            model="claude-haiku-4-5",  # haiku is fast/cheap; swap to sonnet for richer answers
            max_tokens=1024,
            system=ADVISOR_SYSTEM_PROMPT,
            messages=messages,
        )
    except anthropic.APIError as e:
        raise HTTPException(status_code=502, detail=f"Claude API error: {e}")

    return ChatResponse(response=result.content[0].text)


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