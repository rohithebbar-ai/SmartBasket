"""
Generate and upsert product embeddings to Qdrant using Jina v3.

For each product (default: all with sentiment scored):
  1. Constructs embedding text: name + brand + category + specs + top_praise
  2. Calls Jina API in batches of 50 (passage task mode)
  3. Upserts vector + full payload to Qdrant
  4. Creates the collection if it doesn't exist

Qdrant payload per product:
  product_id, name, brand, category, current_price, base_price, avg_rating,
  stock_available, battery_sentiment, display_sentiment, build_quality_sentiment,
  value_sentiment, performance_sentiment, keyboard_sentiment, thermal_sentiment,
  top_complaint, top_praise, use_cases, specs_json

Run:
    python data/ingestion/generate_embeddings.py
    python data/ingestion/generate_embeddings.py --all          # include products without sentiment
    python data/ingestion/generate_embeddings.py --batch-size 50
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

sys.path.insert(0, str(Path(__file__).parent))
from db_utils import dual_connect, fetch_primary

load_dotenv(Path(__file__).parent.parent.parent / ".env")
os.environ.pop("AWS_PROFILE", None)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

JINA_API_KEY    = os.environ["JINA_API_KEY"]
JINA_MODEL      = os.environ.get("JINA_MODEL", "jina-embeddings-v3")
EMBEDDING_DIMS  = int(os.environ.get("EMBEDDING_DIMENSIONS", "1024"))

QDRANT_URL      = os.environ.get("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY  = os.environ.get("QDRANT_API_KEY") or None
COLLECTION_NAME = os.environ.get("QDRANT_COLLECTION_NAME", "products")

BATCH_SIZE      = 50
LOG_EVERY       = 200


# ── Embedding text construction ───────────────────────────────────────────────

def build_embedding_text(row: dict) -> str:
    """
    Natural-language representation of a product for embedding.
    Structured fields expressed as sentences rather than raw JSON so the model
    maps them to the same semantic space as user queries.
    """
    parts = [f"{row['brand']} {row['name']}."]

    if row.get("category"):
        parts.append(f"Category: {row['category']}.")

    specs = row.get("specs") or {}
    if isinstance(specs, str):
        try:
            specs = json.loads(specs)
        except (json.JSONDecodeError, TypeError):
            specs = {}

    spec_parts = []
    if specs.get("ram_gb"):
        spec_parts.append(f"{specs['ram_gb']}GB RAM")
    if specs.get("storage_gb"):
        spec_parts.append(f"{specs['storage_gb']}GB storage")
    if specs.get("display_size_inch"):
        spec_parts.append(f"{specs['display_size_inch']} inch display")
    if specs.get("processor"):
        spec_parts.append(str(specs["processor"]))
    if specs.get("gpu"):
        spec_parts.append(str(specs["gpu"]))
    if specs.get("battery_wh"):
        spec_parts.append(f"{specs['battery_wh']}Wh battery")
    if specs.get("weight_kg"):
        spec_parts.append(f"{specs['weight_kg']}kg")
    if spec_parts:
        parts.append("Specs: " + ", ".join(spec_parts) + ".")

    use_cases = specs.get("use_cases") or []
    if use_cases:
        parts.append("Best for: " + ", ".join(use_cases) + ".")

    if row.get("top_praise"):
        parts.append(f"Customers say: {row['top_praise']}")

    return " ".join(parts)


# ── Jina API ──────────────────────────────────────────────────────────────────

_session = requests.Session()
_session.headers.update({
    "Authorization": f"Bearer {JINA_API_KEY}",
    "Content-Type": "application/json",
})


def embed_batch(texts: list[str]) -> list[list[float]]:
    resp = _session.post(
        "https://api.jina.ai/v1/embeddings",
        json={
            "model": JINA_MODEL,
            "task": "retrieval.passage",
            "dimensions": EMBEDDING_DIMS,
            "input": texts,
            "normalized": True,
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return [d["embedding"] for d in sorted(data["data"], key=lambda x: x["index"])]


# ── Qdrant helpers ────────────────────────────────────────────────────────────

def ensure_collection(client: QdrantClient) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=EMBEDDING_DIMS, distance=Distance.COSINE),
        )
        log.info("Created Qdrant collection '%s' (%d-dim, cosine)", COLLECTION_NAME, EMBEDDING_DIMS)
    else:
        log.info("Collection '%s' already exists — upserting", COLLECTION_NAME)


def build_payload(row: dict) -> dict:
    specs = row.get("specs") or {}
    if isinstance(specs, str):
        try:
            specs = json.loads(specs)
        except (json.JSONDecodeError, TypeError):
            specs = {}

    return {
        "product_id":               str(row["id"]),
        "name":                     row["name"],
        "brand":                    row["brand"],
        "category":                 row.get("category"),
        "current_price":            float(row["current_price"]) if row.get("current_price") else None,
        "base_price":               float(row["base_price"]) if row.get("base_price") else None,
        "avg_rating":               float(row["avg_rating"]) if row.get("avg_rating") else None,
        "stock_available":          (row.get("stock_count") or 0) > 0,
        "battery_sentiment":        row.get("battery_sentiment"),
        "display_sentiment":        row.get("display_sentiment"),
        "build_quality_sentiment":  row.get("build_quality_sentiment"),
        "value_sentiment":          row.get("value_sentiment"),
        "performance_sentiment":    row.get("performance_sentiment"),
        "keyboard_sentiment":       row.get("keyboard_sentiment"),
        "thermal_sentiment":        row.get("thermal_sentiment"),
        "top_complaint":            row.get("top_complaint"),
        "top_praise":               row.get("top_praise"),
        "use_cases":                specs.get("use_cases") or [],
        "specs_json":               json.dumps(specs),
    }


def upsert_batch(client: QdrantClient, rows: list[dict], vectors: list[list[float]]) -> None:
    points = [
        PointStruct(id=str(row["id"]), vector=vec, payload=build_payload(row))
        for row, vec in zip(rows, vectors)
    ]
    client.upsert(collection_name=COLLECTION_NAME, points=points, wait=True)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(embed_all: bool = False, batch_size: int = BATCH_SIZE) -> None:
    async with dual_connect() as conns:
        query = (
            "SELECT * FROM products WHERE is_active = true ORDER BY avg_rating DESC NULLS LAST"
            if embed_all else
            """
            SELECT * FROM products
            WHERE is_active = true AND sentiment_scored_at IS NOT NULL
            ORDER BY avg_rating DESC NULLS LAST
            """
        )
        products = [dict(r) for r in await fetch_primary(conns, query)]

    total = len(products)
    log.info("Products to embed: %d  batch_size=%d", total, batch_size)

    qdrant = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=30)
    ensure_collection(qdrant)

    upserted = failed = 0
    t0 = time.time()

    for i in range(0, total, batch_size):
        batch = products[i : i + batch_size]
        texts = [build_embedding_text(r) for r in batch]

        try:
            vectors = embed_batch(texts)
            upsert_batch(qdrant, batch, vectors)
            upserted += len(batch)
        except Exception as exc:
            log.warning("Batch %d–%d failed: %s", i, i + len(batch), exc)
            failed += len(batch)
            continue

        done = i + len(batch)
        if done % LOG_EVERY == 0 or done >= total:
            elapsed = time.time() - t0
            rate = done / elapsed if elapsed else 0
            eta  = (total - done) / rate if rate else 0
            log.info(
                "Progress %d/%d | upserted=%d failed=%d | %.0f/min | ETA ~%.0fs",
                done, total, upserted, failed, rate * 60, eta,
            )

        await asyncio.sleep(1.0 / 50)  # 50 req/s Jina rate limit

    elapsed = time.time() - t0
    log.info("Done. upserted=%d failed=%d time=%.0fs", upserted, failed, elapsed)

    info = qdrant.get_collection(COLLECTION_NAME)
    log.info(
        "Qdrant '%s': %d vectors | Dashboard: %s/dashboard",
        COLLECTION_NAME, info.points_count, QDRANT_URL,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true",
                        help="Embed all active products, not just sentiment-scored ones")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = parser.parse_args()
    asyncio.run(main(embed_all=args.all, batch_size=args.batch_size))
