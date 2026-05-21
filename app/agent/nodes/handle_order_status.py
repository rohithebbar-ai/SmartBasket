"""
handle_order_status — returns the user's last 3 orders from PostgreSQL.

No LLM call — order data is structured, so we format it directly.
Covers: pending, confirmed, shipped, delivered, cancelled, refunded.

Reads:  state.user_id
Writes: state.final_response

Outgoing edge: → save_history (always)
"""

import logging

from sqlalchemy import text

from app.agent.state import ShopSenseState
from app.database import AsyncSessionLocal

log = logging.getLogger(__name__)

_ORDERS_SQL = text("""
    SELECT id::text, status,
           CAST(total_amount AS FLOAT) AS total_amount,
           items, created_at, delivered_at
    FROM orders
    WHERE user_id = :uid
    ORDER BY created_at DESC
    LIMIT 3
""")

_STATUS_LABEL: dict[str, str] = {
    "pending":   "Pending",
    "confirmed": "Confirmed",
    "shipped":   "Shipped",
    "delivered": "Delivered",
    "cancelled": "Cancelled",
    "refunded":  "Refunded",
}


def _fmt_date(dt) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%d %b %Y")


def _summarise_items(items: list) -> str:
    if not items:
        return "No items recorded"
    names = [i.get("name", "Unknown item") for i in items[:3]]
    suffix = f" (+{len(items) - 3} more)" if len(items) > 3 else ""
    return ", ".join(names) + suffix


def _status_line(row) -> str:
    status = row["status"]
    if status == "delivered" and row["delivered_at"]:
        return f"Delivered on {_fmt_date(row['delivered_at'])}"
    if status == "shipped":
        return "Shipped — expected within 2–4 business days"
    if status == "cancelled":
        return f"Cancelled (ordered {_fmt_date(row['created_at'])})"
    return f"Ordered on {_fmt_date(row['created_at'])}"


async def handle_order_status(state: ShopSenseState) -> dict:
    user_id = state.get("user_id", "")
    if not user_id:
        return {"final_response": "Please log in to check your order status."}

    try:
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(_ORDERS_SQL, {"uid": user_id})
            ).mappings().all()
    except Exception as exc:
        log.warning("Order status query failed for user %s: %s", user_id, exc)
        return {
            "final_response": (
                "I couldn't retrieve your orders right now. "
                "Please try again in a moment."
            )
        }

    if not rows:
        return {
            "final_response": (
                "You haven't placed any orders yet. "
                "Browse our catalogue and find something you'd love!"
            )
        }

    lines = ["Here are your recent orders:\n"]
    for row in rows:
        short_id = row["id"][:8].upper()
        label    = _STATUS_LABEL.get(row["status"], row["status"].title())
        lines.append(
            f"Order #{short_id} — {label}\n"
            f"  {_status_line(row)}\n"
            f"  {_summarise_items(row['items'] or [])}\n"
            f"  Total: ₹{row['total_amount']:,.0f}\n"
        )

    lines.append("Share an order number if you'd like more details.")
    return {"final_response": "\n".join(lines)}
