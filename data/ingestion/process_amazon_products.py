"""
Reads the 10 Amazon Electronics metadata parquet shards from HuggingFace,
filters to laptop items with valid price and features, extracts specs,
and upserts to PostgreSQL as real products.

Adds ~3,000–5,000 real Amazon laptop listings on top of the 991 Kaggle products.

Run:
    DATABASE_URL=postgresql+asyncpg://shopsense:shopsense@localhost:5432/shopsense \
      python data/ingestion/process_amazon_products.py
"""

import asyncio
import json
import logging
import re
import uuid
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd

from db_utils import dual_connect, fetchval_primary

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

HF_BASE = "https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/main"
NUM_SHARDS = 10
CACHE_DIR = Path("data/raw/amazon_meta_cache")

LAPTOP_KEYWORDS = {"laptop", "notebook", "macbook", "chromebook", "ultrabook", "thinkpad", "ideapad"}

# Minimum price $50, maximum $8000 — filters accessories and ultra-expensive bundles
MIN_PRICE_USD = 50.0
MAX_PRICE_USD = 8000.0

BRAND_NORMALISE = {
    "hewlett packard": "HP", "hp inc": "HP",
    "acer inc": "Acer", "acer america": "Acer",
    "asustek": "ASUS", "asus computer": "ASUS",
    "apple inc": "Apple",
    "lenovo group": "Lenovo",
    "dell inc": "Dell", "dell technologies": "Dell",
    "microsoft corporation": "Microsoft",
    "samsung electronics": "Samsung",
    "lg electronics": "LG",
    "msi (micro-star international)": "MSI", "micro-star international": "MSI",
    "toshiba america": "Toshiba", "toshiba": "Toshiba",
    "razer inc": "Razer",
    "google": "Google",
}


# ── Spec extraction from Amazon features list ─────────────────────────────────

def _extract_ram(features: list[str]) -> int | None:
    pattern = re.compile(r'(\d+)\s*GB\s*(DDR\d*|LPDDR\d*|Unified)?\s*(RAM|Memory|SDRAM)', re.I)
    for f in features:
        m = pattern.search(f)
        if m:
            val = int(m.group(1))
            if 2 <= val <= 256:
                return val
    return None


def _extract_storage(features: list[str]) -> tuple[int | None, str | None]:
    pattern = re.compile(r'(\d+)\s*(GB|TB)\s*(SSD|HDD|NVMe|eMMC|Flash|PCIe)', re.I)
    for f in features:
        m = pattern.search(f)
        if m:
            amount, unit, stype = int(m.group(1)), m.group(2).upper(), m.group(3).upper()
            gb = amount * 1024 if unit == "TB" else amount
            if 16 <= gb <= 8192:
                return gb, stype
    return None, None


def _extract_processor(features: list[str], title: str) -> str | None:
    patterns = [
        re.compile(r'(Intel\s+Core\s+[imc]\d[-\s]\w+)', re.I),
        re.compile(r'(AMD\s+Ryzen\s+\d\s+\w+)', re.I),
        re.compile(r'(Apple\s+M\d+(?:\s+(?:Pro|Max|Ultra))?)', re.I),
        re.compile(r'(Qualcomm\s+Snapdragon\s+\w+)', re.I),
        re.compile(r'(Intel\s+(?:Celeron|Pentium|Core\s+Ultra)\s+\w+)', re.I),
        re.compile(r'(AMD\s+(?:A\d+|Athlon|EPYC)\s*\w*)', re.I),
    ]
    for text in [*features, title]:
        for pat in patterns:
            m = pat.search(text)
            if m:
                return m.group(1).strip()
    return None


def _extract_display(features: list[str], title: str) -> float | None:
    pattern = re.compile(r'(\d+\.?\d*)["\s-]?\s*(?:inch|in\b|")', re.I)
    for text in [*features, title]:
        m = pattern.search(text)
        if m:
            val = float(m.group(1))
            if 10.0 <= val <= 18.0:
                return val
    return None


def _extract_gpu(features: list[str]) -> tuple[str | None, str | None]:
    dedicated = re.compile(r'(NVIDIA\s+(?:GeForce|RTX|GTX)\s+\w+|AMD\s+Radeon\s+RX\s+\w+)', re.I)
    integrated = re.compile(r'(Intel\s+(?:Iris|UHD|Xe)\s*\w*|AMD\s+Radeon\s+Graphics|Apple\s+\w+\s+GPU)', re.I)
    for f in features:
        m = dedicated.search(f)
        if m:
            return m.group(1).strip(), "dedicated"
        m = integrated.search(f)
        if m:
            return m.group(1).strip(), "integrated"
    return None, None


def _parse_price(price_str) -> float | None:
    if not price_str or pd.isna(price_str):
        return None
    cleaned = re.sub(r'[^\d.]', '', str(price_str).split('-')[0].strip())
    try:
        val = float(cleaned)
        return val if MIN_PRICE_USD <= val <= MAX_PRICE_USD else None
    except ValueError:
        return None


def _normalise_brand(store: str) -> str:
    if not store:
        return "Unknown"
    key = store.strip().lower()
    return BRAND_NORMALISE.get(key, store.strip().title())


def _is_laptop(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in LAPTOP_KEYWORDS)


# ── Parquet loading ───────────────────────────────────────────────────────────

def load_metadata_shards() -> pd.DataFrame:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    frames: list[pd.DataFrame] = []

    for i in range(NUM_SHARDS):
        cache_path = CACHE_DIR / f"shard_{i:02d}.parquet"
        if cache_path.exists():
            log.info("  shard %d: loading from cache", i)
            df = pd.read_parquet(cache_path)
        else:
            url = f"{HF_BASE}/raw_meta_Electronics/full-{i:05d}-of-{NUM_SHARDS:05d}.parquet"
            log.info("  shard %d: downloading %s", i, url)
            df = pd.read_parquet(url, storage_options={"anon": True}, engine="pyarrow")
            df.to_parquet(cache_path)

        # Filter to laptops immediately to keep memory low
        mask = df["title"].apply(lambda t: _is_laptop(str(t)) if pd.notna(t) else False)
        filtered = df[mask].copy()
        log.info("  shard %d: %d rows → %d laptop items", i, len(df), len(filtered))
        frames.append(filtered)

    combined = pd.concat(frames, ignore_index=True)
    log.info("Total laptop items from all shards: %d", len(combined))
    return combined


# ── Transform ─────────────────────────────────────────────────────────────────

def transform(df: pd.DataFrame) -> list[dict]:
    records: list[dict] = []
    skipped_price = skipped_dup = 0
    seen_titles: set[str] = set()

    for _, row in df.iterrows():
        title = str(row.get("title") or "").strip()
        if not title or title in seen_titles:
            skipped_dup += 1
            continue
        seen_titles.add(title)

        price = _parse_price(row.get("price"))
        if price is None:
            skipped_price += 1
            continue

        raw_features = row.get("features")
        if raw_features is None or (hasattr(raw_features, '__len__') and len(raw_features) == 0):
            features: list[str] = []
        elif isinstance(raw_features, str):
            try:
                features = json.loads(raw_features)
            except Exception:
                features = [raw_features]
        else:
            features = list(raw_features)
        features = [str(f) for f in features if f and str(f) != "nan"]

        brand  = _normalise_brand(str(row.get("store") or ""))
        if brand == "Unknown":
            # Fall back to first word of title
            brand = title.split()[0].title()

        base_price = Decimal(str(price)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        specs: dict = {}
        ram = _extract_ram(features)
        if ram:
            specs["ram_gb"] = ram

        storage_gb, storage_type = _extract_storage(features)
        if storage_gb:
            specs["storage_gb"] = storage_gb
        if storage_type:
            specs["storage_type"] = storage_type

        processor = _extract_processor(features, title)
        if processor:
            specs["processor"] = processor

        display = _extract_display(features, title)
        if display:
            specs["display_size_inch"] = display

        gpu, gpu_type = _extract_gpu(features)
        if gpu:
            specs["gpu"] = gpu
            specs["gpu_type"] = gpu_type

        # Derive use_cases
        use_cases = ["general"]
        if gpu_type == "dedicated":
            use_cases.append("gaming")
        if ram and ram >= 16:
            use_cases.append("professional")
        if display and display <= 13.5:
            use_cases.append("portable")
        specs["use_cases"] = use_cases

        avg_rating = float(row.get("average_rating") or 0.0)
        if avg_rating > 5.0:
            avg_rating = avg_rating / 20.0  # 0-100 scale

        records.append({
            "id": str(uuid.uuid4()),
            "name": title[:500],
            "brand": brand[:100],
            "category": "laptop",
            "base_price": str(base_price),
            "current_price": str(base_price),
            "specs": specs,
            "stock_count": 10,
            "avg_rating": round(avg_rating, 2),
            "is_active": True,
        })

    log.info(
        "Transform: %d records built  (skipped: %d no-price, %d duplicates)",
        len(records), skipped_price, skipped_dup,
    )
    return records


# ── Upsert ────────────────────────────────────────────────────────────────────

async def upsert(records: list[dict]) -> None:
    SQL = (
        "INSERT INTO products (id,name,brand,category,base_price,current_price,"
        "specs,stock_count,avg_rating,is_active) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT (name) DO NOTHING"
    )
    async with dual_connect() as conns:
        before = await fetchval_primary(conns, "SELECT COUNT(*) FROM products")
        log.info("Products in DB before upsert: %d", before)

        inserted = skipped = 0
        for r in records:
            args = (
                uuid.UUID(r["id"]), r["name"], r["brand"], r["category"],
                Decimal(r["base_price"]), Decimal(r["current_price"]),
                json.dumps(r["specs"]), r["stock_count"], r["avg_rating"], r["is_active"],
            )
            result = await conns[0].execute(SQL, *args)
            n = int(result.split()[-1])
            inserted += n
            skipped += 1 - n
            if n and len(conns) > 1:
                await conns[1].execute(SQL, *args)

        after = await fetchval_primary(conns, "SELECT COUNT(*) FROM products")
        log.info("Inserted: %d  Skipped: %d  Total products: %d", inserted, skipped, after)


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    log.info("=== Amazon Electronics → ShopSense products ===")
    log.info("Loading %d metadata parquet shards…", NUM_SHARDS)
    df = load_metadata_shards()

    log.info("Transforming…")
    records = transform(df)

    if records:
        sample = records[0]
        log.info("Sample: %s — %s @ $%s", sample["brand"], sample["name"][:60], sample["base_price"])
        log.info("Sample specs: %s", list(sample["specs"].keys()))

    log.info("Upserting %d products…", len(records))
    await upsert(records)
    log.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
