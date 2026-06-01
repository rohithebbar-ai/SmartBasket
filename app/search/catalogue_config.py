"""Config-driven catalogue definitions; everything in the search layer imports from here."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException


@dataclass
class AttrDef:
    key: str
    display_name: str
    type: Literal["keyword", "range", "bool"]
    is_qdrant_filter: bool
    redis_values_key: str


@dataclass
class CatalogueConfig:
    client_id: str
    display_name: str
    qdrant_collection: str
    filterable_attrs: list[AttrDef]
    price_field_name: str
    price_currency: str
    sentiment_fields: list[str]
    schema_hint: str
    routing_examples: list[tuple[str, str]]
    embedding_fields: list[str]
    # Domain-specific tips injected into SYNTHESIS_PROMPT. All domain knowledge lives here.
    synthesis_domain_tips: str = ""


FASHION_CATALOGUE = CatalogueConfig(
    client_id="fashion",
    display_name="H&M Fashion",
    qdrant_collection="hm_products",
    price_field_name="current_price",
    price_currency="USD",
    sentiment_fields=[
        "style_sentiment",
        "quality_sentiment",
        "fit_sentiment",
        "comfort_sentiment",
        "versatility_sentiment",
        "delivery_sentiment",
    ],
    embedding_fields=["name", "description", "category", "attributes"],
    filterable_attrs=[
        AttrDef(
            key="colour",
            display_name="Colour",
            type="keyword",
            is_qdrant_filter=True,
            redis_values_key="attrs:fashion:colour",
        ),
        AttrDef(
            key="pattern",
            display_name="Pattern",
            type="keyword",
            is_qdrant_filter=True,
            redis_values_key="attrs:fashion:pattern",
        ),
        AttrDef(
            key="category",
            display_name="Category",
            type="keyword",
            is_qdrant_filter=True,
            redis_values_key="attrs:fashion:category",
        ),
        AttrDef(
            key="garment_group",
            display_name="Garment Group",
            type="keyword",
            is_qdrant_filter=False,
            redis_values_key="attrs:fashion:garment_group",
        ),
        AttrDef(
            key="section",
            display_name="Section",
            type="keyword",
            is_qdrant_filter=False,
            redis_values_key="attrs:fashion:section",
        ),
        AttrDef(
            key="occasion",
            display_name="Occasion",
            type="keyword",
            is_qdrant_filter=False,  # Occasion is always soft — fold into rewritten_query, never a hard Qdrant filter
            redis_values_key="attrs:fashion:occasion",
        ),
    ],
    routing_examples=[
        ("something cute for brunch", "SEMANTIC"),
        ("show me floral dresses", "SEMANTIC"),
        ("what colours does H&M have?", "ANALYTICAL"),
        ("which category has the most options?", "ANALYTICAL"),
        ("well-reviewed blue dress under $30", "HYBRID"),
        ("blue dress size M with good reviews", "HYBRID"),
    ],
    schema_hint=(
        "-- products table (fashion domain)\n"
        "-- id UUID, name VARCHAR, brand VARCHAR, category VARCHAR,\n"
        "-- current_price FLOAT,        -- USD\n"
        "-- stock_count INT, avg_rating FLOAT,\n"
        "-- description TEXT,\n"
        "-- attributes JSONB,           -- keys: colour, pattern, garment_group, section, department\n"
        "--                             -- query: attributes->>'colour', attributes->>'pattern'\n"
        "-- style_sentiment, quality_sentiment, fit_sentiment,\n"
        "-- comfort_sentiment, versatility_sentiment, delivery_sentiment  FLOAT,\n"
        "-- external_product_id VARCHAR  -- non-null = H&M product\n"
        "-- Price is stored in USD. Users may ask in ₹ — convert: ₹3000 ≈ $36"
    ),
    synthesis_domain_tips=(
        "Casual → versatility for different settings, everyday comfort, care instructions\n"
        "Office/Formal → fabric quality, fit precision, whether it suits meetings\n"
        "Evening/Party → standout design feature, what to pair it with, occasion fit\n"
        "Active/Sports → breathability, stretch, durability\n"
        "Gifting → occasion relevance, size universality, style breadth\n"
        "Always mention the occasion a piece suits best and one standout feature that justifies the recommendation."
    ),
)

ELECTRONICS_CATALOGUE = CatalogueConfig(
    client_id="electronics",
    display_name="Tech Store",
    qdrant_collection="products",
    price_field_name="current_price",
    price_currency="USD",
    sentiment_fields=[
        "battery_sentiment",
        "display_sentiment",
        "build_quality_sentiment",
        "value_sentiment",
        "performance_sentiment",
    ],
    embedding_fields=["name", "description", "category", "specs"],
    filterable_attrs=[
        AttrDef(
            key="brand",
            display_name="Brand",
            type="keyword",
            is_qdrant_filter=True,
            redis_values_key="attrs:electronics:brand",
        ),
        AttrDef(
            key="category",
            display_name="Category",
            type="keyword",
            is_qdrant_filter=True,
            redis_values_key="attrs:electronics:category",
        ),
        AttrDef(
            key="ram",
            display_name="RAM",
            type="keyword",
            is_qdrant_filter=True,
            redis_values_key="attrs:electronics:ram",
        ),
        AttrDef(
            key="use_case",
            display_name="Use Case",
            type="keyword",
            is_qdrant_filter=False,
            redis_values_key="attrs:electronics:use_case",
        ),
    ],
    routing_examples=[
        ("show me gaming laptops", "SEMANTIC"),
        ("lightweight laptop for travel", "SEMANTIC"),
        ("which brands do you carry?", "ANALYTICAL"),
        ("how many laptops have 32GB RAM?", "ANALYTICAL"),
        ("fast laptop under $1200 with good battery", "HYBRID"),
        ("Dell laptop 16GB RAM for developers", "HYBRID"),
    ],
    schema_hint=(
        "-- products table (electronics domain)\n"
        "-- id UUID, name VARCHAR, brand VARCHAR, category VARCHAR,\n"
        "-- current_price FLOAT,        -- USD\n"
        "-- stock_count INT, avg_rating FLOAT,\n"
        "-- specs JSONB,                -- keys: ram_gb, storage_gb, processor, gpu\n"
        "--                             -- query: (specs->>'ram_gb')::NUMERIC\n"
        "-- battery_sentiment, display_sentiment, build_quality_sentiment,\n"
        "-- value_sentiment, performance_sentiment  FLOAT\n"
        "-- is_active BOOLEAN           -- always filter is_active = true\n"
        "-- Price is stored in USD. Users may ask in ₹ — divide by 83."
    ),
    synthesis_domain_tips=(
        "AI/ML → VRAM, CUDA support, RAM ≥ 16 GB\n"
        "Gaming → GPU tier, refresh rate, thermal headroom\n"
        "Video editing → CPU core count, colour accuracy, storage speed\n"
        "Travel → weight, battery life, build quality"
    ),
)

_REGISTRY: dict[str, CatalogueConfig] = {
    FASHION_CATALOGUE.client_id: FASHION_CATALOGUE,
    ELECTRONICS_CATALOGUE.client_id: ELECTRONICS_CATALOGUE,
}


def get_catalogue(client_id: str) -> CatalogueConfig:
    if client_id not in _REGISTRY:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown catalogue: '{client_id}'. Valid: fashion, electronics",
        )
    return _REGISTRY[client_id]
