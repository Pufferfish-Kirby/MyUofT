# Remember to call venv/Scripts/activate to get here
# Also run uvicorn main:app --reload
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

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

class RequestData(BaseModel):
    interests: list[str]
    workload: str

@app.post("/recommend")
def recommend(data: RequestData) -> dict:
    return {
        "courses": ["CSC108", "MAT137"]
    }