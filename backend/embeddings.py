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
        allowed_codes: When provided, only these course codes can be returned;
                       everything else is masked out before the top-N pick.
                       Filtering here (not after the search) guarantees we still
                       return a full top_n even when many courses are excluded.

    Uses cosine similarity, not a raw dot product, because the stored vectors
    aren't normalised — a plain dot product would just reward courses with
    longer descriptions instead of ones that actually match.
    """
    vectors, codes = _load_index()
    query_vec = get_model().encode([query], convert_to_numpy=True)[0]  # (384,)

    norms = np.linalg.norm(vectors, axis=1) * np.linalg.norm(query_vec)
    # Guard against zero-magnitude vectors (shouldn't happen, but safe)
    sims = (vectors @ query_vec) / np.where(norms == 0, 1e-9, norms)

    if allowed_codes is not None:
        # Mask excluded rows to -inf so they can never win a top-N slot. We use
        # -inf rather than 0 because cosine scores live in [-1, 1], so any finite
        # sentinel could collide with a real score.
        mask = np.array([c in allowed_codes for c in codes], dtype=bool)
        sims = np.where(mask, sims, -np.inf)

    top_indices = np.argsort(sims)[::-1][:top_n]
    return [(codes[i], float(sims[i])) for i in top_indices]


# ── Program embedding index singleton ────────────────────────────────────────
# Separate vector matrices from the course index, but the same _model singleton.
# Kept apart so program search and course search don't share a vector space.
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

    Same cosine-similarity approach as semantic_search(), just over the program
    vectors. allowed_codes restricts results to certain program types (e.g. only
    "Specialist"), masking everything else out before the top-N pick.

    This deliberately duplicates semantic_search() instead of sharing logic —
    that function is already stable and reused, so a parallel copy avoids
    touching it and risking existing callers. Could be unified later.
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
