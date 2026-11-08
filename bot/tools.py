"""Mocked tools for the support bot.

Every tool reads from a frozen snapshot in store/ (policy pages, orders, catalog),
so a replay sees exactly what the bot saw the first time. A case can override any
part of the snapshot, e.g. to give one customer a different order history.
"""

import json
import re
from pathlib import Path

STORE = Path(__file__).resolve().parent.parent / "store"

STOPWORDS = set("a an and are as at be can do does for from how i if in is it me my of on or the to we what when where which with you your".split())


def load_store(overrides=None):
    docs = {p.stem: p.read_text(encoding="utf-8") for p in sorted((STORE / "docs").glob("*.md"))}
    store = {
        "docs": docs,
        "orders": json.loads((STORE / "orders.json").read_text(encoding="utf-8")),
        "catalog": json.loads((STORE / "catalog.json").read_text(encoding="utf-8")),
    }
    for key, value in (overrides or {}).items():
        if isinstance(store.get(key), dict):
            store[key] = {**store[key], **value}
        else:
            store[key] = value
    return store


def make_tools(store, log):
    """Build the tool functions for one conversation. Every call is appended to `log`."""

    def search_docs(query: str) -> str:
        """Search the store's help pages (returns, warranty, shipping, promotions, contact, privacy). Returns the most relevant pages in full."""
        words = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if w not in STOPWORDS}
        scored = []
        for name, text in store["docs"].items():
            body = text.lower()
            score = sum(body.count(w) for w in words) + 5 * sum(w in name for w in words)
            if score:
                scored.append((score, name, text))
        scored.sort(reverse=True)
        result = "\n\n---\n\n".join(text for _, _, text in scored[:3]) or "No relevant help pages found."
        log.append({"tool": "search_docs", "args": {"query": query}, "result": [n for _, n, _ in scored[:3]]})
        return result

    def get_orders(user_id: str) -> str:
        """Get the order history and status for the signed-in customer."""
        orders = store["orders"].get(user_id)
        result = json.dumps(orders, indent=1) if orders else f"No orders found for {user_id}."
        log.append({"tool": "get_orders", "args": {"user_id": user_id}, "result": result})
        return result

    def search_products(query: str, max_price: float = 10_000.0) -> str:
        """Search the product catalog. Returns name, price, whether it is waterproof and whether it is in stock."""
        words = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if w not in STOPWORDS}
        hits = [
            p for p in store["catalog"]
            if p["price"] <= max_price
            and (not words or words & set(re.findall(r"[a-z0-9]+", f"{p['name']} {p['category']}".lower())) or ("waterproof" in words and p["waterproof"]))
        ]
        result = json.dumps(hits, indent=1) if hits else "No matching products."
        log.append({"tool": "search_products", "args": {"query": query, "max_price": max_price}, "result": [p["sku"] for p in hits]})
        return result

    def escalate_to_human(reason: str) -> str:
        """Hand the conversation to a human support agent. Creates a ticket for the support team."""
        result = "Ticket created. A human agent will reply by email within 1 business day."
        log.append({"tool": "escalate_to_human", "args": {"reason": reason}, "result": result})
        return result

    return [search_docs, get_orders, search_products, escalate_to_human]
