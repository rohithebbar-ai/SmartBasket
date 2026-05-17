#!/usr/bin/env python3
"""
Generate 200 synthetic laptop products with 5 reviews each and insert into PostgreSQL.

Run against the local Docker postgres (docker compose up -d first):
    python data/ingestion/generate_synthetic.py

The script is idempotent by product name — it skips any product whose name already
exists, so re-running it is safe during development.
"""

import asyncio
import json
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg
from dotenv import load_dotenv
from faker import Faker

load_dotenv(Path(__file__).parents[2] / ".env")

fake = Faker()
random.seed(42)
Faker.seed(42)

# ── Laptop catalogue data ──────────────────────────────────────────────────────

BRANDS = {
    "Dell":      {"tiers": ["budget", "mid", "premium", "ultra"], "weight": 15},
    "HP":        {"tiers": ["budget", "mid", "premium"],          "weight": 15},
    "Lenovo":    {"tiers": ["budget", "mid", "premium", "ultra"], "weight": 15},
    "Apple":     {"tiers": ["premium", "ultra"],                  "weight": 12},
    "ASUS":      {"tiers": ["budget", "mid", "premium", "ultra"], "weight": 12},
    "Acer":      {"tiers": ["budget", "mid"],                     "weight": 10},
    "Microsoft": {"tiers": ["premium", "ultra"],                  "weight": 8},
    "Razer":     {"tiers": ["premium", "ultra"],                  "weight": 6},
    "MSI":       {"tiers": ["mid", "premium", "ultra"],           "weight": 5},
    "Samsung":   {"tiers": ["mid", "premium"],                    "weight": 2},
}

BRAND_SERIES = {
    "Dell":      ["XPS", "Inspiron", "Latitude", "Precision", "Vostro", "G Series"],
    "HP":        ["Spectre", "Envy", "Pavilion", "EliteBook", "ProBook", "Omen"],
    "Lenovo":    ["ThinkPad", "IdeaPad", "Yoga", "Legion", "ThinkBook"],
    "Apple":     ["MacBook Air", "MacBook Pro"],
    "ASUS":      ["ZenBook", "VivoBook", "ROG", "TUF Gaming", "ExpertBook", "ProArt"],
    "Acer":      ["Swift", "Aspire", "Predator", "Nitro", "ConceptD"],
    "Microsoft": ["Surface Laptop", "Surface Pro"],
    "Razer":     ["Blade", "Blade Stealth"],
    "MSI":       ["Prestige", "Creator", "Stealth", "Titan", "Katana"],
    "Samsung":   ["Galaxy Book"],
}

PROCESSORS = {
    "budget": [
        "Intel Core i5-1235U", "Intel Core i5-1335U", "AMD Ryzen 5 7520U",
        "AMD Ryzen 5 5500U", "Intel Core i3-1315U",
    ],
    "mid": [
        "Intel Core i7-1355U", "Intel Core i5-13500H", "AMD Ryzen 7 7730U",
        "AMD Ryzen 5 7530U", "Intel Core i7-1265U",
    ],
    "premium": [
        "Intel Core i7-13700H", "Intel Core i9-13900H", "AMD Ryzen 9 7940H",
        "AMD Ryzen 7 7745H", "Apple M3", "Apple M3 Pro",
    ],
    "ultra": [
        "Intel Core i9-14900HX", "AMD Ryzen 9 7945HX", "Apple M3 Pro",
        "Apple M3 Max", "Intel Core Ultra 9 185H",
    ],
}

GPUS = {
    "budget":  ["Intel Iris Xe", "AMD Radeon 610M", "Intel UHD Graphics"],
    "mid":     ["NVIDIA RTX 3050", "NVIDIA RTX 4050", "AMD Radeon RX 6600M", "Intel Arc A370M"],
    "premium": ["NVIDIA RTX 4060", "NVIDIA RTX 4070", "AMD Radeon RX 7700S", "Apple M3 GPU 18-core"],
    "ultra":   ["NVIDIA RTX 4080", "NVIDIA RTX 4090", "AMD Radeon RX 7900M", "Apple M3 Max GPU 40-core"],
}

RAM_BY_TIER = {
    "budget":  [8, 16],
    "mid":     [16, 32],
    "premium": [16, 32, 64],
    "ultra":   [32, 64, 96],
}

STORAGE_BY_TIER = {
    "budget":  [256, 512],
    "mid":     [512, 1024],
    "premium": [512, 1024, 2048],
    "ultra":   [1024, 2048, 4096],
}

DISPLAY_SIZES = [13.3, 13.6, 14.0, 14.2, 15.6, 16.0, 16.2, 17.3]

DISPLAY_SPECS = [
    ("1920x1080", "IPS", 60),
    ("1920x1200", "IPS", 60),
    ("2560x1440", "IPS", 165),
    ("2560x1600", "OLED", 120),
    ("3840x2160", "OLED", 60),
    ("2880x1864", "Liquid Retina", 120),
    ("3024x1964", "Liquid Retina XDR", 120),
    ("2560x1664", "IPS", 120),
]

COLORS = ["Midnight Black", "Silver", "Space Gray", "Platinum", "Natural Silver",
          "Lunar Light", "Mineral Gray", "Graphite", "Starlight", "Iceblue", "Storm Grey"]

USE_CASE_SETS = [
    ["productivity", "business"],
    ["gaming", "content creation"],
    ["student", "productivity"],
    ["creative", "video editing"],
    ["software development", "productivity"],
    ["gaming"],
    ["ultraportable", "travel"],
    ["creative", "graphic design", "video editing"],
    ["business", "enterprise"],
    ["student", "budget"],
]

PRICE_RANGES = {
    "budget":  (399.99,  799.99),
    "mid":     (799.99,  1399.99),
    "premium": (1399.99, 2499.99),
    "ultra":   (2499.99, 4999.99),
}

# ── Review templates ───────────────────────────────────────────────────────────

REVIEW_TEMPLATES = {
    5: [
        "Absolutely love this laptop. {positive_aspect} is outstanding and {another_aspect} exceeded my expectations. Best purchase I've made this year.",
        "Incredible machine. The {positive_aspect} blows everything else in this price range out of the water. Highly recommend.",
        "This is exactly what I needed. {positive_aspect} is flawless, and the {another_aspect} is genuinely impressive. Zero complaints.",
        "Fantastic laptop for {use_case}. The {positive_aspect} alone justifies the price. Build quality feels premium.",
        "Been using this for {months} months and it still runs perfectly. The {positive_aspect} is a game-changer.",
    ],
    4: [
        "Really solid laptop overall. {positive_aspect} is excellent. The only minor issue is {minor_issue}, but it doesn't affect daily use.",
        "Great machine for the price. {positive_aspect} is impressive. I wish {minor_issue} was a bit better but not a dealbreaker.",
        "Very happy with this purchase. {positive_aspect} works great. Knocked one star because {minor_issue}.",
        "Good laptop for {use_case}. Performance is strong and {positive_aspect} is better than expected. {minor_issue} could be improved.",
        "Solid choice. Fast, reliable, and the {positive_aspect} is great. {minor_issue} is a small gripe.",
    ],
    3: [
        "Decent laptop but has some issues. {positive_aspect} is good, but {negative_aspect} is disappointing at this price point.",
        "Mixed feelings. {positive_aspect} is solid, but {negative_aspect} lets it down. Okay for light use.",
        "Average machine. Does what it says on the tin. {negative_aspect} is frustrating. {positive_aspect} saves it from a lower rating.",
        "Not bad, not great. {positive_aspect} is fine, but {negative_aspect} is a real problem for {use_case}.",
        "Could be better. {positive_aspect} is a highlight but {negative_aspect} is a persistent issue.",
    ],
    2: [
        "Disappointed with this purchase. {negative_aspect} is a serious problem. {positive_aspect} is the only redeeming quality.",
        "Not worth the price. {negative_aspect} makes {use_case} really frustrating. Save your money.",
        "Had high hopes but {negative_aspect} ruined the experience. {positive_aspect} is average at best.",
        "Poor {negative_aspect} for the price. I expected better. {positive_aspect} is fine but that's not enough.",
        "Struggled with {negative_aspect} from day one. Tech support was unhelpful. Would not recommend.",
    ],
    1: [
        "Total waste of money. {negative_aspect} failed after {months} months. Avoid.",
        "Terrible experience. {negative_aspect} is abysmal and customer service was useless. Returning immediately.",
        "Do not buy. {negative_aspect} is broken out of the box. {positive_aspect} barely works.",
        "Worst laptop I've owned. {negative_aspect} makes it unusable for {use_case}. Complete disappointment.",
        "Overpriced junk. {negative_aspect} is unacceptable at this price. Would give zero stars if I could.",
    ],
}

POSITIVE_ASPECTS = ["battery life", "display quality", "build quality", "keyboard",
                    "performance", "trackpad", "speakers", "port selection", "thermals"]
NEGATIVE_ASPECTS = ["battery life", "fan noise", "display brightness", "port selection",
                    "keyboard flex", "thermal throttling", "webcam quality", "weight"]
MINOR_ISSUES = ["fan noise under load", "the webcam quality", "the limited port selection",
                "the charger bulk", "the glossy display in bright light", "USB-A port absence"]
USE_CASES_TEXT = ["programming", "video editing", "gaming", "everyday tasks",
                  "travel", "graphic design", "office work", "studying"]


# ── Generators ─────────────────────────────────────────────────────────────────

def pick_tier() -> str:
    return random.choices(
        ["budget", "mid", "premium", "ultra"],
        weights=[25, 35, 30, 10],
    )[0]


def pick_brand(tier: str) -> str:
    eligible = [b for b, v in BRANDS.items() if tier in v["tiers"]]
    weights = [BRANDS[b]["weight"] for b in eligible]
    return random.choices(eligible, weights=weights)[0]


def make_product(brand: str, tier: str, name_set: set[str]) -> dict:
    series = random.choice(BRAND_SERIES[brand])
    model_num = random.randint(13, 16) if "MacBook" not in series else ""
    suffix = random.choice(["", " Plus", " Pro", " Ultra", " SE", " Gen 2", " Gen 3"])
    if "MacBook" in series:
        size_label = random.choice(["13-inch", "14-inch", "16-inch"])
        name_candidate = f"{series} {size_label} {random.randint(2023, 2024)}"
    else:
        name_candidate = f"{brand} {series} {model_num}{suffix}".strip()

    # ensure uniqueness within this batch
    original = name_candidate
    counter = 2
    while name_candidate in name_set:
        name_candidate = f"{original} ({counter})"
        counter += 1
    name_set.add(name_candidate)

    processor = random.choice(PROCESSORS[tier])
    gpu = random.choice(GPUS[tier])
    ram = random.choice(RAM_BY_TIER[tier])
    storage = random.choice(STORAGE_BY_TIER[tier])
    display_size = random.choice(DISPLAY_SIZES)
    resolution, panel, refresh = random.choice(DISPLAY_SPECS)
    color = random.choice(COLORS)
    use_cases = random.choice(USE_CASE_SETS)
    os_name = "macOS Sonoma" if brand == "Apple" else random.choice(
        ["Windows 11 Home", "Windows 11 Pro", "Ubuntu 24.04"]
    )

    low, high = PRICE_RANGES[tier]
    base_price = round(random.uniform(low, high), 2)
    # current_price: within ±15% of base (pricing engine will take over later)
    current_price = round(base_price * random.uniform(0.90, 1.10), 2)

    battery_wh = random.choice([45, 54, 60, 72, 86, 99, 110])
    battery_hours = round(random.uniform(5, 20), 1)
    weight_kg = round(random.uniform(0.9, 2.8), 2)

    specs = {
        "processor": processor,
        "ram_gb": ram,
        "storage_gb": storage,
        "storage_type": "NVMe SSD",
        "display_size_inch": display_size,
        "display_resolution": resolution,
        "display_type": panel,
        "refresh_rate_hz": refresh,
        "gpu": gpu,
        "battery_wh": battery_wh,
        "battery_life_hours": battery_hours,
        "weight_kg": weight_kg,
        "os": os_name,
        "ports": random.sample(
            ["USB-A 3.2", "USB-C 3.2", "Thunderbolt 4", "HDMI 2.1", "SD card reader",
             "3.5mm audio", "USB4", "MagSafe"],
            k=random.randint(3, 6),
        ),
        "wifi": random.choice(["Wi-Fi 6", "Wi-Fi 6E", "Wi-Fi 7"]),
        "bluetooth": random.choice(["5.1", "5.2", "5.3"]),
        "color": color,
        "use_cases": use_cases,
        "backlit_keyboard": random.choice([True, True, True, False]),
        "fingerprint_reader": random.choice([True, True, False]),
        "webcam": random.choice(["720p", "1080p", "1080p"]),
        "tier": tier,
    }

    stock = random.randint(0, 200)

    return {
        "id": str(uuid.uuid4()),
        "name": name_candidate,
        "brand": brand,
        "category": "laptop",
        "base_price": base_price,
        "current_price": current_price,
        "specs": specs,
        "stock_count": stock,
        "is_active": True,
    }


def _render_template(template: str, use_cases: list[str]) -> str:
    pos = random.choice(POSITIVE_ASPECTS)
    another = random.choice([a for a in POSITIVE_ASPECTS if a != pos])
    neg = random.choice(NEGATIVE_ASPECTS)
    return template.format(
        positive_aspect=pos,
        another_aspect=another,
        negative_aspect=neg,
        minor_issue=random.choice(MINOR_ISSUES),
        use_case=random.choice(use_cases if use_cases else USE_CASES_TEXT),
        months=random.randint(2, 18),
    )


def _sentiment_for_rating(rating: int) -> tuple[float, float, float, float, float]:
    """
    Return (battery, display, build_quality, value, performance) sentiment scores.
    Scores cluster around the rating with ±0.8 jitter and are clamped to [1.0, 5.0].
    """
    def jittered(base: float) -> float:
        return round(max(1.0, min(5.0, base + random.uniform(-0.8, 0.8))), 2)

    base = float(rating)
    return (jittered(base), jittered(base), jittered(base), jittered(base), jittered(base))


def make_reviews(product_id: str, use_cases: list[str]) -> list[dict]:
    # Distribute 5 ratings: skew positive for high-tier, realistic spread overall
    rating_pool = [5, 5, 4, 4, 3, 3, 2, 1]
    ratings = random.choices(rating_pool, k=5)
    reviews = []
    base_date = datetime.now(tz=timezone.utc) - timedelta(days=random.randint(30, 365))

    for i, rating in enumerate(ratings):
        template = random.choice(REVIEW_TEMPLATES[rating])
        text = _render_template(template, use_cases)
        batt, disp, build, val, perf = _sentiment_for_rating(rating)
        reviews.append({
            "id": str(uuid.uuid4()),
            "product_id": product_id,
            "rating": rating,
            "review_text": text,
            "battery_sentiment": batt,
            "display_sentiment": disp,
            "build_quality_sentiment": build,
            "value_sentiment": val,
            "performance_sentiment": perf,
            "created_at": base_date + timedelta(days=i * random.randint(5, 30)),
        })
    return reviews


# ── Database helpers ───────────────────────────────────────────────────────────

def _asyncpg_dsn(database_url: str) -> str:
    """Strip the +asyncpg dialect prefix — asyncpg uses plain postgresql:// DSNs."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://")


async def insert_batch(conn: asyncpg.Connection, products: list[dict], all_reviews: list[dict]) -> None:
    async with conn.transaction():
        # Products
        await conn.executemany(
            """
            INSERT INTO products
                (id, name, brand, category, base_price, current_price,
                 specs, stock_count, avg_rating, is_active)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (id) DO NOTHING
            """,
            [
                (
                    p["id"], p["name"], p["brand"], p["category"],
                    p["base_price"], p["current_price"],
                    json.dumps(p["specs"]), p["stock_count"],
                    0.0,  # avg_rating seeded to 0; updated after reviews are inserted
                    p["is_active"],
                )
                for p in products
            ],
        )

        # Reviews
        await conn.executemany(
            """
            INSERT INTO reviews
                (id, product_id, rating, review_text,
                 battery_sentiment, display_sentiment, build_quality_sentiment,
                 value_sentiment, performance_sentiment, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (id) DO NOTHING
            """,
            [
                (
                    r["id"], r["product_id"], r["rating"], r["review_text"],
                    r["battery_sentiment"], r["display_sentiment"],
                    r["build_quality_sentiment"], r["value_sentiment"],
                    r["performance_sentiment"], r["created_at"],
                )
                for r in all_reviews
            ],
        )

        # Back-fill avg_rating from the reviews we just inserted
        await conn.execute(
            """
            UPDATE products p
            SET avg_rating = sub.avg
            FROM (
                SELECT product_id, ROUND(AVG(rating)::numeric, 2) AS avg
                FROM reviews
                WHERE product_id = ANY($1::uuid[])
                GROUP BY product_id
            ) sub
            WHERE p.id = sub.product_id
            """,
            [p["id"] for p in products],
        )


# ── Main ───────────────────────────────────────────────────────────────────────

async def main() -> None:
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://shopsense:shopsense@localhost:5432/shopsense",
    )
    dsn = _asyncpg_dsn(database_url)

    print(f"Connecting to {dsn.split('@')[-1]} …")
    conn: asyncpg.Connection = await asyncpg.connect(dsn)

    try:
        # Check for existing synthetic data so re-runs don't silently duplicate
        existing = await conn.fetchval("SELECT COUNT(*) FROM products WHERE category = 'laptop'")
        if existing:
            print(f"Found {existing} existing laptop rows — skipping insert. "
                  "Truncate the tables manually if you want a fresh seed.")
            return

        print("Generating 200 laptops …")
        name_set: set[str] = set()
        products: list[dict] = []

        for _ in range(200):
            tier = pick_tier()
            brand = pick_brand(tier)
            products.append(make_product(brand, tier, name_set))

        all_reviews: list[dict] = []
        for p in products:
            all_reviews.extend(make_reviews(p["id"], p["specs"]["use_cases"]))

        print(f"Inserting {len(products)} products and {len(all_reviews)} reviews …")
        await insert_batch(conn, products, all_reviews)

        # Summary
        total_products = await conn.fetchval("SELECT COUNT(*) FROM products")
        total_reviews = await conn.fetchval("SELECT COUNT(*) FROM reviews")
        avg_price = await conn.fetchval("SELECT ROUND(AVG(current_price)::numeric, 2) FROM products")
        avg_rating = await conn.fetchval("SELECT ROUND(AVG(avg_rating)::numeric, 2) FROM products")
        print(
            f"\nDone.\n"
            f"  products : {total_products} (avg price ${avg_price})\n"
            f"  reviews  : {total_reviews} (avg product rating {avg_rating}/5)\n"
        )

        # Brand breakdown
        rows = await conn.fetch(
            "SELECT brand, COUNT(*) AS n FROM products GROUP BY brand ORDER BY n DESC"
        )
        print("Brand breakdown:")
        for row in rows:
            print(f"  {row['brand']:<12} {row['n']:>3}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
