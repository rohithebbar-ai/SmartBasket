"""
Maps H&M source columns to the SmartBasket canonical product schema.
"""

# H&M fields → canonical fields
_HM_MAP = {
    "article_id":       "external_product_id",
    "prod_name":        "name",
    "product_type_name": "category",
    "detail_desc":      "description",
    "index_group_name": "brand",   # no brand field in H&M; use audience segment
}

# H&M fields packed into the `attributes` JSONB column
_HM_ATTRIBUTE_FIELDS = {
    "colour_group_name":            "colour",
    "perceived_colour_master_name": "colour_master",
    "graphical_appearance_name":    "pattern",
    "garment_group_name":           "garment_group",
    "product_group_name":           "product_group",
    "section_name":                 "section",
    "department_name":              "department",
}


def map_hm_row(raw: dict) -> dict:
    """Convert one raw H&M row to a canonical product dict."""
    out: dict = {}

    for src, dst in _HM_MAP.items():
        val = raw.get(src)
        if val is not None:
            out[dst] = str(val).strip() if isinstance(val, str) else val

    out["attributes"] = {
        dst: str(raw[src]).strip()
        for src, dst in _HM_ATTRIBUTE_FIELDS.items()
        if raw.get(src)
    }

    # Full S3 image URL provided by this dataset version
    out["image_url"] = raw.get("image_url") or None

    # Carry raw group names through for the validator filter (dropped after validation)
    out["_product_group"] = raw.get("product_group_name", "")
    out["_index_group"]   = raw.get("index_group_name", "")

    return out


def map_batch(rows: list[dict], source: str = "hm") -> list[dict]:
    if source == "hm":
        return [map_hm_row(r) for r in rows]
    raise ValueError(f"Unknown source: {source}")
