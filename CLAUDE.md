# MyUofT — AI-Powered Course Planning for University of Toronto Students

## Project Overview

MyUofT is an AI-powered course planning tool that helps University of Toronto students navigate the overwhelming number of courses, minors, majors, and specialist programs available across all three campuses (St. George, UTM, UTSC). The tool understands student preferences, academic goals, and degree requirements, then generates personalized long-term academic plans.

**Core value proposition:** Students shouldn't need to spend weeks parsing the Academic Calendar to figure out what to take. MyUofT turns a 20-minute conversation into a 4-year plan.

---

## Tech Stack

### Current (Phase 1 — Local MVP)
- **Frontend:** React with TypeScript (Vite)
- **Backend:** Python with FastAPI
- **Database:** SQLite (via SQLAlchemy ORM)
- **AI:** Anthropic Claude API (claude-sonnet-4-6) for conversational course advising
- **Styling:** Tailwind CSS

### Live Deployment (Beta)
- **Backend:** Railway, deployed from `backend/` (Root Directory setting) — see
  `backend/Procfile` and `backend/.python-version`. SQLite persists only if a
  Railway Volume is attached (`RAILWAY_VOLUME_MOUNT_PATH` env var); without one,
  `myuoft.db` resets on every redeploy.
- **Frontend:** Vercel, deployed from `frontend/` (Root Directory setting). When
  creating/reconfiguring the Vercel project, do NOT use the "Services" preset —
  it auto-deploys `backend/` too as a serverless function, which breaks SQLite
  persistence and duplicates Railway. Use a single-app preset instead.
- **Config wiring:** frontend's `VITE_API_URL` (full URL incl. `https://` — a
  bare hostname gets treated as a relative path and silently breaks all API
  calls) must point at the Railway domain; Railway's `CORS_ORIGINS` must
  exactly match the Vercel domain (scheme, no trailing slash). Vite env vars
  are baked in at *build* time, not read at runtime — changing the value
  requires a fresh deploy, and a cached build will keep serving the old value.

### Future (Phase 2+ — Production)
- **Database:** PostgreSQL (on AWS RDS)
- **Cloud:** AWS (EC2/ECS for compute, S3 for static assets, CloudFront CDN)
- **Auth:** Clerk or Auth0
- **Caching:** Redis for session state and AI response caching
- **Search:** Embeddings-based semantic search over course descriptions (pgvector)

---

## Architecture

```
┌─────────────────────────────────────────────┐
│                 Frontend (React + TS)        │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
│  │ Chat UI  │ │ Plan View│ │ Course Search│ │
│  └────┬─────┘ └────┬─────┘ └──────┬───────┘ │
│       └─────────────┼──────────────┘         │
│                     │ REST API               │
├─────────────────────┼───────────────────────-┤
│              Backend (FastAPI)                │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
│  │ Chat     │ │ Planner  │ │ Course Data  │ │
│  │ Service  │ │ Service  │ │ Service      │ │
│  └────┬─────┘ └────┬─────┘ └──────┬───────┘ │
│       │             │              │         │
│  ┌────┴─────┐  ┌────┴─────┐  ┌────┴───────┐ │
│  │Claude API│  │ SQLite   │  │Course Data │ │
│  │          │  │ (Plans)  │  │ (JSON/DB)  │ │
│  └──────────┘  └──────────┘  └────────────┘ │
└──────────────────────────────────────────────┘
```

---

## Data Sources for UofT Course Information

Course data should be scraped or imported from:
1. **UofT Academic Calendar** — https://artsci.calendar.utoronto.ca/ (course descriptions, prerequisites, exclusions, program requirements)
2. **Timetable Builder** — https://ttb.utoronto.ca/ (scheduling, sections, enrollment)
3. **Existing open-source scrapers** (reference, not dependency):
   - `cobalt-uoft/uoft-scrapers` — Python scrapers for courses, buildings, etc.
   - `UofT-Course-Tools` GitHub org — GraphQL backend, program scraper, course eval scraper
   - `nikel-api` — REST API with course, program, and textbook data
4. **Program/degree requirements** — scraped from calendar pages per department

### Course Data Schema (target)
```
Course:
  code: str           # e.g., "CSC108H1"
  name: str           # e.g., "Introduction to Computer Programming"
  description: str
  campus: str         # "St. George" | "UTM" | "UTSC"
  department: str
  division: str       # "Faculty of Arts and Science", etc.
  prerequisites: str  # raw text
  corequisites: str
  exclusions: str
  breadth_category: str
  distribution: str
  credit_weight: float  # 0.5 or 1.0
  terms_offered: list[str]  # ["F", "S", "Y"]
  tags: list[str]     # AI-generated topic tags for search
```

### Program Data Schema (actual — from `backend/app/data/programs.json`)
```
Program:
  program_code: str      # e.g., "ASMAJ1689"
  name: str              # e.g., "Computer Science Major (Science Program)"
  type: str              # "Major" | "Minor" | "Specialist"
  enrolment_requirements:
    general: str         # general enrolment description (open vs. limited, prerequisites)
    pathways: list       # optional — list of admission paths, each with:
                         #   heading: str, description: str, requirements: list[str]
    notes: list[str]     # optional clarifying notes
  asip: str | null       # Arts & Science Internship Program info (null if not applicable)
  completion_requirements:
    summary: str         # full credit total + requirements as scraped text,
                         # e.g., "(8.0 credits, including...)"
    first_year:          # optional — structured first-year requirements
      credits: str
      heading: str
      requirements: list[str]
      notes: list[str]
    second_year:         # optional — same structure as first_year
      credits: str
      heading: str
      requirements: list[str]
      notes: list[str]
    upper_years:         # optional — upper-year requirements
      credits: str
      heading: str
      requirements: list[str]
      notes: list[str]
      groups: list       # optional — for Group A / B / C course selections
      criteria: list[str] # optional — selection criteria
      integrative_activity: str  # optional
    transfer_credits: str    # optional
    combining: str           # optional — notes on combining with other programs
    engineering_courses: str # optional
```

---

## Coding Conventions

### Python (Backend)
- Python 3.11+
- Use `ruff` for linting and formatting
- Type hints on all function signatures
- Pydantic models for request/response validation
- Async endpoints where appropriate (especially AI calls)
- Tests with `pytest`; aim for service-level tests, not just unit tests
- Environment variables via `.env` files loaded with `python-dotenv`
- Keep route handlers thin — business logic goes in service modules (currently flat in `backend/`, will migrate to `app/services/` in Phase 2)

### TypeScript (Frontend)
- Strict TypeScript — no `any` types unless absolutely unavoidable
- Functional components with hooks only (no class components)
- Use `fetch` or `axios` for API calls, wrapped in custom hooks
- Component structure: `components/`, `pages/`, `hooks/`, `types/`, `utils/`
- Use Tailwind CSS utility classes; avoid custom CSS files
- State management: React Context for global state initially; consider Zustand if it grows

### General
- All files use 2-space indentation (frontend) or 4-space (Python backend)
- Descriptive variable names — no single-letter variables except loop counters
- Comments explain "why", not "what"
- Git commit messages: conventional commits format (`feat:`, `fix:`, `refactor:`, `docs:`)
- Never commit `.env` files, API keys, or secrets
- Always include error handling for API calls and database operations

---

## Project Structure

> **Note:** The structure below reflects the actual current state. The aspirational
> `app/models/`, `app/schemas/`, `app/routers/`, `app/services/` subdirectories do
> not exist yet — they are the target for Phase 2 when the backend grows beyond its
> current flat layout.

```
myuoft/
├── CLAUDE.md
├── README.md
├── .env.example
├── .gitignore
│
├── backend/
│   ├── main.py              # FastAPI app entry point, all routes live here for now
│   ├── chat_db.py           # SQLite chat session management (init, create, list, messages)
│   ├── reviews_db.py        # Course reviews database (save/get reviews)
│   ├── scoring.py           # Course scoring, recommendation logic, and search by message
│   ├── embeddings.py        # Embedding generation and vector search
│   ├── build_embeddings.py  # One-off script to build the embeddings index from courses.json
│   ├── data_pulling.py      # Data loading utilities (reads courses.json into memory)
│   ├── consolidate_courses.py  # Script to merge/deduplicate scraped course data
│   ├── debug_retrieval.py   # Dev debugging script for retrieval pipeline
│   ├── test_retrieval.py    # Dev test script for retrieval pipeline
│   ├── myuoft.db            # SQLite database (chat sessions, reviews) — not committed
│   │
│   ├── app/
│   │   └── data/                # Static scraped data (committed to repo)
│   │       ├── courses.json     # All Arts & Science course records
│   │       └── programs.json    # All Arts & Science program requirements
│   │
│   ├── scripts/
│   │   ├── scrape_programs.py   # Scraper for program/degree requirements
│   │   ├── enrich_courses.py    # Enriches a batch of courses with AI-generated tags
│   │   └── enrich_all_courses.py  # Runs enrichment across the full catalog
│   │
│   ├── venv/                    # Python virtual environment (not committed)
│   └── requirements.txt
│
│   # Future Phase 2 structure (does not exist yet):
│   # backend/app/__init__.py
│   # backend/app/main.py
│   # backend/app/config.py
│   # backend/app/database.py
│   # backend/app/models/        (SQLAlchemy ORM models)
│   # backend/app/schemas/       (Pydantic request/response schemas)
│   # backend/app/routers/       (API route handlers)
│   # backend/app/services/      (business logic modules)
│
├── frontend/
│   ├── src/
│   │   ├── App.jsx          # Main React component (currently a single-file app)
│   │   └── main.jsx         # Vite entry point
│   │
│   │   # Future structure (not yet built out):
│   │   # components/Chat/, components/Plan/, components/Search/, components/Layout/
│   │   # pages/, hooks/, types/, utils/
│   │
│   ├── package.json
│   ├── vite.config.js
│   └── postcss.config.js
│
└── docs/
    └── plans/               # Claude Code plan files
```

---

## AI Integration Details

### Model Selection
- **Conversational advising (chat):** `claude-sonnet-4-6` — fast, cheap, good at dialogue
- **Complex plan generation:** `claude-sonnet-4-6` with extended system prompt — for generating multi-year plans with constraint satisfaction
- **Embeddings for course search:** Use `voyage-3` or OpenAI `text-embedding-3-small` to embed course descriptions, then store in SQLite (Phase 1) or pgvector (Phase 2)

### System Prompt Strategy
The AI advisor should receive:
1. A system prompt explaining it is a UofT academic advisor
2. Relevant course data injected as context (filtered by student's expressed interests)
3. The student's current academic state (year, completed courses, declared programs)
4. Degree requirements for their declared or prospective programs

### Key AI Features
- **Preference Discovery Chat:** Conversational flow that asks about interests, career goals, course load preferences, schedule constraints
- **Plan Generation:** Takes preferences and outputs a semester-by-semester plan
- **Prerequisite Validation:** Checks that the generated plan respects all prerequisites
- **Course Recommendations:** "Students who liked X also took Y" style suggestions
- **What-If Analysis:** "What would my plan look like if I switched from CS Major to CS Specialist?"

### Chat Privacy Model
Chat sessions are private per-browser via an anonymous device ID (UUID in
`localStorage`, sent as `X-Device-Id` header), not real accounts — Phase 2 is
where real auth (Clerk) replaces this. Course reviews remain global/shared by
design. Any new chat-session endpoint must require `x_device_id: str =
Header(...)` and call `session_belongs_to()` (`backend/chat_db.py`) before
returning or mutating a session — session ids are guessable integers with no
other access control.

---

## Development Phases

### Phase 1: Local MVP (Current)
- [x] Scrape and store Arts & Science course data (St. George) — `courses.json` + `programs.json` done
- [x] Basic FastAPI backend with course search endpoint — `main.py` has course search + chat
- [x] Simple chat interface that talks to Claude API — chat UI + sessions working
- [ ] Generate a basic 4-year plan from chat preferences — not yet implemented
- [x] SQLite database for courses and generated plans — `myuoft.db` with chat sessions + reviews
- [x] React frontend with chat UI and plan display — landing page + chat UI live

### Phase 2: Smart Planning
- [ ] Prerequisite graph and validation
- [ ] Program requirement tracking (major/minor/specialist)
- [ ] Embeddings-based semantic course search
- [ ] Improved plan generation with constraint satisfaction
- [ ] User accounts and saved plans

### Phase 3: Multi-Campus & Scale
- [ ] UTM and UTSC course data
- [ ] PostgreSQL migration
- [ ] AWS deployment
- [ ] Redis caching for AI responses
- [ ] Rate limiting and usage tracking

### Phase 4: Community Features
- [ ] Course reviews and ratings from students
- [ ] Plan sharing and templates
- [ ] Integration with UofT Timetable Builder for scheduling
- [ ] Mobile-responsive redesign

---

## Common Mistakes to Avoid

- **Don't over-engineer early.** SQLite is fine for Phase 1. Don't set up PostgreSQL, Redis, and Kubernetes before the chat works.
- **Don't send the entire course catalog to Claude.** Filter courses by department/interest first, then include only relevant ones in the prompt context.
- **Don't trust AI output blindly.** Always validate generated plans against prerequisite data programmatically.
- **Don't scrape UofT in production.** Scrape once, store as JSON/DB, update periodically. Don't hit their servers on every request.
- **Don't forget about breadth requirements.** UofT Arts & Science has specific breadth/distribution requirements that must be satisfied — the planner must account for these.
- **When generating code, add short comments explaining what each piece does and why it's built that way — keep them tight, not essays.** Aim for ~3 lines per comment: 1-2 sentences on what the code/process does, then 1 sentence on why that choice was made over the obvious alternative. Skip deep technical jargon where a plainer phrase works just as well. I still want to be learning a lot from this project (including being able to explain it in an interview / on my resume), so this is important — just keep it scannable.

---

## Environment Variables

```
# .env.example
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=sqlite:///./myuoft.db
ENVIRONMENT=development
LOG_LEVEL=info
CORS_ORIGINS=http://localhost:5173
```

---

## Commands Reference

```bash
# Backend — activate the venv first (Windows)
cd backend
venv/Scripts/activate          # Windows; use `source venv/bin/activate` on Mac/Linux
pip install -r requirements.txt
uvicorn main:app --reload --port 8000   # NOTE: main:app, not app.main:app

# Frontend
cd frontend
npm install
npm run dev

# Build embeddings index (run once after updating courses.json)
cd backend
python build_embeddings.py

# Scraping / enrichment
cd backend
python scripts/scrape_programs.py
python scripts/enrich_all_courses.py

# Tests
cd backend
pytest tests/ -v
```
