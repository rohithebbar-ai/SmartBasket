"""
Fashion Sentiment Worker — Day 18.5

Reads H&M products from Supabase where sentiment_scored_at IS NULL,
scores each product using real Amazon clothing reviews via Groq,
then writes structured sentiment scores + real customer quote excerpts back.

Run:
    python -m workers.sentiment.fashion_sentiment_worker
    python -m workers.sentiment.fashion_sentiment_worker --limit 50
    python -m workers.sentiment.fashion_sentiment_worker --limit 0   # all products
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import textwrap
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

# Bedrock Haiku 4.5: no free-tier daily cap, ~1-2s latency per call.
# Fire CONCURRENCY requests in parallel — each batch takes ~2s instead of 2s×N.
_CONCURRENCY = 5
_MAX_REVIEWS_PER_CALL = 15

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

log = logging.getLogger(__name__)

_DATABASE_URL: str = os.environ["DATABASE_URL"]

_FETCH_SQL = """
    SELECT id, name, category, description, attributes
    FROM   products
    WHERE  external_product_id IS NOT NULL
      AND  sentiment_scored_at IS NULL
    ORDER  BY last_ingested_at DESC
    LIMIT  $1
"""

_UPDATE_SQL = """
    UPDATE products SET
        style_sentiment       = $2,
        quality_sentiment     = $3,
        fit_sentiment         = $4,
        comfort_sentiment     = $5,
        versatility_sentiment = $6,
        delivery_sentiment    = $7,
        top_praise            = $8,
        top_complaint         = $9,
        sentiment_scored_at   = NOW()
    WHERE id = $1
"""

_SCORE_PROMPT = textwrap.dedent("""
You are a fashion e-commerce sentiment analyst.

Product details:
  Name:        {name}
  Category:    {category}
  Description: {description}

Real customer reviews for similar {category} products (sourced from Amazon):
{reviews_block}

Based on these real customer reviews, score the following sentiment aspects
for this product's category on a scale of 1.0 (very negative) to 5.0 (very positive):
  - style:       visual appeal, aesthetic, how it looks
  - quality:     materials, construction, durability
  - fit:         sizing accuracy, fit on the body
  - comfort:     wearability, softness, breathability
  - versatility: occasions it suits, ease of styling
  - delivery:    shipping speed, packaging (use 3.5 if reviews don't mention it)

Also pick ONE real verbatim quote that best represents a customer praising this
product type, and ONE real verbatim quote that best represents a complaint.
Keep quotes under 120 characters. Only pick from the reviews above.

Return ONLY valid JSON, no explanation:
{{
  "style_sentiment":       <float>,
  "quality_sentiment":     <float>,
  "fit_sentiment":         <float>,
  "comfort_sentiment":     <float>,
  "versatility_sentiment": <float>,
  "delivery_sentiment":    <float>,
  "top_praise":            "<verbatim customer quote>",
  "top_complaint":         "<verbatim customer quote>"
}}
""").strip()


def _make_dsn(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://").split("?")[0]


def _build_reviews_block(reviews: list[dict]) -> str:
    lines = []
    for i, r in enumerate(reviews, 1):
        stars = "★" * r["rating"] + "☆" * (5 - r["rating"])
        title = f'  Title: "{r["title"]}"' if r.get("title") else ""
        lines.append(f'[{i}] {stars}{title}\n    "{r["text"][:300]}"')
    return "\n\n".join(lines)


def _parse_scores(raw: str) -> dict | None:
    try:
        data = json.loads(raw)
        required = {
            "style_sentiment", "quality_sentiment", "fit_sentiment",
            "comfort_sentiment", "versatility_sentiment", "delivery_sentiment",
            "top_praise", "top_complaint",
        }
        if not required.issubset(data.keys()):
            return None
        # Clamp floats to [1.0, 5.0]
        for key in required - {"top_praise", "top_complaint"}:
            data[key] = max(1.0, min(5.0, float(data[key])))
        return data
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


async def _score_product_bedrock(
    bedrock_client,
    product: asyncpg.Record,
    reviews: list[dict],
) -> tuple[dict | None, None]:
    """Call Bedrock Haiku with real Amazon reviews. Returns (scores, None)."""
    import json as _json

    if not reviews:
        log.warning("No reviews for product %s (%s)", product["id"], product["category"])
        return None, None

    reviews_block = _build_reviews_block(reviews)
    prompt = _SCORE_PROMPT.format(
        name=product["name"],
        category=product["category"],
        description=(product["description"] or "No description available.")[:400],
        reviews_block=reviews_block,
    )

    for attempt in range(3):
        try:
            resp = await bedrock_client.messages.create(
                model=os.environ.get(
                    "BEDROCK_FAST_MODEL_ID",
                    "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
                ),
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            parsed = _parse_scores(raw)
            if parsed:
                return parsed, None
            log.warning("Bad JSON from Bedrock for %s: %.120s", product["name"], raw)
            return None, None

        except Exception as e:
            wait = 10 * (2 ** attempt)   # 10s, 20s, 40s
            log.warning("Bedrock error (attempt %d/3) for %s: %s — retrying in %ds", attempt + 1, product["name"], e, wait)
            await asyncio.sleep(wait)

    log.error("All 3 attempts exhausted for %s — skipping", product["name"])
    return None, None


async def run(limit: int = 100) -> None:
    import anthropic

    from workers.sentiment.amazon_connector import build_review_pool, get_reviews_for_category

    bedrock_client = anthropic.AsyncAnthropicBedrock(
        aws_region=os.environ.get("AWS_REGION", "eu-north-1"),
    )

    # ── 1. Build real Amazon review pool (streamed once, held in memory) ─────
    log.info("Building Amazon review pool…")
    review_pool = build_review_pool(total_limit=4000)

    # ── 2. Fetch unscored fashion products from Supabase ─────────────────────
    dsn = _make_dsn(_DATABASE_URL)
    # Use a pool — single connections time out after hours of 13s sleeps.
    # min_size=1 max_size=3, server keepalive every 60s.
    pool = await asyncpg.create_pool(
        dsn,
        min_size=1,
        max_size=_CONCURRENCY + 2,
        command_timeout=30,
        server_settings={"tcp_keepalives_idle": "60"},
    )

    async with pool.acquire() as conn:
        fetch_limit = limit if limit > 0 else 999_999
        rows = await conn.fetch(_FETCH_SQL, fetch_limit)

    log.info("Found %d unscored fashion products", len(rows))

    if not rows:
        log.info("Nothing to score — exiting.")
        await pool.close()
        return

    # ── 3. Score concurrently in chunks of _CONCURRENCY ──────────────────────
    scored = 0
    failed = 0
    total = len(rows)
    semaphore = asyncio.Semaphore(_CONCURRENCY)

    async def _score_one(product):
        category = product["category"] or "clothing"
        reviews = get_reviews_for_category(review_pool, category)[:_MAX_REVIEWS_PER_CALL]
        async with semaphore:
            return product, await _score_product_bedrock(bedrock_client, product, reviews)

    for batch_start in range(0, total, _CONCURRENCY):
        batch = rows[batch_start : batch_start + _CONCURRENCY]
        results = await asyncio.gather(*[_score_one(p) for p in batch], return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                failed += 1
                log.error("Unexpected error in batch: %s", result)
                continue

            product, (scores, _) = result
            if scores:
                async with pool.acquire() as conn:
                    await conn.execute(
                        _UPDATE_SQL,
                        product["id"],
                        scores["style_sentiment"],
                        scores["quality_sentiment"],
                        scores["fit_sentiment"],
                        scores["comfort_sentiment"],
                        scores["versatility_sentiment"],
                        scores["delivery_sentiment"],
                        scores["top_praise"],
                        scores["top_complaint"],
                    )
                scored += 1
            else:
                failed += 1

        done = batch_start + len(batch)
        log.info("[%d/%d] batch done — scored=%d failed=%d", done, total, scored, failed)

    await pool.close()
    log.info("Done — scored=%d failed=%d", scored, failed)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stdout,
    )

    parser = argparse.ArgumentParser(
        description="Score fashion product sentiment using real Amazon reviews via Groq"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Max products to score per run (0 = all, default 100)",
    )
    args = parser.parse_args()

    asyncio.run(run(limit=args.limit))


if __name__ == "__main__":
    main()
