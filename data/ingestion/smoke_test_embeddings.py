"""
3-way embedding smoke test: Jina v3 vs NVIDIA nv-embedqa-e5-v5 vs Bedrock Titan v2

Embeds 6 real products + 3 search queries with all providers.
Computes cosine similarity between each query and all products.
Prints a ranked result table so you can judge which provider understands
e-commerce semantics best.

Run after setting JINA_API_KEY and NVIDIA_API_KEY in .env:
    python data/ingestion/smoke_test_embeddings.py
"""

import json
import math
import os
import sys
import time
from pathlib import Path

import boto3
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")
os.environ.pop("AWS_PROFILE", None)

JINA_KEY   = os.environ.get("JINA_API_KEY", "").strip()
NVIDIA_KEY = os.environ.get("NVIDIA_API_KEY", "").strip()

# ── Test data ─────────────────────────────────────────────────────────────────

PRODUCTS = [
    {"id": "p1", "text": "Dell XPS 15 OLED laptop Intel Core i9 32GB RAM 1TB SSD NVIDIA RTX 4070 15.6 inch touchscreen display. Excellent performance and stunning display. Premium build quality."},
    {"id": "p2", "text": "Lenovo ThinkPad X1 Carbon lightweight business laptop 14 inch Intel Core i7 16GB RAM 512GB SSD 12 hour battery life. Best in class keyboard and durability."},
    {"id": "p3", "text": "ASUS ROG Strix G16 gaming laptop AMD Ryzen 9 RTX 4080 16GB RAM 144Hz display RGB keyboard. Dominates AAA games at ultra settings."},
    {"id": "p4", "text": "Apple MacBook Air M3 chip 13 inch 8GB unified memory 256GB SSD fanless design 18 hour battery. Silent, fast, perfect for everyday use."},
    {"id": "p5", "text": "HP Spectre x360 2-in-1 convertible laptop 13 inch OLED touchscreen Intel Core i7 16GB 512GB pen stylus. Great for creative work and note-taking."},
    {"id": "p6", "text": "Acer Aspire 5 budget laptop 15 inch AMD Ryzen 5 8GB RAM 256GB SSD Full HD display. Reliable everyday laptop at an affordable price."},
]

QUERIES = [
    {"id": "q1", "text": "laptop for video editing and creative work",       "expect_top": ["p1", "p5"]},
    {"id": "q2", "text": "gaming laptop with high refresh rate display",     "expect_top": ["p3"]},
    {"id": "q3", "text": "lightweight laptop with long battery for travel",   "expect_top": ["p2", "p4"]},
]


# ── Embedding providers ───────────────────────────────────────────────────────

def embed_jina(texts: list[str], task: str = "retrieval.passage") -> list[list[float]]:
    resp = requests.post(
        "https://api.jina.ai/v1/embeddings",
        headers={"Authorization": f"Bearer {JINA_KEY}", "Content-Type": "application/json"},
        json={"model": "jina-embeddings-v3", "task": task, "dimensions": 1024,
              "input": texts, "normalized": True},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return [d["embedding"] for d in sorted(data["data"], key=lambda x: x["index"])]


def embed_nvidia(texts: list[str], input_type: str = "passage") -> list[list[float]]:
    resp = requests.post(
        "https://integrate.api.nvidia.com/v1/embeddings",
        headers={"Authorization": f"Bearer {NVIDIA_KEY}", "Content-Type": "application/json"},
        json={"model": "nvidia/nv-embedqa-e5-v5", "input": texts,
              "input_type": input_type, "encoding_format": "float"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return [d["embedding"] for d in sorted(data["data"], key=lambda x: x["index"])]


def embed_titan(texts: list[str]) -> list[list[float]]:
    client = boto3.client("bedrock-runtime", region_name="eu-north-1")
    vecs = []
    for text in texts:
        body = json.dumps({"inputText": text[:8000], "dimensions": 1024, "normalize": True})
        r = client.invoke_model(
            modelId="amazon.titan-embed-text-v2:0",
            body=body, contentType="application/json", accept="application/json",
        )
        vecs.append(json.loads(r["body"].read())["embedding"])
    return vecs


# ── Scoring ───────────────────────────────────────────────────────────────────

def cosine(a: list[float], b: list[float]) -> float:
    dot  = sum(x * y for x, y in zip(a, b))
    na   = math.sqrt(sum(x * x for x in a))
    nb   = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def run_provider(name: str, product_vecs: list[list[float]], query_vecs: list[list[float]]) -> int:
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    total_hits = 0
    for q, qvec in zip(QUERIES, query_vecs):
        scores = [(p["id"], cosine(qvec, pvec)) for p, pvec in zip(PRODUCTS, product_vecs)]
        scores.sort(key=lambda x: -x[1])
        top1 = scores[0][0]
        hit  = top1 in q["expect_top"]
        total_hits += int(hit)
        print(f"\n  Query: \"{q['text']}\"")
        print(f"  Expected top: {q['expect_top']}")
        for rank, (pid, score) in enumerate(scores[:3], 1):
            label = next(p["text"][:50] for p in PRODUCTS if p["id"] == pid)
            marker = " ✓" if pid in q["expect_top"] else ""
            print(f"    {rank}. [{pid}] {label}...  sim={score:.4f}{marker}")
        print(f"  Result: {'HIT ✓' if hit else 'MISS ✗'}")
    print(f"\n  Score: {total_hits}/{len(QUERIES)} queries ranked correctly")
    return total_hits


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    product_texts = [p["text"] for p in PRODUCTS]
    query_texts   = [q["text"] for q in QUERIES]

    results: dict[str, int] = {}

    # ── Jina ─────────────────────────────────────────────────────────────────
    if JINA_KEY:
        print("\nRunning Jina v3...")
        t = time.time()
        pvecs = embed_jina(product_texts, task="retrieval.passage")
        qvecs = embed_jina(query_texts,   task="retrieval.query")
        elapsed = time.time() - t
        print(f"  dims={len(pvecs[0])}  time={elapsed:.1f}s  cost=~$0 (free tier)")
        results["Jina v3 (1024-dim)"] = run_provider("Jina v3 (1024-dim)", pvecs, qvecs)
    else:
        print("\nSkipping Jina — JINA_API_KEY not set in .env")

    # ── NVIDIA ────────────────────────────────────────────────────────────────
    if NVIDIA_KEY:
        print("\nRunning NVIDIA nv-embedqa-e5-v5...")
        t = time.time()
        pvecs = embed_nvidia(product_texts, input_type="passage")
        qvecs = embed_nvidia(query_texts,   input_type="query")
        elapsed = time.time() - t
        print(f"  dims={len(pvecs[0])}  time={elapsed:.1f}s  cost=~$0 (free credits)")
        results["NVIDIA nv-embedqa-e5-v5 (1024-dim)"] = run_provider("NVIDIA nv-embedqa-e5-v5 (1024-dim)", pvecs, qvecs)
    else:
        print("\nSkipping NVIDIA — NVIDIA_API_KEY not set in .env")

    # ── Titan ─────────────────────────────────────────────────────────────────
    print("\nRunning Bedrock Titan v2...")
    t = time.time()
    pvecs = embed_titan(product_texts)
    qvecs = embed_titan(query_texts)
    elapsed = time.time() - t
    cost = (len(product_texts) + len(query_texts)) * 15 * 0.00002  # rough token estimate
    print(f"  dims={len(pvecs[0])}  time={elapsed:.1f}s  cost=~${cost:.4f}")
    results["Bedrock Titan v2 (1024-dim)"] = run_provider("Bedrock Titan v2 (1024-dim)", pvecs, qvecs)

    # ── Winner ────────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  FINAL SCORES")
    print(f"{'='*60}")
    for provider, score in sorted(results.items(), key=lambda x: -x[1]):
        bar = "█" * score + "░" * (len(QUERIES) - score)
        print(f"  {bar}  {score}/{len(QUERIES)}  {provider}")
    winner = max(results, key=results.get) if results else "Bedrock Titan v2 (1024-dim)"
    print(f"\n  Recommendation: {winner}")


if __name__ == "__main__":
    main()
