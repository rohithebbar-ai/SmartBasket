"""Config-driven constraint extractor: NL query → typed ConstraintOutput."""
from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel

from app.llm import call_llm
from app.redis_client import get_redis_client
from app.search.catalogue_config import AttrDef, CatalogueConfig

log = logging.getLogger(__name__)

_RATES: dict[str, float] = {"USD": 1.0, "INR": 1 / 83, "EUR": 1.08, "GBP": 1.26}


class ConstraintOutput(BaseModel):
    rewritten_query: str
    max_price: float | None
    min_price: float | None
    hard_filters: dict[str, str | None]
    soft_attrs: dict[str, str | None]
    detected_currency: str
    occasion: str | None


def _convert_price(value: float, from_currency: str, to_currency: str) -> float:
    usd = value * _RATES.get(from_currency, 1.0)
    return usd / _RATES.get(to_currency, 1.0)


async def _load_attr_values(attrs: list[AttrDef]) -> dict[str, set[str]]:
    import asyncio

    redis = get_redis_client()

    async def safe_smembers(attr: AttrDef) -> tuple[str, set[str]]:
        try:
            members = await redis.smembers(attr.redis_values_key)
            return attr.key, set(members)
        except Exception:
            log.warning("Redis SMEMBERS failed for key=%s", attr.redis_values_key)
            return attr.key, set()

    try:
        pairs = await asyncio.gather(*[safe_smembers(a) for a in attrs])
    finally:
        await redis.aclose()

    return dict(pairs)


def _build_prompt(
    query: str,
    config: CatalogueConfig,
    attr_values: dict[str, set[str]],
) -> str:
    hard_attrs = [a for a in config.filterable_attrs if a.is_qdrant_filter]
    soft_attrs = [a for a in config.filterable_attrs if not a.is_qdrant_filter]

    filter_lines: list[str] = []
    for attr in config.filterable_attrs:
        values = attr_values.get(attr.key, set())
        value_hint = ", ".join(sorted(values)) if values else "any value"
        filter_lines.append(f"  - {attr.display_name} ({attr.key}): one of: {value_hint}")

    soft_lines = [f"  - {a.display_name} ({a.key})" for a in soft_attrs]

    hard_filter_json_fields = "\n  ".join(
        f'"{a.key}": "<value or null>",' for a in hard_attrs
    )
    soft_attr_json_fields = "\n  ".join(
        f'"{a.key}": "<value or null>",' for a in soft_attrs
    )

    return f"""You are a shopping assistant for {config.display_name}.
Extract structured filters from the user's query.

Available filters:
{chr(10).join(filter_lines)}

Price:
  Internal currency: {config.price_currency}
  If the user mentions a price, detect the currency (USD/INR/EUR/GBP) and extract the numeric value.

Soft context (do NOT filter, fold into rewritten_query):
{chr(10).join(soft_lines)}

Respond with JSON only:
{{
  "rewritten_query": "<expanded semantic query including soft context like occasion>",
  "price_value": <number or null>,
  "price_currency": "<USD|INR|EUR|GBP or null>",
  "price_type": "<max|min|exact or null>",
  {hard_filter_json_fields}
  {soft_attr_json_fields}
}}

Query: {query}"""


def _parse_price(
    raw: dict[str, Any],
    config: CatalogueConfig,
) -> tuple[float | None, float | None, str]:
    price_value: float | None = raw.get("price_value")
    price_currency: str | None = raw.get("price_currency")
    price_type: str | None = raw.get("price_type")

    if price_value is None or not price_currency:
        return None, None, "USD"

    detected_currency = price_currency.upper()
    converted = _convert_price(price_value, detected_currency, config.price_currency)

    max_price: float | None = None
    min_price: float | None = None

    if price_type in ("max", "exact"):
        max_price = converted
    if price_type == "min":
        min_price = converted

    return max_price, min_price, detected_currency


def _build_fallback(config: CatalogueConfig, query: str) -> ConstraintOutput:
    hard_attrs = [a for a in config.filterable_attrs if a.is_qdrant_filter]
    soft_attrs = [a for a in config.filterable_attrs if not a.is_qdrant_filter]
    return ConstraintOutput(
        rewritten_query=query,
        max_price=None,
        min_price=None,
        hard_filters={a.key: None for a in hard_attrs},
        soft_attrs={a.key: None for a in soft_attrs},
        detected_currency="USD",
        occasion=None,
    )


async def extract_constraints(query: str, config: CatalogueConfig) -> ConstraintOutput:
    attr_values = await _load_attr_values(config.filterable_attrs)
    prompt = _build_prompt(query, config, attr_values)

    raw_response = await call_llm(prompt, tier="fast", max_tokens=400)

    try:
        raw: dict[str, Any] = json.loads(raw_response)
    except (json.JSONDecodeError, ValueError):
        log.warning("constraint_extractor: LLM returned invalid JSON; returning empty filters")
        return _build_fallback(config, query)

    hard_attrs = [a for a in config.filterable_attrs if a.is_qdrant_filter]
    soft_attrs = [a for a in config.filterable_attrs if not a.is_qdrant_filter]

    hard_filters = {a.key: raw.get(a.key) or None for a in hard_attrs}
    soft_attr_values = {a.key: raw.get(a.key) or None for a in soft_attrs}

    max_price, min_price, detected_currency = _parse_price(raw, config)

    return ConstraintOutput(
        rewritten_query=raw.get("rewritten_query") or query,
        max_price=max_price,
        min_price=min_price,
        hard_filters=hard_filters,
        soft_attrs=soft_attr_values,
        detected_currency=detected_currency,
        occasion=soft_attr_values.get("occasion"),
    )
