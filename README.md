# MyUofT

Course selection at the University of Toronto can be a long process where you have to go to multiple pages to get the information you need. MyUoft gives you one space to get everything you need, using AI-powered course advising. Ask it what you're interested in, get back real courses from the actual calendar, not a keyword match.

**Live: [my-uoft.vercel.app](https://my-uoft.vercel.app)**

## What it does

MyUofT is a app that knows the entire University of Toronto Faculty of Arts & Science course catalog and answers questions about it conversationally. Instead of digging through the Academic Calendar and trying to put the pieces together yourself, you describe what you want and it finds courses that actually fit your needs and shows you why it is best.

## How it works

The core is a retrieval-augmented generation (RAG) pipeline: a student's message is embedded and compared against a pre-built vector index of every course description. The top matches are pulled out and are injected into Claude's context for the actual response. This prevents Claude from hallucinating course codes it was never shown.

Retrieval itself is hybrid, not pure semantic search:

1. **Course-code regex** — if the message contains something like `MAT235` or `CSC108H1`, it's pulled out and pinned to the top of the results immediately, no embedding search needed.
2. **Year-level and breadth filtering** — phrases like "first year" or "breadth 2" are detected with regex and take priority in the search process, better filtering the information you need.
3. **Semantic search** — the (filtered) remaining query goes through Voyage AI's embedding model to rank by cosine similarity against the course vector index.
4. **Difficulty re-ranking** — "easy" or "hard" phrasing blends a difficulty score into the final ordering (70% similarity / 30% difficulty) without ever hard-filtering, so it re-ranks instead of throwing away good matches.

A separate embedding index does the same thing for program/degree requirement data, so questions about specific majors or specialists get grounded in the actual 169-program dataset instead of Claude's general knowledge of UofT.

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React, TypeScript, Vite, Tailwind CSS |
| Backend | FastAPI, Python |
| AI (chat) | Claude Haiku 4.5 |
| AI (course enrichment) | Claude Haiku 4.5 via the Anthropic Batches API |
| Embeddings | Voyage AI (`voyage-3-lite`) |
| Data | SQLite (chat sessions, reviews), JSON (course/program catalog) |
| Deployment | Vercel (frontend), Railway (backend) |

## Architecture decisions worth knowing about

**Keyword synonym map → embeddings-based semantic search.**
The first version of retrieval was a hand-maintained `INTEREST_SYNONYMS` dict (ex: "coding" manually mapped to `["programming", "python", "software", ...]`). It worked for single words a developer thought to add, and fell apart on anything else. Query `"first year proof courses"` against the synonym map returned nothing, because no expansion rule connects "proof" to `MAT138H1`'s actual title, "Introduction to Proofs." Semantic search surfaces compares meaning, not vocabulary overlap. This allows courses to better match with keywords.

**Difficulty/workload scored courses from a one-time Haiku batch job, not manual entry or a bigger model.**
Every one of the 3,206 courses got AI-scored for difficulty and workload once, using Claude Haiku through the Anthropic **Batches API**. Batches run async at a 50% token discount over the same calls made one at a time, making an important feature cost less.

**Hybrid retrieval: semantic search plus structured filters**
A query like "capstone-style research project in my field" can rank a genuinely relevant 4th-year capstone course above a first-year intro course. The fix was catching year-level and breadth-category phrases with regex *before* the embedding search runs, masking the pool of courses to avoid this problem. The same principle showed up again in the program-advising RAG: semantic search could find the right *program*, but answering "what do I need for second year CS specialist" also requires the *exact* course codes for that specific year. That's now handled by reusing the same year-detection regex to force-include the guaranteed-correct course codes into context, rather than hoping the embedding surfaces them.

**Local sentence-transformers → Voyage AI's hosted embedding API.**
Embeddings originally ran locally via `sentence-transformers` and the `all-MiniLM-L6-v2` hugging face model. It's free, but it gave me problems. In production on Railway, the model kept ~90MB of data, plus torch's much larger runtime to look through the 90 MB made a simple query take 30 seconds. Switching to Voyage's `voyage-3-lite` API replaced a fixed call with a cheap API call and made the queries send in 2 seconds.

## What's not built yet

- **Structured, multi-year plan generation** — chat can recommend individual courses and answer program-requirement questions conversationally, but it doesn't yet output a semester-by-semester 4-year plan.
- **Full program-requirement tracking** — prerequisite eligibility is checked per-course (`is_eligible()` walks the parsed AND/OR prerequisite tree against a student's completed courses), but there's no persistent tracking of progress against a *declared* major/minor/specialist over time.
- **Student accounts/profiles** — chat sessions are private per-browser via an anonymous device ID in `localStorage`, not real accounts.
- **Auto-generated scheduling** — no timetable-conflict resolution or integration with the Timetable Builder yet.
- **RateMyProfessors data** — link out to it, don't scrape or mirror it.
- **UTM/UTSC campuses, Engineering, Music...** course and program data is currently specific to the Faculty of Arts and Science

## Project structure

```
myuoft/
├── backend/
│   ├── main.py                  # FastAPI app, all routes
│   ├── scoring.py                # Course model, scoring, hybrid retrieval logic
│   ├── embeddings.py             # Voyage API client, semantic search over course/program vectors
│   ├── chat_db.py                # SQLite chat session management
│   ├── reviews_db.py             # Course review storage
│   ├── build_embeddings.py       # One-off script: embed catalog, save vectors to disk
│   ├── scripts/                  # Scraping and AI-enrichment scripts
│   └── app/data/                 # courses.json, programs.json (scraped catalog)
├── frontend/
│   └── src/
│       ├── App.jsx                # Chat UI, landing page (single-file for now)
│       └── main.jsx               # Vite entry point
└── docs/
    └── plans/                     # Claude Code plan files
```

## Lessons learned
- **Retrieval bugs hide on the way.** The majority of my RAG errors came as I continued to test. Once I realized it couldn't search for a year and fixed that problem, it could not fetch descriptions, and so on. It's important to use test-driven development to understand what you need so you can solve everything in one go.
- **Semantic search is a "probably close enough" tool, not a lookup.** Being able to write the word MAT235 didn't mean my AI would get MAT235H1, which is the actual course code. It's important to build feature to make sure "close enough" can work.
- **Batch APIs change the economics of "AI-enrich the whole catalog."** Scoring 3,206 courses for difficulty/workload individually and synchronously would have been slow and needlessly expensive; the same job through the Batches API, polled every 60 seconds until done, cost a fraction of that and ran unattended.
- **Career/topic questions need general knowledge, not just retrieval.** Asking about reinforcement learning and got back seemingly random courses. I then split the system prompt into two tiers: grounded UofT facts that must come only from retrieved course context, and general "how does this field work" knowledge. Creating a system prompt isn't always about being super strict. You have to give it a bit of freedom so it can answer follow-up questions.

## Try it

**[my-uoft.vercel.app](https://my-uoft.vercel.app)**

Ask something like: *"what are some good first year proof-based math courses?"* — a plain keyword search on that phrase returns nothing useful (none of the words "proof-based" appear verbatim in most course titles), but the semantic search correctly surfaces `MAT138H1 — Introduction to Proofs` as the top result.
