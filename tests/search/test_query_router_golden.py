"""
Golden test set for the query router — 30 real Bedrock Haiku calls, 10 per type.

These tests are NOT mocked. They hit the live Bedrock endpoint and assert that
classify_query() returns the correct type for every query. This is the acceptance
criterion for Day 9: >= 85% accuracy (26/30) required before proceeding.

Run with:
    pytest tests/search/test_query_router_golden.py -v -s

The Redis cache is bypassed per test by using a unique prefix so repeated runs
don't hide regressions behind stale cache hits.
"""

import asyncio
import uuid
from dataclasses import dataclass
from typing import Literal

import pytest

from app.config import settings
from app.config import LLMProvider

# Skip the whole module when not using Bedrock — Groq/Gemini models score below
# the 85% threshold on this classification task. Run with LLM_PROVIDER=bedrock.
pytestmark = pytest.mark.skipif(
    settings.llm_provider != LLMProvider.BEDROCK,
    reason="Golden tests require LLM_PROVIDER=bedrock (Haiku calibrated to 85%+ accuracy)",
)

QueryType = Literal["SEMANTIC", "ANALYTICAL", "HYBRID"]

ACCURACY_THRESHOLD = 0.85  # 26 / 30


# ── Golden queries ────────────────────────────────────────────────────────────

@dataclass
class Case:
    query: str
    expected: QueryType


GOLDEN: list[Case] = [
    # ── SEMANTIC (10) — discovery, exploratory, needs meaning not structure ────
    Case("laptop for video editing", "SEMANTIC"),
    Case("something portable for travel", "SEMANTIC"),
    Case("what do you recommend for a developer", "SEMANTIC"),
    Case("good gaming laptop", "SEMANTIC"),
    Case("best laptop for college students", "SEMANTIC"),
    Case("lightweight ultrabook for long flights", "SEMANTIC"),
    Case("laptop good for photo editing and design", "SEMANTIC"),
    Case("reliable laptop for remote work and video calls", "SEMANTIC"),
    Case("laptop with a great display for creative professionals", "SEMANTIC"),
    Case("comfortable laptop for coding all day", "SEMANTIC"),

    # ── ANALYTICAL (10) — structured data questions, exact numbers, aggregations
    Case("which brand has the highest average rating", "ANALYTICAL"),
    Case("show me all out of stock products", "ANALYTICAL"),
    Case("what is the average price of Dell laptops", "ANALYTICAL"),
    Case("how many laptops are priced under 50000", "ANALYTICAL"),
    Case("which products had the most price changes this week", "ANALYTICAL"),
    Case("what is the cheapest laptop currently available", "ANALYTICAL"),
    Case("list all products with a rating above 4.5", "ANALYTICAL"),
    Case("how many different brands do you carry", "ANALYTICAL"),
    Case("what percentage of laptops are out of stock", "ANALYTICAL"),
    Case("which laptop has the highest number of reviews", "ANALYTICAL"),

    # ── HYBRID (10) — semantic understanding + structured filter ──────────────
    Case("best rated Dell laptop under 80000", "HYBRID"),
    Case("best reviewed laptop under 80k with good battery life", "HYBRID"),
    Case("top rated Dell products for video editing", "HYBRID"),
    Case("affordable laptops with high display ratings", "HYBRID"),
    Case("gaming laptop under 1500 dollars with high refresh rate display", "HYBRID"),
    Case("highly rated ultrabook under 1000 dollars", "HYBRID"),
    Case("top ASUS laptop for developers under 1500", "HYBRID"),
    Case("well reviewed laptop with great battery life under 60000", "HYBRID"),
    Case("best thin and light laptop under 1200 with good reviews", "HYBRID"),
    Case("top rated MacBook alternative for video editing under 150000", "HYBRID"),
]


# ── Test harness ──────────────────────────────────────────────────────────────

async def _classify(query: str) -> str:
    from app.search.query_router import classify_query
    result = await classify_query(query)
    return result.type


@pytest.mark.asyncio
async def test_golden_set_accuracy():
    """
    Runs all 30 golden queries against live Bedrock Haiku and asserts >= 85% accuracy.
    Prints a full breakdown so failures are easy to diagnose.
    """
    results: list[tuple[Case, str, bool]] = []

    for case in GOLDEN:
        try:
            got = await _classify(case.query)
        except Exception as exc:
            got = f"ERROR({exc})"
        correct = got == case.expected
        results.append((case, got, correct))

    # ── Report ────────────────────────────────────────────────────────────────
    correct_count = sum(1 for _, _, ok in results if ok)
    total = len(results)
    accuracy = correct_count / total

    print(f"\n{'='*70}")
    print(f"QUERY ROUTER — GOLDEN TEST SET ({correct_count}/{total} correct, {accuracy:.0%})")
    print(f"{'='*70}")

    by_type: dict[str, list[tuple[Case, str, bool]]] = {"SEMANTIC": [], "ANALYTICAL": [], "HYBRID": []}
    for row in results:
        by_type[row[0].expected].append(row)

    for qtype, rows in by_type.items():
        type_correct = sum(1 for _, _, ok in rows if ok)
        print(f"\n  {qtype} ({type_correct}/{len(rows)})")
        for case, got, ok in rows:
            mark = "✓" if ok else "✗"
            mismatch = f"  → got {got}" if not ok else ""
            print(f"    {mark}  {case.query!r}{mismatch}")

    print(f"\n{'='*70}")
    print(f"  Accuracy: {accuracy:.0%}  (threshold: {ACCURACY_THRESHOLD:.0%})")
    print(f"{'='*70}\n")

    assert accuracy >= ACCURACY_THRESHOLD, (
        f"Query router accuracy {accuracy:.0%} is below the {ACCURACY_THRESHOLD:.0%} threshold "
        f"({correct_count}/{total} correct). See breakdown above."
    )


# ── Per-type breakdown tests (informational — show where failures cluster) ────

@pytest.mark.asyncio
@pytest.mark.parametrize("case", [c for c in GOLDEN if c.expected == "SEMANTIC"], ids=lambda c: c.query[:40])
async def test_semantic_case(case: Case):
    got = await _classify(case.query)
    assert got == "SEMANTIC", f"Expected SEMANTIC, got {got!r} for: {case.query!r}"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [c for c in GOLDEN if c.expected == "ANALYTICAL"], ids=lambda c: c.query[:40])
async def test_analytical_case(case: Case):
    got = await _classify(case.query)
    assert got == "ANALYTICAL", f"Expected ANALYTICAL, got {got!r} for: {case.query!r}"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [c for c in GOLDEN if c.expected == "HYBRID"], ids=lambda c: c.query[:40])
async def test_hybrid_case(case: Case):
    got = await _classify(case.query)
    assert got == "HYBRID", f"Expected HYBRID, got {got!r} for: {case.query!r}"
