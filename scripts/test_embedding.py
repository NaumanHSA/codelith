"""
Quick test for the LM Studio embedding endpoint.

Usage:
    conda run -n LLMs python scripts/test_embedding.py

What it checks:
  1. The /v1/embeddings endpoint is reachable
  2. The returned vector dimension matches VECTOR_DIMENSIONS in .env
  3. Cosine similarity works: similar texts score higher than unrelated ones
"""

import asyncio
import math
import os
import sys
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from openai import AsyncOpenAI


def _load_env() -> dict:
    """Read key=value lines from .env in the repo root."""
    env: dict = {}
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return env
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def main() -> None:
    env = _load_env()

    base_url = env.get("LLM_BASE_URL", "http://localhost:1234/v1")
    api_key = env.get("LLM_API_KEY", "lm-studio")
    model = env.get("EMBEDDING_MODEL", "text-embedding-bge-m3")
    expected_dims = int(env.get("VECTOR_DIMENSIONS", "1536"))

    print(f"  Base URL : {base_url}")
    print(f"  Model    : {model}")
    print(f"  Expected : {expected_dims} dimensions")
    print()

    client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    # ── Test 1: single embedding ──────────────────────────────────────────────
    print("Test 1 — single embedding")
    try:
        resp = await client.embeddings.create(model=model, input="Hello, world!")
        vec = resp.data[0].embedding
        dims = len(vec)
        status = "PASS" if dims == expected_dims else "FAIL"
        print(f"  [{status}] got {dims} dims  (expected {expected_dims})")
        print(f"  First 5 values: {[round(v, 6) for v in vec[:5]]}")
        if dims != expected_dims:
            print(f"  !! Update VECTOR_DIMENSIONS={dims} in your .env to match.")
    except Exception as exc:
        print(f"  [FAIL] {exc}")
        print("  Make sure LM Studio is running and the embedding model is loaded.")
        sys.exit(1)

    print()

    # ── Test 2: similarity check ──────────────────────────────────────────────
    print("Test 2 — cosine similarity")
    texts = {
        "A": "FastAPI is a modern Python web framework for building APIs.",
        "B": "FastAPI makes it easy to create REST endpoints in Python.",
        "C": "The Eiffel Tower is located in Paris, France.",
    }

    try:
        batch_resp = await client.embeddings.create(model=model, input=list(texts.values()))
        vecs = {k: batch_resp.data[i].embedding for i, k in enumerate(texts)}

        sim_ab = cosine_similarity(vecs["A"], vecs["B"])
        sim_ac = cosine_similarity(vecs["A"], vecs["C"])

        print(f"  A vs B (similar  ): {sim_ab:.4f}")
        print(f"  A vs C (unrelated): {sim_ac:.4f}")

        if sim_ab > sim_ac:
            print("  [PASS] similar texts score higher than unrelated — embeddings look good!")
        else:
            print("  [WARN] similar texts did NOT score higher — model may not be loaded correctly.")
    except Exception as exc:
        print(f"  [FAIL] {exc}")

    print()

    # ── Test 3: batch throughput ───────────────────────────────────────────────
    print("Test 3 — batch of 10 short strings")
    try:
        import time
        samples = [f"This is test sentence number {i}." for i in range(10)]
        t0 = time.perf_counter()
        batch_resp = await client.embeddings.create(model=model, input=samples)
        elapsed = time.perf_counter() - t0
        count = len(batch_resp.data)
        print(f"  [PASS] {count} embeddings in {elapsed:.2f}s  ({elapsed/count*1000:.1f} ms each)")
    except Exception as exc:
        print(f"  [FAIL] {exc}")


if __name__ == "__main__":
    asyncio.run(main())
