"""Integration tests for constraint_extractor.py — requires LLM_PROVIDER=bedrock."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable
from unittest.mock import AsyncMock, patch

import pytest

from app.config import LLMProvider, settings
from app.search.catalogue_config import ELECTRONICS_CATALOGUE, FASHION_CATALOGUE
from app.search.constraint_extractor import ConstraintOutput, extract_constraints

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        settings.llm_provider != LLMProvider.BEDROCK,
        reason="Integration tests require LLM_PROVIDER=bedrock",
    ),
]


# ── Mock Redis fixture ────────────────────────────────────────────────────────

_FASHION_VALUES = {
    "attrs:fashion:colour":        {"Black", "White", "Blue", "Red", "Pink", "Green", "Yellow", "Navy", "Beige", "Brown"},
    "attrs:fashion:pattern":       {"Solid", "Floral", "Striped", "Checked", "Plain", "Printed"},
    "attrs:fashion:category":      {"Dress", "Jacket", "Coat", "Top", "Jeans", "Skirt", "Hoodie", "T-shirt", "Trousers", "Blouse"},
    "attrs:fashion:garment_group": {"Dresses", "Tops", "Jackets & Coats", "Trousers", "Skirts"},
    "attrs:fashion:section":       {"Ladies", "Divided", "H&M+"},
    "attrs:fashion:occasion":      set(),  # empty — occasion is soft/inferred
    "attrs:electronics:brand":     {"Apple", "Dell", "Lenovo", "ASUS", "HP", "Samsung", "MSI", "Acer"},
    "attrs:electronics:category":  {"Laptop", "Ultrabook", "Gaming Laptop", "Chromebook"},
    "attrs:electronics:ram":       {"8GB", "16GB", "32GB", "64GB"},
    "attrs:electronics:use_case":  {"gaming", "video editing", "programming", "business", "travel"},
}


@pytest.fixture(autouse=True)
def mock_redis_attrs():
    """Patch Redis so extractor gets realistic attribute values without a live Redis."""

    async def fake_smembers(key):
        return _FASHION_VALUES.get(key, set())

    mock_r = AsyncMock()
    mock_r.smembers = AsyncMock(side_effect=fake_smembers)
    mock_r.aclose = AsyncMock()

    with patch("app.search.constraint_extractor.get_redis_client", return_value=mock_r):
        yield


# ── Case dataclass ────────────────────────────────────────────────────────────

@dataclass
class Case:
    query: str
    catalogue: str
    checks: list[tuple[str, Callable[[ConstraintOutput], bool]]] = field(default_factory=list)


# ── Fashion cases (10) ────────────────────────────────────────────────────────

FASHION_CASES: list[Case] = [
    Case(
        query="beach wedding, not too formal, under $40",
        catalogue="fashion",
        checks=[
            ("max_price ≤ 40", lambda o: o.max_price is not None and o.max_price <= 40),
            ("rewritten_query references wedding/beach/occasion", lambda o: any(
                kw in o.rewritten_query.lower() for kw in ("wedding", "beach", "occasion", "formal")
            )),
        ],
    ),
    Case(
        query="show me black floral dresses",
        catalogue="fashion",
        checks=[
            ("hard_filters colour == Black", lambda o: o.hard_filters.get("colour", "").lower() == "black"),
            ("hard_filters pattern is Floral", lambda o: (o.hard_filters.get("pattern") or "").lower() == "floral"),
            ("rewritten_query non-empty", lambda o: bool(o.rewritten_query.strip())),
        ],
    ),
    Case(
        query="something cosy for winter, under $50",
        catalogue="fashion",
        checks=[
            ("max_price ≤ 50", lambda o: o.max_price is not None and o.max_price <= 50),
            ("rewritten_query mentions warm/cosy/winter", lambda o: any(
                kw in o.rewritten_query.lower() for kw in ("warm", "cosy", "cozy", "winter")
            )),
        ],
    ),
    Case(
        query="date night outfit, not too expensive",
        catalogue="fashion",
        checks=[
            ("occasion present in soft_attrs", lambda o: o.soft_attrs.get("occasion") is not None or o.occasion is not None),
            ("rewritten_query non-empty", lambda o: bool(o.rewritten_query.strip())),
        ],
    ),
    Case(
        query="red dress for a party",
        catalogue="fashion",
        checks=[
            ("red colour captured in filters or rewritten_query", lambda o: (
                (o.hard_filters.get("colour") or "").lower() == "red"
                or "red" in o.rewritten_query.lower()
            )),
        ],
    ),
    Case(
        query="office smart casual under $35",
        catalogue="fashion",
        checks=[
            ("max_price ≤ 35", lambda o: o.max_price is not None and o.max_price <= 35),
        ],
    ),
    Case(
        # ₹3000 ≈ $36 at ~83 INR/USD
        query="₹3000 budget, floral top",
        catalogue="fashion",
        checks=[
            ("max_price captured and ≤ 50 (₹3000 ≈ $36)", lambda o: o.max_price is not None and o.max_price <= 50),
        ],
    ),
    Case(
        query="show me something in navy blue stripes",
        catalogue="fashion",
        checks=[
            ("navy captured in colour filter or rewritten_query", lambda o: (
                "navy" in (o.hard_filters.get("colour") or "").lower()
                or "navy" in o.rewritten_query.lower()
            )),
        ],
    ),
    Case(
        query="gift for teenage girl, around $25",
        catalogue="fashion",
        checks=[
            ("max_price captured and ≤ 30", lambda o: o.max_price is not None and o.max_price <= 30),
        ],
    ),
    Case(
        query="white summer dress",
        catalogue="fashion",
        checks=[
            ("rewritten_query non-empty", lambda o: bool(o.rewritten_query.strip())),
            ("white captured somewhere in output", lambda o: (
                "white" in str(o.hard_filters).lower()
                or "white" in o.rewritten_query.lower()
            )),
        ],
    ),
]


# ── Electronics cases (10) ────────────────────────────────────────────────────

ELECTRONICS_CASES: list[Case] = [
    Case(
        query="gaming laptop 32GB RAM under $1200",
        catalogue="electronics",
        checks=[
            ("max_price ≤ 1200", lambda o: o.max_price is not None and o.max_price <= 1200),
            ("hard_filters ram == 32GB", lambda o: o.hard_filters.get("ram") == "32GB"),
        ],
    ),
    Case(
        query="MacBook alternative for developers under $1500",
        catalogue="electronics",
        checks=[
            ("max_price ≤ 1500", lambda o: o.max_price is not None and o.max_price <= 1500),
            ("rewritten_query mentions developer/programming", lambda o: any(
                kw in o.rewritten_query.lower() for kw in ("developer", "programming", "develop", "code", "coding")
            )),
        ],
    ),
    Case(
        query="lightweight laptop for travel, under $800",
        catalogue="electronics",
        checks=[
            ("max_price ≤ 800", lambda o: o.max_price is not None and o.max_price <= 800),
        ],
    ),
    Case(
        query="best laptop for video editing, 16GB RAM",
        catalogue="electronics",
        checks=[
            ("hard_filters ram == 16GB", lambda o: o.hard_filters.get("ram") == "16GB"),
            ("rewritten_query mentions video/editing", lambda o: any(
                kw in o.rewritten_query.lower() for kw in ("video", "editing", "edit")
            )),
        ],
    ),
    Case(
        # ₹80000 ≈ $964 at ~83 INR/USD
        query="₹80000 budget, good laptop for students",
        catalogue="electronics",
        checks=[
            ("max_price captured and ≤ 1100 (₹80000 ≈ $964)", lambda o: o.max_price is not None and o.max_price <= 1100),
        ],
    ),
    Case(
        query="ASUS gaming laptop under $1200",
        catalogue="electronics",
        checks=[
            ("ASUS captured in brand filter or rewritten_query", lambda o: (
                (o.hard_filters.get("brand") or "").lower() == "asus"
                or "asus" in o.rewritten_query.lower()
            )),
            ("max_price ≤ 1200", lambda o: o.max_price is not None and o.max_price <= 1200),
        ],
    ),
    Case(
        query="show me Dell laptops",
        catalogue="electronics",
        checks=[
            ("hard_filters brand == Dell", lambda o: o.hard_filters.get("brand") == "Dell"),
        ],
    ),
    Case(
        query="laptop for machine learning, 32GB RAM",
        catalogue="electronics",
        checks=[
            ("hard_filters ram == 32GB", lambda o: o.hard_filters.get("ram") == "32GB"),
        ],
    ),
    Case(
        query="ultrabook under $600 for business travel",
        catalogue="electronics",
        checks=[
            ("max_price ≤ 600", lambda o: o.max_price is not None and o.max_price <= 600),
        ],
    ),
    Case(
        query="budget laptop under $500",
        catalogue="electronics",
        checks=[
            ("max_price ≤ 500", lambda o: o.max_price is not None and o.max_price <= 500),
        ],
    ),
]


ALL_CASES: list[Case] = FASHION_CASES + ELECTRONICS_CASES


# ── Accuracy test ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_constraint_extractor_accuracy():
    results = []
    for case in ALL_CASES:
        config = FASHION_CATALOGUE if case.catalogue == "fashion" else ELECTRONICS_CATALOGUE
        output = await extract_constraints(case.query, config)

        case_passed = True
        failures = []
        for desc, check in case.checks:
            if not check(output):
                case_passed = False
                failures.append(desc)

        results.append((case, output, case_passed, failures))

    passed = sum(1 for _, _, ok, _ in results if ok)
    print(f"\n{'='*70}")
    print(f"CONSTRAINT EXTRACTOR — {passed}/{len(results)} cases passed")
    print(f"{'='*70}")
    for case, output, ok, failures in results:
        mark = "✓" if ok else "✗"
        print(f"\n  {mark} [{case.catalogue}] {case.query!r}")
        print(f"     rewritten_query: {output.rewritten_query!r}")
        print(f"     max_price={output.max_price}  min_price={output.min_price}  currency={output.detected_currency}")
        print(f"     hard_filters={output.hard_filters}")
        print(f"     soft_attrs={output.soft_attrs}")
        if not ok:
            for f in failures:
                print(f"     ✗ FAILED: {f}")
    print(f"\n{'='*70}\n")

    assert passed >= int(len(ALL_CASES) * 0.75), (
        f"Constraint extractor: {passed}/{len(ALL_CASES)} passed (threshold 75%). "
        "See breakdown above."
    )


# ── Per-case parametrized tests ───────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("case", ALL_CASES, ids=lambda c: f"[{c.catalogue}] {c.query[:50]}")
async def test_individual_case(case: Case):
    config = FASHION_CATALOGUE if case.catalogue == "fashion" else ELECTRONICS_CATALOGUE
    output = await extract_constraints(case.query, config)

    failures = [desc for desc, check in case.checks if not check(output)]
    assert not failures, (
        f"Case failed: {case.query!r}\n"
        f"  Failures: {failures}\n"
        f"  Output: rewritten={output.rewritten_query!r}, max_price={output.max_price}, "
        f"hard_filters={output.hard_filters}, soft_attrs={output.soft_attrs}"
    )
