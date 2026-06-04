"""
Validates mapped product rows before normalisation.
Filters out:
  - Rows missing required fields (name, category)
  - Undergarments, lingerie, swimwear, nightwear, socks
    (not suitable for the demo storefront)
"""
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

# H&M product_group_name values to exclude from the demo
_EXCLUDED_PRODUCT_GROUPS = {
    # Undergarments / nightwear
    "Underwear",
    "Socks & Tights",
    "Swimwear",
    "Nightwear",
    "Underwear/nightwear",
    # Non-clothing — accessories, shoes
    "Accessories",
    "Shoes",
    "Items",
}

# H&M index_group_name values to exclude (catches lingerie index)
_EXCLUDED_INDEX_GROUPS = {
    "Lingeries/Tights",
}

REQUIRED_FIELDS = ("name", "category", "external_product_id")


@dataclass
class ValidationError:
    row_id: str
    reason: str


def validate(rows: list[dict]) -> tuple[list[dict], list[ValidationError]]:
    """
    Returns (valid_rows, errors).
    Strips internal `_product_group` / `_index_group` keys from valid rows.
    """
    valid: list[dict] = []
    errors: list[ValidationError] = []

    for row in rows:
        row_id = row.get("external_product_id", "<unknown>")

        # Exclude unsuitable product groups
        product_group = row.get("_product_group", "")
        index_group   = row.get("_index_group", "")

        if product_group in _EXCLUDED_PRODUCT_GROUPS:
            errors.append(ValidationError(row_id, f"excluded group: {product_group}"))
            continue
        if index_group in _EXCLUDED_INDEX_GROUPS:
            errors.append(ValidationError(row_id, f"excluded index: {index_group}"))
            continue

        # Required field check
        missing = [f for f in REQUIRED_FIELDS if not row.get(f)]
        if missing:
            errors.append(ValidationError(row_id, f"missing: {missing}"))
            continue

        # Strip internal keys before passing downstream
        clean = {k: v for k, v in row.items() if not k.startswith("_")}
        valid.append(clean)

    return valid, errors
