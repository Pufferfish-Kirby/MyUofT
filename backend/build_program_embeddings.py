"""
build_program_embeddings.py — One-time script to embed all UofT programs.

Generates the embedding index consumed at runtime by embeddings.program_semantic_search().
Run this once after programs.json is updated.

Usage (from inside backend/):
    python build_program_embeddings.py

Outputs:
    backend/program_embeddings.npy   — numpy array, shape (N, 384)
    backend/program_codes.json       — JSON list of program codes, length N
"""
import json
from pathlib import Path

import numpy as np

from program_data import load_programs
from embeddings import encode

programs = load_programs()
print(f"Loaded {len(programs)} programs")
print("First 3 codes:", [p.get_program_code() for p in programs[:3]])
print()

if len(programs) < 50:
    raise SystemExit(
        f"ERROR: only {len(programs)} programs loaded — check programs.json path"
    )

texts = [p.to_text() for p in programs]
codes = [p.get_program_code() for p in programs]

print("Embedding programs...")
vectors = encode(texts)   # shape: (N, 384)

out_dir = Path(__file__).parent
np.save(out_dir / "program_embeddings.npy", vectors)
with open(out_dir / "program_codes.json", "w", encoding="utf-8") as f:
    json.dump(codes, f)

print(f"\nDone. Saved {len(codes)} embeddings, shape {vectors.shape}")
print(f"  -> {out_dir / 'program_embeddings.npy'}")
print(f"  -> {out_dir / 'program_codes.json'}")
