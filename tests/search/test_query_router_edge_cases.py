"""
Edge-case golden set for the query router — 30 real Bedrock Haiku calls, 10 per type.

None of these queries appear in the prompt examples or the original golden set.
They are designed to stress the model's understanding of the SEMANTIC /
ANALYTICAL / HYBRID distinction, not its ability to pattern-match on the
exact phrasing it was shown.

Failure categories being probed:
  SEMANTIC  — vague / colloquial / profession-based / sounds-analytical-but-isn't
  ANALYTICAL — aggregation that looks like discovery, multi-brand comparison
  HYBRID    — "top N" with price (looks ANALYTICAL), brand + use case + price

Run with:
    pytest tests/search/test_query_router_edge_cases.py -v -s
"""

from dataclasses import dataclass
from typing import Literal

import pytest

QueryType = Literal["SEMANTIC", "ANALYTICAL", "HYBRID"]

ACCURACY_THRESHOLD = 0.85  # 26 / 30


@dataclass
class Case:
    query: str
    expected: QueryType
    note: str = ""  # explains the trap / why this is hard


EDGE_CASES: list[Case] = [
    # ── SEMANTIC (10) ──────────────────────────────────────────────────────────
    # These look like they might need structure but are pure discovery queries.

    Case("show me something like the MacBook Pro",
         "SEMANTIC", "comparison phrasing but it's still exploration"),
    Case("i need a laptop for my kid",
         "SEMANTIC", "colloquial — no price or brand constraint"),
    Case("how good is the Dell XPS 15",
         "SEMANTIC", "'how good' sounds analytical but it's a product question"),
    Case("laptop that won't slow down after a year",
         "SEMANTIC", "durability / longevity — no structured filter"),
    Case("something my parents can use easily",
         "SEMANTIC", "very colloquial, user type — no constraints"),
    Case("laptop for machine learning and AI work",
         "SEMANTIC", "technical use case — no price or brand filter"),
    Case("gaming laptop that's not too loud",
         "SEMANTIC", "specific feature but still discovery"),
    Case("laptop that handles many browser tabs without freezing",
         "SEMANTIC", "performance use case — no structured constraint"),
    Case("suggest a laptop for an architect",
         "SEMANTIC", "profession-based — semantic only"),
    Case("what is a good laptop for everyday home use",
         "SEMANTIC", "'what is' phrasing — still exploratory"),

    # ── ANALYTICAL (10) ────────────────────────────────────────────────────────
    # These need SQL aggregation. Some have brand/category context that might
    # fool the model into thinking SQL+vector is needed.

    Case("compare the average ratings of Dell and ASUS",
         "ANALYTICAL", "group-by aggregation, no discovery needed"),
    Case("how many products cost more than 100000",
         "ANALYTICAL", "count with price threshold"),
    Case("rank all brands by their average price",
         "ANALYTICAL", "ranking aggregation — pure SQL"),
    Case("show me products sorted by rating from highest to lowest",
         "ANALYTICAL", "sorting/listing — no semantic meaning needed"),
    Case("what is the price range of gaming laptops in the catalogue",
         "ANALYTICAL", "MIN/MAX aggregation — 'gaming' is a category tag not a meaning query"),
    Case("how many Dell laptops are currently in stock",
         "ANALYTICAL", "count with brand + stock filter"),
    Case("which laptop saw the biggest price drop recently",
         "ANALYTICAL", "time-series price comparison — needs price_history table"),
    Case("what brands have more than 10 products listed",
         "ANALYTICAL", "group-by count with having clause"),
    Case("show the top 5 most reviewed products",
         "ANALYTICAL", "count + sort — no semantic understanding needed"),
    Case("what is the lowest rated laptop in the catalogue",
         "ANALYTICAL", "MIN aggregation — not a discovery query"),

    # ── HYBRID (10) ────────────────────────────────────────────────────────────
    # Each has at least one semantic dimension (use case, quality signal, feature)
    # AND at least one hard filter (price, brand, stock).

    Case("out of stock Dell gaming laptops under 100000",
         "HYBRID", "stock filter + brand filter + semantic category"),
    Case("top 3 laptops under 1000 dollars with good build quality",
         "HYBRID", "price filter + semantic quality signal — 'top 3' is not pure SQL"),
    Case("which Dell laptop should I buy for under 80000",
         "HYBRID", "'which should I buy' = discovery intent + price constraint"),
    Case("best laptop for developers that costs less than 60000",
         "HYBRID", "use-case semantic + hard price ceiling"),
    Case("most popular gaming laptop under 1500 dollars",
         "HYBRID", "'gaming' needs semantic, price needs SQL"),
    Case("well reviewed thin and light laptop under 800 dollars",
         "HYBRID", "form factor is semantic + price is SQL"),
    Case("best value laptop for video editing under 1200 dollars",
         "HYBRID", "use case + 'best value' sentiment + price"),
    Case("ASUS laptop good for design work and under 150000",
         "HYBRID", "brand filter + use-case semantic"),
    Case("in stock laptop with good keyboard for writers under 70000",
         "HYBRID", "stock + feature sentiment + price — three constraints"),
    Case("highly rated laptop for students that ships under 50000",
         "HYBRID", "rating signal + use case + price filter"),
]


# ── Test harness ──────────────────────────────────────────────────────────────

async def _classify(query: str) -> str:
    from app.search.query_router import classify_query
    result = await classify_query(query)
    return result.type


@pytest.mark.asyncio
async def test_edge_case_accuracy():
    """
    Runs all 30 edge-case queries against live Bedrock Haiku.
    Asserts >= 85% accuracy and prints a full breakdown.
    """
    results: list[tuple[Case, str, bool]] = []

    for case in EDGE_CASES:
        try:
            got = await _classify(case.query)
        except Exception as exc:
            got = f"ERROR({exc})"
        correct = got == case.expected
        results.append((case, got, correct))

    correct_count = sum(1 for _, _, ok in results if ok)
    total = len(results)
    accuracy = correct_count / total

    print(f"\n{'='*72}")
    print(f"EDGE-CASE GOLDEN SET ({correct_count}/{total} correct, {accuracy:.0%})")
    print(f"{'='*72}")

    by_type: dict[str, list] = {"SEMANTIC": [], "ANALYTICAL": [], "HYBRID": []}
    for row in results:
        by_type[row[0].expected].append(row)

    for qtype, rows in by_type.items():
        type_correct = sum(1 for _, _, ok in rows if ok)
        print(f"\n  {qtype} ({type_correct}/{len(rows)})")
        for case, got, ok in rows:
            mark = "✓" if ok else "✗"
            mismatch = f"  → got {got}" if not ok else ""
            note = f"  [{case.note}]" if case.note and not ok else ""
            print(f"    {mark}  {case.query!r}{mismatch}{note}")

    print(f"\n  Accuracy: {accuracy:.0%}  (threshold: {ACCURACY_THRESHOLD:.0%})")
    print(f"{'='*72}\n")

    assert accuracy >= ACCURACY_THRESHOLD, (
        f"Edge-case accuracy {accuracy:.0%} below {ACCURACY_THRESHOLD:.0%} threshold "
        f"({correct_count}/{total}). See breakdown above — fix the prompt and re-run."
    )
