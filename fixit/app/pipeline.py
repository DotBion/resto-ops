"""Fix-It Cam pipeline: footage -> Gemini 4 diagnosis -> Shop MCP search (text + keyframe image)
-> Gemini Decisions fit gate -> Gemini 4 ranking -> top-3 buyable offers."""
from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
import time

from google.genai import types

from . import gemini
from .shop_mcp import ShopMCP, flatten_offers

MAX_CANDIDATES = int(os.getenv("MAX_CANDIDATES", "18"))


def is_video(mime: str) -> bool:
    return (mime or "").startswith("video/")


def extract_frame(video_path: str, seconds: float) -> bytes | None:
    """Grab one JPEG frame at `seconds` with ffmpeg (falls back to first frame)."""
    for t in (max(0.0, seconds or 0.0), 0.0):
        with tempfile.NamedTemporaryFile(suffix=".jpg") as out:
            cmd = ["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", video_path,
                   "-frames:v", "1", "-vf", "scale='min(1024,iw)':-2", "-q:v", "3", out.name]
            try:
                subprocess.run(cmd, check=True, timeout=20)
                data = open(out.name, "rb").read()
                if data:
                    return data
            except Exception:
                continue
    return None


def video_duration(video_path: str) -> float:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                              "default=nw=1:nk=1", video_path], capture_output=True, text=True, timeout=10)
        return float(out.stdout.strip())
    except Exception:
        return 0.0


def _frame_time(name: str, i: int) -> float:
    import re
    m = re.search(r"_t([0-9.]+)s", name or "")
    return float(m.group(1)) if m else float(i)


def frames_parts(paths: list[str], mimes: list[str], names: list[str]) -> list:
    """Several keyframes of one clip, in order -> interleaved [label, image, label, image, ...]."""
    parts: list = [f"The following {len(paths)} images are keyframes from ONE short phone clip, in time order. "
                   "Treat them as a video; timestamps are given per frame."]
    for i, (p, m) in enumerate(zip(paths, mimes)):
        t = _frame_time(names[i] if i < len(names) else "", i)
        parts.append(f"Frame {i+1} at {int(t)//60:02d}:{int(t)%60:02d} ({t:.1f}s):")
        parts.append(types.Part.from_bytes(data=open(p, "rb").read(), mime_type=m))
    return parts


def nearest_frame(names: list[str], seconds: float) -> int:
    ts = [_frame_time(n, i) for i, n in enumerate(names)]
    return min(range(len(ts)), key=lambda i: abs(ts[i] - seconds)) if ts else 0


async def media_part(path: str, mime: str):
    if is_video(mime):
        return await gemini.upload_media(path, mime)
    return types.Part.from_bytes(data=open(path, "rb").read(), mime_type=mime)


async def diagnose_media(path: str, mime: str, note: str = "") -> tuple[dict, dict]:
    timings = {}
    t = time.time()
    part = await media_part(path, mime)
    timings["upload_s"] = round(time.time() - t, 2)
    t = time.time()
    diag = await gemini.diagnose(part, note)
    timings["diagnose_s"] = round(time.time() - t, 2)
    return diag, timings


async def search_offers(shop: ShopMCP, diag: dict, frame: tuple[bytes, str] | None,
                        use_image: bool = True, max_queries: int = 3) -> list[dict]:
    queries = [q for q in (diag.get("search_queries") or []) if q.strip()][:max_queries]
    if not queries and diag.get("replace"):
        queries = [diag["replace"]]
    tasks = [shop.search_catalog(query=q) for q in queries]
    labels = [f"text: {q}" for q in queries]
    if use_image and frame:
        tasks.append(shop.search_catalog(query=diag.get("replace") or None, image=frame))
        labels.append("photo + text")
    results = await asyncio.gather(*tasks, return_exceptions=True)
    seen, cands = set(), []
    # interleave results so every query contributes
    lists = [flatten_offers(r, lab) if not isinstance(r, Exception) else [] for r, lab in zip(results, labels)]
    for row in range(max((len(l) for l in lists), default=0)):
        for l in lists:
            if row < len(l):
                c = l[row]
                key = c.get("variant_id") or c.get("product_url")
                if key and key not in seen and c.get("shop"):
                    seen.add(key)
                    cands.append(c)
    return cands[:MAX_CANDIDATES]


async def run(path: str, mime: str, note: str = "", shop: ShopMCP | None = None,
              use_gate: bool = True, use_image: bool = True) -> dict:
    own = shop is None
    shop = shop or ShopMCP()
    t_all = time.time()
    try:
        diag, timings = await diagnose_media(path, mime, note)
        frame = None
        if use_image:
            if is_video(mime):
                fb = await asyncio.to_thread(extract_frame, path, float(diag.get("best_frame_seconds") or 0))
                frame = (fb, "image/jpeg") if fb else None
            else:
                frame = (open(path, "rb").read(), mime)
        t = time.time()
        cands = await search_offers(shop, diag, frame, use_image=use_image)
        timings["search_s"] = round(time.time() - t, 2)
        if use_gate and cands:
            t = time.time()
            try:
                fits = await gemini.fit_gate(diag, cands)
                for c, f in zip(cands, fits):
                    c["fit"] = round(f, 3)
                cands.sort(key=lambda c: -c.get("fit", 0))
            except Exception as e:  # gate is an accelerator, never a single point of failure
                timings["gate_error"] = str(e)[:200]
            timings["gate_s"] = round(time.time() - t, 2)
        shortlist = [c for c in cands if c.get("fit", 1) >= 0.05][:8] or cands[:8]
        t = time.time()
        top = await gemini.rank(diag, shortlist) if shortlist else []
        timings["rank_s"] = round(time.time() - t, 2)
        timings["total_s"] = round(time.time() - t_all, 2)
        return {"diagnosis": diag, "top": top, "candidates_considered": len(cands),
                "timings": timings, "models": {"identify": gemini.IDENTIFY_MODEL, "rank": gemini.RANK_MODEL,
                                               "gate": gemini.DECISION_MODEL if use_gate else None}}
    finally:
        if own:
            await shop.aclose()
