"""
Reads Kaggle laptop CSVs, normalises columns, converts INR → USD,
maps to the products schema, and upserts to PostgreSQL.

Run:
    DATABASE_URL=postgresql+asyncpg://shopsense:shopsense@localhost:5432/shopsense \
      python data/ingestion/process_kaggle_laptops.py
"""

import asyncio
import sys
import uuid
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd

from db_utils import dual_connect, exec_all, fetchval_primary

# ── Constants ─────────────────────────────────────────────────────────────────

INR_TO_USD = Decimal("0.012")   # 1 INR ≈ 0.012 USD (1 USD ≈ 83 INR)

RAW_DIR = Path(__file__).parent.parent / "raw"
CSV_FILES = [
    RAW_DIR / "laptops.csv",
    RAW_DIR / "brand" / "laptops.csv",
]

# Brands to normalise to their canonical display name
BRAND_DISPLAY = {
    "acer": "Acer", "apple": "Apple", "asus": "ASUS", "avita": "Avita",
    "axl": "AXL", "chuwi": "Chuwi", "dell": "Dell", "fujitsu": "Fujitsu",
    "gigabyte": "Gigabyte", "honor": "Honor", "hp": "HP", "iball": "iBall",
    "infinix": "Infinix", "jio": "Jio", "lenovo": "Lenovo", "lg": "LG",
    "microsoft": "Microsoft", "msi": "MSI", "primebook": "Primebook",
    "realme": "Realme", "samsung": "Samsung", "tecno": "Tecno",
    "ultimus": "Ultimus", "walker": "Walker", "wings": "Wings",
    "zebronics": "Zebronics",
}


# ── Data loading and normalisation ────────────────────────────────────────────

def load_and_deduplicate() -> pd.DataFrame:
    frames = []
    for path in CSV_FILES:
        if path.exists():
            frames.append(pd.read_csv(path))
            print(f"  loaded {path.name} from {path.parent.name}/  ({len(frames[-1])} rows)")
        else:
            print(f"  skipping {path} — not found")

    if not frames:
        sys.exit("No CSV files found. Run the kaggle download commands first.")

    df = pd.concat(frames, ignore_index=True)
    before = len(df)
    df = df.drop_duplicates(subset=["Model"])
    print(f"  deduplicated: {before} → {len(df)} unique models")
    return df


def inr_to_usd(inr: float) -> Decimal:
    return (Decimal(str(inr)) * INR_TO_USD).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def rating_to_five(rating: float) -> float:
    """Converts 0–100 integer rating to 0.0–5.0 scale, rounded to 1dp."""
    return round(float(rating) / 20.0, 1)


def build_processor_string(row: pd.Series) -> str:
    brand = str(row["processor_brand"]).strip().title()
    tier = str(row["processor_tier"]).strip().title()
    cores = row["num_cores"]
    threads = row["num_threads"]
    return f"{brand} {tier} ({cores}C/{threads}T)"


def build_specs(row: pd.Series) -> dict:
    specs: dict = {}

    specs["processor"] = build_processor_string(row)
    specs["ram_gb"] = int(row["ram_memory"])
    specs["storage_gb"] = int(row["primary_storage_capacity"])
    specs["storage_type"] = str(row["primary_storage_type"]).upper()

    if row["secondary_storage_capacity"] > 0:
        specs["secondary_storage_gb"] = int(row["secondary_storage_capacity"])
        specs["secondary_storage_type"] = str(row["secondary_storage_type"]).upper()

    gpu_brand = str(row["gpu_brand"]).strip().title()
    gpu_type = str(row["gpu_type"]).strip().lower()
    specs["gpu"] = f"{gpu_brand} ({gpu_type})"
    specs["gpu_type"] = gpu_type  # "integrated" | "dedicated"

    specs["display_size_inch"] = float(row["display_size"])
    specs["resolution"] = f"{int(row['resolution_width'])}x{int(row['resolution_height'])}"
    specs["is_touch_screen"] = bool(row["is_touch_screen"])
    specs["os"] = str(row["OS"]).strip().lower()
    try:
        specs["warranty_years"] = int(row["year_of_warranty"])
    except (ValueError, TypeError):
        specs["warranty_years"] = 1

    # Derived use_cases — useful for semantic search
    use_cases = ["general"]
    if gpu_type == "dedicated":
        use_cases.append("gaming")
    if specs["ram_gb"] >= 16:
        use_cases.append("professional")
    if specs["display_size_inch"] <= 13.5:
        use_cases.append("portable")
    specs["use_cases"] = use_cases

    return specs


def transform(df: pd.DataFrame) -> list[dict]:
    records = []
    for _, row in df.iterrows():
        brand_key = str(row["brand"]).strip().lower()
        brand = BRAND_DISPLAY.get(brand_key, str(row["brand"]).strip().title())
        name = str(row["Model"]).strip()

        base_price = inr_to_usd(float(row["Price"]))
        # Clamp to reasonable range: $50–$6000
        base_price = max(Decimal("50.00"), min(base_price, Decimal("6000.00")))

        records.append({
            "id": str(uuid.uuid4()),
            "name": name,
            "brand": brand,
            "category": "laptop",
            "base_price": str(base_price),
            "current_price": str(base_price),
            "specs": build_specs(row),
            "stock_count": 10,
            "avg_rating": rating_to_five(float(row["Rating"])),
            "is_active": True,
        })
    return records


# ── PostgreSQL upsert ─────────────────────────────────────────────────────────

async def upsert(records: list[dict]) -> None:
    import json

    async with dual_connect() as conns:
        existing = await fetchval_primary(conns, "SELECT COUNT(*) FROM products WHERE category = 'laptop'")
        print(f"\n  existing laptop rows in DB: {existing}")

        inserted = 0
        skipped = 0
        for r in records:
            args = (
                uuid.UUID(r["id"]), r["name"], r["brand"], r["category"],
                Decimal(r["base_price"]), Decimal(r["current_price"]),
                json.dumps(r["specs"]), r["stock_count"], r["avg_rating"], r["is_active"],
            )
            # Write to all connections (local + mirror)
            result = await conns[0].execute(
                "INSERT INTO products (id,name,brand,category,base_price,current_price,specs,stock_count,avg_rating,is_active) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT (name) DO NOTHING", *args
            )
            n = int(result.split()[-1])
            inserted += n
            skipped += 1 - n
            if n and len(conns) > 1:
                await conns[1].execute(
                    "INSERT INTO products (id,name,brand,category,base_price,current_price,specs,stock_count,avg_rating,is_active) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT (name) DO NOTHING", *args
                )

        total = await fetchval_primary(conns, "SELECT COUNT(*) FROM products")
        print(f"  inserted: {inserted}  skipped (duplicates): {skipped}")
        print(f"  total products in DB: {total}")


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    print("=== ShopSense Kaggle laptop ingestion ===\n")

    print("Loading CSVs...")
    df = load_and_deduplicate()

    print(f"\nTransforming {len(df)} records...")
    records = transform(df)

    # Quick sanity check
    sample = records[0]
    print(f"  sample: {sample['brand']} — {sample['name'][:60]}")
    print(f"          price=${sample['base_price']}  rating={sample['avg_rating']}")
    print(f"          specs keys: {list(sample['specs'].keys())}")

    print("\nUpserting to PostgreSQL...")
    await upsert(records)

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
