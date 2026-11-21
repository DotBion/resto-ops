"""Minimal Shop MCP client (https://mcp.shop.com/) over plain HTTP JSON-RPC.

The server speaks MCP protocol 2026-07-28 (stateless): no initialize handshake,
every request carries MCP-Protocol-Version + Mcp-Method headers and a _meta block.
Results are fetched live on every call (no caching, per Shop rules).
"""
from __future__ import annotations

import itertools
import json
import os
from typing import Any

import httpx

SHOP_MCP_URL = os.getenv("SHOP_MCP_URL", "https://mcp.shop.com/")
PROTOCOL = "2026-07-28"
_ids = itertools.count(1)


class ShopMCPError(RuntimeError):
    pass


def _parse_body(text: str) -> dict:
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    # text/event-stream: take the last data: line that parses as JSON-RPC
    msg = None
    for line in text.splitlines():
        if line.startswith("data:"):
            try:
                msg = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
    if msg is None:
        raise ShopMCPError(f"Unparseable MCP response: {text[:200]}")
    return msg


class ShopMCP:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(timeout=30)

    async def _rpc(self, method: str, params: dict | None = None, name: str | None = None) -> dict:
        params = dict(params or {})
        params["_meta"] = {
            "io.modelcontextprotocol/protocolVersion": PROTOCOL,
            "io.modelcontextprotocol/clientCapabilities": {},
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL,
            "Mcp-Method": method,
        }
        if name:
            headers["Mcp-Name"] = name
        body = {"jsonrpc": "2.0", "id": next(_ids), "method": method, "params": params}
        r = await self._client.post(SHOP_MCP_URL, json=body, headers=headers)
        msg = _parse_body(r.text)
        if "error" in msg:
            raise ShopMCPError(f"{method} {name or ''}: {msg['error']}")
        return msg["result"]

    async def list_tools(self) -> list[dict]:
        return (await self._rpc("tools/list"))["tools"]

    async def call(self, tool: str, arguments: dict) -> dict:
        res = await self._rpc("tools/call", {"name": tool, "arguments": arguments}, name=tool)
        payload: Any = res.get("structuredContent")
        if payload is None:
            texts = [c.get("text", "") for c in res.get("content", []) if c.get("type") == "text"]
            joined = "\n".join(texts)
            try:
                payload = json.loads(joined)
            except json.JSONDecodeError:
                payload = {"text": joined}
        if res.get("isError"):
            raise ShopMCPError(f"{tool} returned error: {str(payload)[:300]}")
        return payload

    # ---- convenience wrappers -------------------------------------------------
    async def search_catalog(self, query: str | None = None, image: tuple[bytes, str] | None = None,
                             limit: int = 6, country: str = "US") -> dict:
        import base64
        catalog: dict[str, Any] = {
            "context": {"address_country": country, "currency": "USD"},
            "filters": {"available": True},
            "pagination": {"limit": limit},
        }
        if query:
            catalog["query"] = query
        if image:
            data, mime = image
            catalog["like"] = [{"image": {"content_type": mime, "data": base64.b64encode(data).decode()}}]
        return await self.call("search_catalog", {"catalog": catalog})

    async def create_checkout(self, shop: str, variant_id: str, quantity: int = 1, country: str = "US") -> dict:
        return await self.call("create_checkout", {
            "shop": shop,
            "checkout": {
                "line_items": [{"item": {"id": variant_id}, "quantity": quantity}],
                "context": {"address_country": country},
            },
        })

    async def aclose(self):
        await self._client.aclose()


def flatten_offers(payload: dict, source: str) -> list[dict]:
    """Turn a search_catalog payload into one candidate per product (first available variant).
    URLs are kept exactly as returned."""
    out = []
    for p in payload.get("products", []) or []:
        variants = p.get("variants") or []
        v = next((x for x in variants if (x.get("availability") or {}).get("available", True)), None)
        if not v:
            continue
        seller = v.get("seller") or {}
        media = (v.get("media") or p.get("media") or [])
        img = next((m.get("url") for m in media if m.get("type") == "image" and m.get("url")), None)
        price = v.get("price") or {}
        rating = v.get("rating") or p.get("rating") or {}
        out.append({
            "product_id": p.get("id"),
            "variant_id": v.get("id"),
            "title": p.get("title") or v.get("title"),
            "variant_title": v.get("title"),
            "description": _strip_html(((v.get("description") or p.get("description") or {}).get("plain") or ""))[:400],
            "features": ((p.get("metadata") or {}).get("top_features") or [])[:4],
            "price_minor": price.get("amount"),
            "currency": price.get("currency", "USD"),
            "image_url": img,
            "product_url": v.get("url"),
            "checkout_url": v.get("checkout_url"),  # merchant /buy link, used exactly as returned
            "seller_name": seller.get("name"),
            "shop": seller.get("domain"),
            "rating": rating.get("value"),
            "rating_count": rating.get("count"),
            "found_by": source,
        })
    return out


def _strip_html(s: str) -> str:
    import re
    import html
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()
