"""
Normalises validated product rows before loading.
Responsibilities:
  - Generate synthetic prices (H&M dataset has no prices)
  - Set stock_count
  - Clean text fields
  - Set brand fallback
"""
import hashlib
import random

# Seeded by article_id so reruns produce identical prices for the same product
def _seeded_price(external_product_id: str, low: float, high: float) -> float:
    seed = int(hashlib.md5(external_product_id.encode()).hexdigest(), 16) % 10_000
    rng = random.Random(seed)
    raw = rng.uniform(low, high)
    return round(raw, 2)


# Price ranges in USD (frontend multiplies by 83 to display INR)
_PRICE_RANGES: dict[str, tuple[float, float]] = {
    # Outerwear
    "Jacket":            (30,  60),
    "Coat":              (36,  72),
    "Windbreaker":       (22,  42),
    # Dresses
    "Dress":             (14,  42),
    "Jumpsuit/Playsuit": (18,  48),
    # Tops
    "T-shirt":           (5,   14),
    "Blouse":            (10,  24),
    "Top":               (6,   18),
    "Vest top":          (5,   12),
    "Shirt":             (10,  24),
    "Sweater":           (14,  36),
    "Hoodie":            (12,  30),
    "Cardigan":          (12,  30),
    # Bottoms
    "Trousers":          (12,  36),
    "Jeans":             (18,  42),
    "Shorts":            (7,   22),
    "Skirt":             (10,  24),
    "Leggings/Tights":   (6,   14),
}
_DEFAULT_PRICE_RANGE = (6.0, 24.0)


def _get_price(row: dict) -> float:
    category = row.get("category", "")
    for key, (low, high) in _PRICE_RANGES.items():
        if key.lower() in category.lower():
            return _seeded_price(row["external_product_id"], low, high)
    return _seeded_price(row["external_product_id"], *_DEFAULT_PRICE_RANGE)


def normalise(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        price = _get_price(row)
        row["base_price"]    = price
        row["current_price"] = price
        row["stock_count"]   = 50   # default stock for demo
        row["avg_rating"]    = 0.0
        row["is_active"]     = True
        row["brand"]         = row.get("brand") or "H&M"
        # Truncate description to avoid DB limits
        if row.get("description"):
            row["description"] = row["description"][:1000].strip()
        # Ensure name is not empty
        if not row.get("name"):
            row["name"] = row.get("category", "Unknown Product")
        out.append(row)
    return out
