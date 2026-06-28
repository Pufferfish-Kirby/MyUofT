from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

# ── Model singleton ──────────────────────────────────────────────────────────
# ~90 MB, takes a few seconds to load. Loaded once on first encode/search call.
_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def encode(texts: list[str], show_progress: bool = False) -> np.ndarray:
    """Embed a list of strings. Returns shape (len(texts), 384)."""
    return get_model().encode(texts, show_progress_bar=show_progress, convert_to_numpy=True)


# ── Embedding index singleton ────────────────────────────────────────────────
# Loaded lazily from disk on first semantic_search() call. The .npy matrix is
# ~5 MB so we keep it in memory for the lifetime of the process rather than
# re-reading it on each request.
_vectors: np.ndarray | None = None
_codes: list[str] | None = None


def _load_index() -> tuple[np.ndarray, list[str]]:
    global _vectors, _codes
    if _vectors is None:
        here = Path(__file__).parent
        _vectors = np.load(here / "course_embeddings.npy")
        with open(here / "course_codes.json", encoding="utf-8") as f:
            _codes = json.load(f)
    return _vectors, _codes


def semantic_search(
    query: str,
    top_n: int = 5,
    allowed_codes: set[str] | None = None,
) -> list[tuple[str, float]]:
    """
    Find the top_n most semantically similar courses for a free-text query.

    Returns (course_code, cosine_similarity) pairs sorted highest-first.

    Args:
        query:         Free-text search string (stop-word-stripped recommended).
        top_n:         Maximum number of results to return.
        allowed_codes: When provided, restrict scoring to only these course codes.
                       Courses not in the set are masked to -inf and never appear
                       in the output. This lets callers pre-filter by year level
                       (or any criterion) BEFORE the top-N selection runs, so all
                       returned results come from the allowed pool.

                       WHY filter here rather than post-hoc in the caller:
                       Post-hoc filtering after a full search can silently return
                       fewer than top_n results when many top candidates are
                       excluded. The mask approach ensures argsort always selects
                       from the allowed rows and returns up to top_n valid results.

    WHY cosine similarity over dot product:
        The stored vectors are not L2-normalised, so raw dot products would
        favour longer (higher-magnitude) vectors. Cosine similarity normalises
        both sides so we measure angle, not magnitude — a course with a very
        long description won't automatically beat a short one.
    """
    vectors, codes = _load_index()
    query_vec = get_model().encode([query], convert_to_numpy=True)[0]  # (384,)

    norms = np.linalg.norm(vectors, axis=1) * np.linalg.norm(query_vec)
    # Guard against zero-magnitude vectors (shouldn't happen, but safe)
    sims = (vectors @ query_vec) / np.where(norms == 0, 1e-9, norms)

    if allowed_codes is not None:
        # Build a boolean mask: True for rows whose code is in allowed_codes.
        # WHY -np.inf not 0: cosine similarity is defined on [-1, 1], so any
        # finite sentinel could collide with a real score. -inf is always less
        # than any real cosine value, so excluded rows can never win a top-N slot.
        mask = np.array([c in allowed_codes for c in codes], dtype=bool)
        sims = np.where(mask, sims, -np.inf)

    top_indices = np.argsort(sims)[::-1][:top_n]
    return [(codes[i], float(sims[i])) for i in top_indices]


# ── Program embedding index singleton ────────────────────────────────────────
# Separate globals from the course index so the two searches use the same
# _model singleton but independent vector matrices. The model (~90 MB) is
# never loaded twice — get_model() returns the cached instance either way.
_program_vectors: np.ndarray | None = None
_program_codes: list[str] | None = None


def _load_program_index() -> tuple[np.ndarray, list[str]]:
    """Load program embeddings from disk, caching in module-level globals."""
    global _program_vectors, _program_codes
    if _program_vectors is None:
        here = Path(__file__).parent
        _program_vectors = np.load(here / "program_embeddings.npy")
        with open(here / "program_codes.json", encoding="utf-8") as f:
            _program_codes = json.load(f)
    return _program_vectors, _program_codes


def program_semantic_search(
    query: str,
    top_n: int = 3,
    allowed_codes: set[str] | None = None,
) -> list[tuple[str, float]]:
    """
    Find the top_n most semantically similar programs for a free-text query.

    Identical cosine-similarity algorithm as semantic_search() but operates on
    the program embedding matrix. Reuses the _model singleton loaded by
    get_model() so the 90 MB model is never loaded twice.

    Args:
        query:         Free-text search string (stop-word-stripped recommended).
        top_n:         Maximum results to return (default 3).
        allowed_codes: When provided, restrict scoring to only these program codes.
                       Used for type filtering (e.g. only "Specialist" programs).
                       Excluded programs are masked to -inf so they never appear
                       in the top-N result, even if semantically similar.

    WHY not refactor semantic_search() to share logic:
        semantic_search() is already stable and tested. Changing its signature
        would break existing callers in scoring.py. Adding a parallel function
        is surgical and zero-risk. Unification can happen in a future refactor.
    """
    vectors, codes = _load_program_index()
    query_vec = get_model().encode([query], convert_to_numpy=True)[0]

    norms = np.linalg.norm(vectors, axis=1) * np.linalg.norm(query_vec)
    sims = (vectors @ query_vec) / np.where(norms == 0, 1e-9, norms)

    if allowed_codes is not None:
        mask = np.array([c in allowed_codes for c in codes], dtype=bool)
        sims = np.where(mask, sims, -np.inf)

    top_indices = np.argsort(sims)[::-1][:top_n]
    return [(codes[i], float(sims[i])) for i in top_indices]
