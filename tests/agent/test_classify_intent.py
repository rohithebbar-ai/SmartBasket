"""
Intent classifier quality gate — 20 real Bedrock Haiku calls, 2 per intent.

Cases are chosen to probe genuine understanding, not keyword matching:
  - Colloquial / indirect phrasing ("I'll take it" → PURCHASE_INTENT)
  - Overlapping signals ("best Dell vs HP" — COMPARE not PRODUCT_SEARCH)
  - Tone variations ("can you explain" → EXPLAIN, not PRODUCT_SEARCH)
  - Admin phrasing that sounds like product search ("show revenue") → ADMIN_ACTION

Threshold: 18 / 20 (90%). If below threshold the INTENT_CLASSIFIER_PROMPT
needs work — do not proceed to Day 13 until this passes.

Run:
    pytest tests/agent/test_classify_intent.py -v -s
"""

from dataclasses import dataclass
from typing import Literal

import pytest

from app.config import settings

IntentLabel = Literal[
    "PRODUCT_SEARCH",
    "COMPARE",
    "EXPLAIN",
    "PURCHASE_INTENT",
    "CHECKOUT",
    "ORDER_STATUS",
    "POST_PURCHASE",
    "WISHLIST_ACTION",
    "ADMIN_ACTION",
    "OUT_OF_SCOPE",
]

ACCURACY_THRESHOLD = 0.90  # 18 / 20


@dataclass
class Case:
    message: str
    expected: IntentLabel
    note: str = ""


# 2 cases per intent, designed to stress colloquial / indirect phrasing.
CASES: list[Case] = [
    # ── PRODUCT_SEARCH ───────────────────────────────────────────────────────
    Case(
        "what laptops do you have for college students",
        "PRODUCT_SEARCH",
        "classic discovery — open-ended, no specific product named",
    ),
    Case(
        "something fast and lightweight for travel",
        "PRODUCT_SEARCH",
        "vague colloquial search — no brand, no price constraint",
    ),

    # ── COMPARE ──────────────────────────────────────────────────────────────
    Case(
        "which is better — the Dell XPS 15 or the MacBook Pro 14",
        "COMPARE",
        "explicit side-by-side with two named products",
    ),
    Case(
        "help me decide between ASUS ZenBook and Lenovo ThinkPad X1",
        "COMPARE",
        "'help me decide between' = comparison intent",
    ),

    # ── EXPLAIN ──────────────────────────────────────────────────────────────
    Case(
        "can you explain what OLED means for everyday use",
        "EXPLAIN",
        "feature explanation — not a product search",
    ),
    Case(
        "why is NVMe SSD so much faster than a regular hard drive",
        "EXPLAIN",
        "technical 'why' question — educational intent",
    ),

    # ── PURCHASE_INTENT ───────────────────────────────────────────────────────
    Case(
        "I'll take it",
        "PURCHASE_INTENT",
        "minimal colloquial — 'it' refers to a product shown earlier",
    ),
    Case(
        "add the HP Spectre x360 to my cart please",
        "PURCHASE_INTENT",
        "explicit add-to-cart request with product name",
    ),

    # ── CHECKOUT ─────────────────────────────────────────────────────────────
    Case(
        "let's go ahead and place the order",
        "CHECKOUT",
        "'place the order' = completing a transaction",
    ),
    Case(
        "show me my cart and confirm everything looks right",
        "CHECKOUT",
        "cart review before payment — completing the flow",
    ),

    # ── ORDER_STATUS ─────────────────────────────────────────────────────────
    Case(
        "where is my package, it was supposed to arrive yesterday",
        "ORDER_STATUS",
        "delivery tracking — no order number but clearly about shipment",
    ),
    Case(
        "has my laptop shipped yet? I ordered three days ago",
        "ORDER_STATUS",
        "shipping status with time reference",
    ),

    # ── POST_PURCHASE ─────────────────────────────────────────────────────────
    Case(
        "I want to return the laptop I bought last week",
        "POST_PURCHASE",
        "return request after delivery — post-purchase flow",
    ),
    Case(
        "the screen on my new laptop is flickering, how do I get a refund",
        "POST_PURCHASE",
        "defect + refund request — clearly post-purchase",
    ),

    # ── WISHLIST_ACTION ───────────────────────────────────────────────────────
    Case(
        "save the Dell XPS 15 for me, I might buy it next month",
        "WISHLIST_ACTION",
        "'save for later' with a future-purchase signal",
    ),
    Case(
        "add this to my saved items",
        "WISHLIST_ACTION",
        "minimal phrasing — 'saved items' = wishlist",
    ),

    # ── ADMIN_ACTION ──────────────────────────────────────────────────────────
    Case(
        "show me the revenue breakdown by brand for this month",
        "ADMIN_ACTION",
        "business analytics — revenue aggregation, not product search",
    ),
    Case(
        "which products have the lowest stock levels right now",
        "ADMIN_ACTION",
        "inventory management query — admin analytics, not product discovery",
    ),

    # ── OUT_OF_SCOPE ──────────────────────────────────────────────────────────
    Case(
        "what's the weather like in Bangalore today",
        "OUT_OF_SCOPE",
        "completely unrelated to electronics / shopping",
    ),
    Case(
        "write me a short poem about mountains",
        "OUT_OF_SCOPE",
        "creative writing request — zero shopping relevance",
    ),
]


# ── Test harness ──────────────────────────────────────────────────────────────

async def _run_case(case: Case) -> str:
    from app.agent.nodes.classify_intent import classify_intent

    state = {
        "messages": [{"role": "user", "content": case.message}],
        "session_id": "test-intent",
        "user_id": "",
    }
    result = await classify_intent(state)
    return result.get("intent", "PRODUCT_SEARCH")


@pytest.mark.asyncio
@pytest.mark.skipif(
    settings.llm_provider.value != "bedrock",
    reason=(
        "Intent quality gate requires Bedrock Claude Haiku — "
        f"current provider is '{settings.llm_provider.value}'. "
        "Set LLM_PROVIDER=bedrock and re-run to validate."
    ),
)
async def test_intent_classifier_accuracy():
    """
    Runs all 20 cases against live Bedrock Haiku and asserts >= 90% accuracy.
    Prints a full breakdown by intent so failures are easy to diagnose.

    Skipped when LLM_PROVIDER != bedrock because smaller models collapse
    subtle intents (CHECKOUT vs PURCHASE_INTENT, ADMIN_ACTION vs PRODUCT_SEARCH).
    """
    results: list[tuple[Case, str, bool]] = []

    for case in CASES:
        try:
            got = await _run_case(case)
        except Exception as exc:
            got = f"ERROR({exc})"
        correct = got == case.expected
        results.append((case, got, correct))

    correct_count = sum(1 for _, _, ok in results if ok)
    total = len(results)
    accuracy = correct_count / total

    # Group by expected intent for readable output
    by_intent: dict[str, list] = {
        "PRODUCT_SEARCH": [], "COMPARE": [], "EXPLAIN": [],
        "PURCHASE_INTENT": [], "CHECKOUT": [], "ORDER_STATUS": [],
        "POST_PURCHASE": [], "WISHLIST_ACTION": [], "ADMIN_ACTION": [],
        "OUT_OF_SCOPE": [],
    }
    for row in results:
        by_intent[row[0].expected].append(row)

    print(f"\n{'='*72}")
    print(f"INTENT CLASSIFIER QUALITY GATE ({correct_count}/{total} correct, {accuracy:.0%})")
    print(f"{'='*72}")

    for intent, rows in by_intent.items():
        intent_correct = sum(1 for _, _, ok in rows if ok)
        print(f"\n  {intent} ({intent_correct}/{len(rows)})")
        for case, got, ok in rows:
            mark = "✓" if ok else "✗"
            mismatch = f"  → got {got}" if not ok else ""
            note = f"  [{case.note}]" if case.note and not ok else ""
            print(f"    {mark}  {case.message!r}{mismatch}{note}")

    print(f"\n  Accuracy: {accuracy:.0%}  (threshold: {ACCURACY_THRESHOLD:.0%})")
    print(f"{'='*72}\n")

    assert accuracy >= ACCURACY_THRESHOLD, (
        f"Intent classifier accuracy {accuracy:.0%} is below the {ACCURACY_THRESHOLD:.0%} "
        f"threshold ({correct_count}/{total}). "
        "Fix INTENT_CLASSIFIER_PROMPT before proceeding to Day 13."
    )
