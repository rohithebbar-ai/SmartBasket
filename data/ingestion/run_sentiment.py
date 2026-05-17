"""
Batch aspect-sentiment extraction for ShopSense products.

For each product (top 1,500 by review count, skipping already-scored ones):
  1. Fetch all reviews from PostgreSQL (primary/local DB)
  2. Call Bedrock Haiku with ASPECT_SENTIMENT_PROMPT
  3. Parse JSON response → 7 sentiment floats + top_complaint + top_praise
  4. Write to products table on all DBs (dual-write)
  5. Mark sentiment_scored_at = now()

Resumable: re-running skips products where sentiment_scored_at IS NOT NULL.
Estimated runtime: ~15–20 minutes for 1,500 products with Haiku.

Run:
    DATABASE_URL=postgresql+asyncpg://shopsense:shopsense@localhost:5432/shopsense \
    MIRROR_DATABASE_URL=<supabase-url> \
      python data/ingestion/run_sentiment.py [--limit 1500]
"""

import asyncio
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import boto3
import asyncpg

sys.path.insert(0, str(Path(__file__).parent))
from db_utils import dual_connect, fetch_primary, fetchval_primary

# db_utils calls load_dotenv() which may restore AWS_PROFILE from .env.
# The .env references a named profile (e.g. shopsense-dev) that may not exist
# locally. Strip it after dotenv so boto3 uses the default credentials chain.
os.environ.pop("AWS_PROFILE", None)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_LIMIT = 1_500
MODEL_ID = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
AWS_REGION = "eu-north-1"
MAX_TOKENS = 512
SLEEP_BETWEEN_CALLS = 0.3   # seconds — stays well inside Bedrock rate limits
BATCH_LOG_EVERY = 50        # log progress every N products

ASPECT_SENTIMENT_PROMPT = """\
Analyse these product reviews and extract sentiment scores from 1.0 to 5.0.
Return JSON only — no explanation, no markdown.

Reviews:
{reviews_text}

Return exactly this JSON structure (use null for aspects not mentioned at all):
{{
  "battery_sentiment": 3.8,
  "display_sentiment": 4.7,
  "build_quality_sentiment": 4.2,
  "value_sentiment": 3.5,
  "performance_sentiment": 4.6,
  "keyboard_sentiment": 4.0,
  "thermal_sentiment": 3.2,
  "top_complaint": "short one-sentence summary of the most common complaint",
  "top_praise": "short one-sentence summary of the most common praise"
}}"""

SENTIMENT_FIELDS = [
    "battery_sentiment",
    "display_sentiment",
    "build_quality_sentiment",
    "value_sentiment",
    "performance_sentiment",
    "keyboard_sentiment",
    "thermal_sentiment",
]

# ── Bedrock client (module-level singleton) ───────────────────────────────────

_bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)


def call_bedrock(reviews_text: str) -> dict:
    """
    Calls Bedrock Haiku with the aspect sentiment prompt.
    Returns parsed dict or raises on parse failure.
    """
    prompt = ASPECT_SENTIMENT_PROMPT.format(reviews_text=reviews_text)
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    })
    response = _bedrock.invoke_model(
        modelId=MODEL_ID,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    raw = json.loads(response["body"].read())
    text = raw["content"][0]["text"].strip()

    # Strip markdown code fences if model wraps in ```json ... ```
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    return json.loads(text)


# ── DB helpers ────────────────────────────────────────────────────────────────

UPDATE_SQL = """
UPDATE products SET
  battery_sentiment        = $1,
  display_sentiment        = $2,
  build_quality_sentiment  = $3,
  value_sentiment          = $4,
  performance_sentiment    = $5,
  keyboard_sentiment       = $6,
  thermal_sentiment        = $7,
  top_complaint            = $8,
  top_praise               = $9,
  sentiment_scored_at      = now()
WHERE id = $10
"""


async def write_scores(conns: list, product_id, scores: dict) -> None:
    args = (
        scores.get("battery_sentiment"),
        scores.get("display_sentiment"),
        scores.get("build_quality_sentiment"),
        scores.get("value_sentiment"),
        scores.get("performance_sentiment"),
        scores.get("keyboard_sentiment"),
        scores.get("thermal_sentiment"),
        scores.get("top_complaint"),
        scores.get("top_praise"),
        product_id,
    )
    for conn in conns:
        await conn.execute(UPDATE_SQL, *args)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(limit: int = DEFAULT_LIMIT) -> None:
    async with dual_connect() as conns:
        # Products ordered by review count, skipping already-scored ones
        products = await fetch_primary(
            conns,
            """
            SELECT p.id, p.name, p.brand,
                   COUNT(r.id) AS review_count
            FROM products p
            LEFT JOIN reviews r ON r.product_id = p.id
            WHERE p.is_active = true
              AND p.sentiment_scored_at IS NULL
            GROUP BY p.id
            HAVING COUNT(r.id) > 0
            ORDER BY review_count DESC
            LIMIT $1
            """,
            limit,
        )

        total = len(products)
        log.info("Products to score: %d (limit=%d)", total, limit)

        if total == 0:
            log.info("Nothing to do — all products already scored.")
            return

        scored = 0
        failed = 0
        t0 = time.time()

        for i, product in enumerate(products, 1):
            pid   = product["id"]
            name  = product["name"]
            brand = product["brand"]
            rcount = product["review_count"]

            # Fetch review texts for this product
            rows = await fetch_primary(
                conns,
                "SELECT rating, review_text FROM reviews WHERE product_id = $1",
                pid,
            )
            if not rows:
                continue

            # Format reviews for the prompt (rating + text)
            reviews_text = "\n---\n".join(
                f"Rating: {r['rating']}/5\n{(r['review_text'] or '').strip()}"
                for r in rows
                if r["review_text"]
            )
            if not reviews_text:
                continue

            try:
                scores = call_bedrock(reviews_text)
                await write_scores(conns, pid, scores)
                scored += 1
            except Exception as exc:
                log.warning("Failed [%s %s]: %s", brand, name, exc)
                failed += 1

            if i % BATCH_LOG_EVERY == 0 or i == total:
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed else 0
                eta = (total - i) / rate if rate else 0
                log.info(
                    "Progress %d/%d | scored=%d failed=%d | %.1f/min | ETA ~%.0fs",
                    i, total, scored, failed, rate * 60, eta,
                )

            if SLEEP_BETWEEN_CALLS and i < total:
                await asyncio.sleep(SLEEP_BETWEEN_CALLS)

        elapsed = time.time() - t0
        log.info(
            "Done. scored=%d failed=%d total_time=%.0fs",
            scored, failed, elapsed,
        )

        # Final count for verification
        done_count = await fetchval_primary(
            conns,
            "SELECT COUNT(*) FROM products WHERE sentiment_scored_at IS NOT NULL",
        )
        log.info("Products with sentiment scores in DB: %d", done_count)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Batch sentiment extraction via Bedrock Haiku")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"Max products to score (default {DEFAULT_LIMIT})")
    args = parser.parse_args()
    asyncio.run(main(limit=args.limit))
