"""
End-to-end LangGraph flow test.
Run with: python test_flow.py

Flow tested:
  1. Search for a laptop
  2. Add it to cart (interrupt → confirm)
  3. Checkout (interrupt → confirm)
  4. Post-payment: ask a new product query
  5. Try a new purchase after payment (verify stale-source bug is fixed)

Each turn prints every SSE event so you can see exactly what LangGraph emits.
"""

import json
import sys
import time
import urllib.request
import uuid

BASE_URL = "http://localhost:8000"
EMAIL = "rohithebbar@gmail.com"
PASSWORD = "12345678"

# ── ANSI colours ──────────────────────────────────────────────────────────────
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

SEP = f"{DIM}{'─' * 70}{RESET}"


def step(n: int, label: str) -> None:
    print(f"\n{BOLD}{CYAN}{'='*70}{RESET}")
    print(f"{BOLD}{CYAN}  STEP {n}: {label}{RESET}")
    print(f"{BOLD}{CYAN}{'='*70}{RESET}")


def log_event(tag: str, payload: dict) -> None:
    colour = {
        "token":     GREEN,
        "done":      BOLD + GREEN,
        "interrupt": YELLOW,
        "error":     RED,
    }.get(tag, DIM)
    print(f"  {colour}[{tag}]{RESET} ", end="")
    if tag == "token":
        print(f"{DIM}{payload.get('content','')[:80]}{RESET}")
    elif tag == "interrupt":
        print(f"{YELLOW}{payload.get('content','')}{RESET}")
    elif tag == "done":
        content = payload.get("content", "")
        sources = payload.get("sources", [])
        products = payload.get("products", [])
        cross_sell = payload.get("cross_sell", [])
        cart_action = payload.get("cart_action")
        cart_cleared = payload.get("cart_cleared", False)
        print(f"\n{BOLD}  Response:{RESET} {content}")
        if sources:
            print(f"  {DIM}Sources: {sources[:3]}{RESET}")
        if products:
            print(f"  {DIM}Products returned:{RESET}")
            for p in products:
                print(f"    • {p.get('name','')} — ₹{p.get('current_price',0):,.0f} ★{p.get('avg_rating',0):.1f}")
        if cross_sell:
            print(f"  {DIM}Cross-sell:{RESET}")
            for p in cross_sell:
                print(f"    • {p.get('name','')} — ₹{p.get('current_price',0):,.0f}")
        if cart_action:
            print(f"  {GREEN}Cart action: {cart_action}{RESET}")
        if cart_cleared:
            print(f"  {GREEN}✓ cart_cleared=True (payment confirmed){RESET}")
    elif tag == "error":
        print(f"{RED}{payload.get('content','')}{RESET}")


def post_json(path: str, body: dict, token: str | None = None) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def sse_chat(message: str, session_id: str, token: str | None = None) -> tuple[dict, str]:
    """
    POST /api/chat and read SSE stream.
    Returns (last_event, session_id).
    Event type is one of: token, done, interrupt, error.
    """
    body = json.dumps({"message": message, "session_id": session_id}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/api/chat",
        data=body,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
        method="POST",
    )

    event_type = ""
    accumulated_content = ""
    last_done: dict = {}
    token_count = 0

    with urllib.request.urlopen(req, timeout=120) as resp:
        # Capture session_id from response header if generated
        returned_sid = resp.headers.get("X-Session-Id", session_id)

        buffer = ""
        while True:
            chunk = resp.read(512)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="replace")
            lines = buffer.split("\n\n")
            buffer = lines.pop()
            for line in lines:
                if not line.startswith("data: "):
                    continue
                raw = line[6:].strip()
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                t = ev.get("type", "")
                if t == "token":
                    token_count += 1
                    accumulated_content += ev.get("content", "")
                    if token_count == 1:
                        log_event("token", ev)   # only log first token so output isn't spammy
                elif t == "done":
                    if not ev.get("content") and accumulated_content:
                        ev["content"] = accumulated_content
                    last_done = ev
                    log_event("done", ev)
                elif t == "interrupt":
                    last_done = ev
                    log_event("interrupt", ev)
                elif t == "error":
                    last_done = ev
                    log_event("error", ev)

        if token_count > 1:
            print(f"  {DIM}(+ {token_count-1} more token events){RESET}")

    return last_done, returned_sid


def main() -> None:
    session_id = str(uuid.uuid4())
    print(f"\n{BOLD}ShopSense LangGraph Flow Test{RESET}")
    print(f"Session ID: {DIM}{session_id}{RESET}")

    # ── Login ─────────────────────────────────────────────────────────────────
    step(0, "Login")
    try:
        auth = post_json("/auth/login", {"email": EMAIL, "password": PASSWORD})
        token = auth.get("access_token", "")
        print(f"  {GREEN}✓ Logged in — token: {token[:30]}...{RESET}")
    except Exception as e:
        print(f"  {RED}✗ Login failed: {e}{RESET}")
        print(f"  {YELLOW}Continuing as guest (no auth) — checkout/cart will be limited{RESET}")
        token = None

    # ─────────────────────────────────────────────────────────────────────────
    step(1, "Search: 'show me good laptops under 80000'")
    ev1, session_id = sse_chat("show me good laptops under 80000", session_id, token)
    print(SEP)

    # ─────────────────────────────────────────────────────────────────────────
    step(2, "Purchase intent: 'I want to buy the first one'")
    ev2, session_id = sse_chat("I want to buy the first one", session_id, token)

    if ev2.get("type") == "interrupt":
        print(f"\n  {YELLOW}⚡ Graph paused — interrupt received (expected){RESET}")
        print(f"  Interrupt message: {ev2.get('content','')[:120]}")
        print(SEP)

        step(3, "Confirm add to cart: 'Yes, confirm'")
        ev3, session_id = sse_chat("Yes, confirm", session_id, token)
        print(SEP)

        # ── Checkout ──────────────────────────────────────────────────────
        step(4, "Checkout: 'proceed to checkout'")
        ev4, session_id = sse_chat("proceed to checkout", session_id, token)

        if ev4.get("type") == "interrupt":
            print(f"\n  {YELLOW}⚡ Checkout interrupt received (expected){RESET}")
            print(SEP)
            step(5, "Confirm payment: 'Yes, confirm'")
            ev5, session_id = sse_chat("Yes, confirm", session_id, token)
            print(SEP)
            if ev5.get("cart_cleared"):
                print(f"  {GREEN}✓ Payment succeeded — cart_cleared=True{RESET}")
            else:
                print(f"  {RED}⚠ cart_cleared not set — check payment logs{RESET}")
        else:
            print(f"  {YELLOW}⚠ Checkout: got '{ev4.get('type')}' instead of interrupt. Response: {ev4.get('content','')[:80]}{RESET}")
    else:
        print(f"  {RED}⚠ Step 2: got '{ev2.get('type')}' instead of interrupt.")
        print(f"     Response: {ev2.get('content','')[:120]}")
        print(f"     → Skipping checkout steps (no cart item){RESET}")

    print(SEP)

    # ─────────────────────────────────────────────────────────────────────────
    step(6, "Post-payment: 'show me Dell laptops for gaming'")
    print(f"  {DIM}(Testing: does a new search work cleanly after payment?){RESET}")
    ev6, session_id = sse_chat("show me Dell laptops for gaming", session_id, token)
    print(SEP)

    # ─────────────────────────────────────────────────────────────────────────
    step(7, "New purchase intent post-payment: 'I want to buy the cheapest one'")
    print(f"  {DIM}(Testing: does handle_purchase_intent use NEW sources, not old MacBook?){RESET}")
    ev7, session_id = sse_chat("I want to buy the cheapest one", session_id, token)
    print(SEP)

    # ─────────────────────────────────────────────────────────────────────────
    step(8, "Test: send new query while confirmation is pending")
    print(f"  {DIM}(Testing: does a search query DECLINE the pending confirmation?){RESET}")

    # Trigger a confirmation
    ev8a, session_id = sse_chat("I want to buy the cheapest one", session_id, token)
    if ev8a.get("type") == "interrupt":
        print(f"  {YELLOW}⚡ Confirmation pending — now sending a search query instead of yes/no{RESET}")
        ev8b, session_id = sse_chat("actually show me HP laptops instead", session_id, token)
        print(f"  {DIM}Expected: DECLINE → 'No problem, I've cancelled that'{RESET}")
        actual = ev8b.get("content", "")
        if "cancelled" in actual.lower() or "cancel" in actual.lower() or "no problem" in actual.lower():
            print(f"  {GREEN}✓ Correctly declined and cleared confirmation{RESET}")
        else:
            print(f"  {YELLOW}⚠ Unexpected response: {actual[:100]}{RESET}")
    else:
        print(f"  {YELLOW}⚠ Step 8: got '{ev8a.get('type')}'. Response: {ev8a.get('content','')[:100]}{RESET}")

    print(f"\n{BOLD}{GREEN}{'='*70}{RESET}")
    print(f"{BOLD}{GREEN}  Flow test complete{RESET}")
    print(f"{BOLD}{GREEN}{'='*70}{RESET}\n")


if __name__ == "__main__":
    main()
