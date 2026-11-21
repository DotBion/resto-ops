"""Gemini 4 calls: video/photo -> structured diagnosis, Decisions API fit gate, ranking reasons."""
from __future__ import annotations

import asyncio
import json
import os
import time

from google import genai
from google.genai import types

IDENTIFY_MODEL = os.getenv("IDENTIFY_MODEL", "gemini-4-hydrogen")
RANK_MODEL = os.getenv("RANK_MODEL", "gemini-4-hydrogen")
DECISION_MODEL = os.getenv("DECISION_MODEL", "gemini-decision-1")
DIAGNOSE_THINKING = os.getenv("DIAGNOSE_THINKING", "")  # "", "low", "high"
RANK_THINKING = os.getenv("RANK_THINKING", "low")


def _thinking(level: str):
    return types.ThinkingConfig(thinking_level=level) if level else None

_client: genai.Client | None = None


def client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(http_options={"api_version": "v1beta"})
    return _client


DIAGNOSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "item": {"type": "string", "description": "What the object is, as specific as possible (brand + model if visible)."},
        "brand": {"type": "string"},
        "model": {"type": "string", "description": "Model / part number if readable or inferable, else empty."},
        "broken_part": {"type": "string", "description": "The specific component that is broken or worn."},
        "failure": {"type": "string", "description": "What is wrong (e.g. frayed insulation at strain relief)."},
        "specs": {
            "type": "array",
            "description": "Specs needed to buy a compatible replacement: size, connector, wattage, thread, width, color...",
            "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "value": {"type": "string"},
                "source": {"type": "string", "enum": ["seen", "heard", "inferred"]}},
                "required": ["name", "value", "source"]},
        },
        "evidence": {
            "type": "array",
            "description": "Moments in the footage that support the diagnosis.",
            "items": {"type": "object", "properties": {
                "t": {"type": "string", "description": "mm:ss timestamp"},
                "observation": {"type": "string"}}, "required": ["t", "observation"]},
        },
        "replace": {"type": "string", "description": "Exactly what to buy (the part, or the whole item if the part is not sold separately)."},
        "repair_tip": {"type": "string", "description": "One or two sentences: how to swap/fix it safely."},
        "search_queries": {"type": "array", "items": {"type": "string"},
                           "description": "2-3 shopping queries, most specific first. Product words only."},
        "best_frame_seconds": {"type": "number", "description": "Timestamp (s) of the clearest frame showing the part."},
        "confidence": {"type": "number", "description": "0-1 confidence the part is correctly identified."},
        "uncertainties": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["item", "broken_part", "failure", "specs", "evidence", "replace", "repair_tip",
                 "search_queries", "best_frame_seconds", "confidence", "uncertainties"],
}

DIAGNOSIS_PROMPT = """You are Fix-It Cam, a repair technician watching a short phone clip of a broken or worn object.
Watch the WHOLE clip (and listen: people often say the model or what happened).
1. Identify the object and the exact broken/worn part.
2. Read any labels, model numbers, ratings, sizes visible in any frame; note what you heard.
3. List the specs a shopper needs to buy a compatible replacement (connector type, size, wattage, thread, width...).
4. Decide what to buy: the replacement part, or the whole item if the part isn't sold separately.
5. Write 2-3 product search queries for an online catalog, most specific first.
Cite timestamps. Be honest about uncertainty; never invent model numbers."""


async def upload_media(path: str, mime: str):
    """Upload a video via the Files API and wait until ACTIVE. Images are sent inline instead."""
    c = client()
    f = await c.aio.files.upload(file=path, config={"mime_type": mime})
    t0 = time.time()
    while f.state and f.state.name == "PROCESSING":
        if time.time() - t0 > 120:
            raise TimeoutError("Gemini file processing timed out")
        await asyncio.sleep(0.7)
        f = await c.aio.files.get(name=f.name)
    if f.state and f.state.name == "FAILED":
        raise RuntimeError("Gemini could not process the video")
    return f


async def diagnose(media_part, extra_note: str = "", model: str | None = None) -> dict:
    """media_part: a Files API File (video) or types.Part (inline image)."""
    prompt = DIAGNOSIS_PROMPT + (f"\nUser note: {extra_note}" if extra_note else "")
    r = await client().aio.models.generate_content(
        model=model or IDENTIFY_MODEL,
        contents=(list(media_part) if isinstance(media_part, list) else [media_part]) + [prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=DIAGNOSIS_SCHEMA,
            temperature=0.2,
            thinking_config=_thinking(DIAGNOSE_THINKING),
        ),
    )
    return json.loads(r.text)


def diagnosis_text(d: dict) -> str:
    specs = "; ".join(f"{s['name']}: {s['value']}" for s in d.get("specs", []))
    return (f"Broken item: {d.get('item')}. Broken part: {d.get('broken_part')} ({d.get('failure')}). "
            f"Need to buy: {d.get('replace')}. Specs: {specs}.")


async def fit_gate(diag: dict, candidates: list[dict]) -> list[float]:
    """Gemini Decisions API: one call, one isolated yes/no question per candidate.
    Returns calibrated P(candidate is a correct compatible replacement)."""
    if not candidates:
        return []
    qs = {}
    for i, c in enumerate(candidates):
        price = f"${c['price_minor']/100:.2f}" if c.get("price_minor") is not None else ""
        qs[f"c{i}"] = {
            "type": "noul",
            "instructions": (f"Would buying this product be a correct, compatible replacement that fixes the problem? "
                             f"Product: '{c['title']}' / variant '{c.get('variant_title')}' {price}. "
                             f"Details: {c.get('description','')[:200]}"),
        }
    r = await client().aio.decisions.create(model=DECISION_MODEL, input=diagnosis_text(diag), questions=qs)
    return [float(r.answers[f"c{i}"].noul) for i in range(len(candidates))]


RANK_SCHEMA = {
    "type": "object",
    "properties": {"picks": {"type": "array", "items": {"type": "object", "properties": {
        "index": {"type": "integer"},
        "reason": {"type": "string", "description": "<=20 words: why it fits (cite specs)."},
        "check": {"type": "string", "description": "<=12 words: what to double-check before buying, or empty."}},
        "required": ["index", "reason", "check"]}}},
    "required": ["picks"],
}


async def rank(diag: dict, candidates: list[dict], k: int = 3, model: str | None = None) -> list[dict]:
    """Ask Gemini 4 to choose the best k candidates for fit and explain why."""
    lines = []
    for i, c in enumerate(candidates):
        price = f"${c['price_minor']/100:.2f}" if c.get("price_minor") is not None else "?"
        gate = f" fit_prob={c['fit']:.2f}" if c.get("fit") is not None else ""
        lines.append(f"[{i}] {c['title']} | {c.get('variant_title')} | {price} | {c.get('seller_name')}{gate} | {c.get('description','')[:160]}")
    prompt = (diagnosis_text(diag) + "\n\nCandidate products:\n" + "\n".join(lines) +
              f"\n\nPick the {k} best replacements for FIT first (correct part/specs), then price and rating. "
              "Exclude anything that would not fix the problem. Return fewer if fewer fit.")
    r = await client().aio.models.generate_content(
        model=model or RANK_MODEL, contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json",
                                           response_json_schema=RANK_SCHEMA, temperature=0.1,
                                           thinking_config=_thinking(RANK_THINKING)))
    picks = json.loads(r.text).get("picks", [])
    seen, out = set(), []
    for p in picks:
        i = p.get("index")
        if isinstance(i, int) and 0 <= i < len(candidates) and i not in seen:
            seen.add(i)
            out.append({**candidates[i], "reason": p.get("reason", ""), "check": p.get("check", "")})
    return out[:k]
