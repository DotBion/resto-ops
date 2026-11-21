"""Fix-It Cam eval: full video pipeline vs a single-frame baseline on messy clips.

Clips live in eval/clips/ (any video or photo). Labels in eval/clips/labels.json:
  {"clip.mp4": {"keywords": ["magsafe", "60w"], "description": "frayed 2015 MacBook charger"}}
(The /eval-upload page writes this file for you.)

Systems
  full      Gemini 4 watches the whole clip -> specs + queries -> Shop search (text + keyframe photo)
            -> Gemini Decisions fit gate -> Gemini 4 top-3 ranking.
  baseline  Middle still frame -> Gemini 4 writes ONE plain search query -> Shop text search -> first 3 results.

Metrics per system
  kw@1 / kw@3   any of the top-1 / top-3 offers contains ALL expected keywords (title + variant + description)
  judge@3       LLM judge (Gemini 4, blind to which system) says at least one top-3 offer fixes the problem
  latency       wall-clock seconds per clip

Usage:  python eval/eval.py [--clips eval/clips] [--limit N] [--systems full,baseline] [--concurrency 3]
Writes: eval/results/<timestamp>/{results.json, summary.md, failures.md}
"""
from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from google.genai import types  # noqa: E402

from app import gemini, pipeline  # noqa: E402
from app.shop_mcp import ShopMCP, flatten_offers  # noqa: E402

JUDGE_MODEL = gemini.RANK_MODEL


def norm(s: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in (s or "")).split())


def kw_hit(offer: dict, keywords: list[str]) -> bool:
    text = norm(" ".join([offer.get("title") or "", offer.get("variant_title") or "", offer.get("description") or ""]))
    padded = f" {text} "
    return all((f" {norm(k)} " in padded) or (norm(k) in text and len(norm(k)) > 3) for k in keywords)


async def run_full(path: str, mime: str, shop: ShopMCP) -> dict:
    t = time.time()
    res = await pipeline.run(path, mime, shop=shop)
    return {"offers": res["top"], "diagnosis": res["diagnosis"], "timings": res["timings"],
            "latency_s": round(time.time() - t, 2)}


BASELINE_PROMPT = "This photo shows a broken or worn object. Reply with ONE short online-shopping search query for its replacement. Query only."


async def run_baseline(path: str, mime: str, shop: ShopMCP) -> dict:
    t = time.time()
    if pipeline.is_video(mime):
        dur = await asyncio.to_thread(pipeline.video_duration, path)
        frame = await asyncio.to_thread(pipeline.extract_frame, path, dur / 2 if dur else 0)
        img_mime = "image/jpeg"
    else:
        frame, img_mime = open(path, "rb").read(), mime
    if not frame:
        raise RuntimeError("could not extract frame")
    r = await gemini.client().aio.models.generate_content(
        model=gemini.IDENTIFY_MODEL,
        contents=[types.Part.from_bytes(data=frame, mime_type=img_mime), BASELINE_PROMPT],
        config=types.GenerateContentConfig(temperature=0.2, thinking_config=gemini._thinking("low")))
    query = (r.text or "").strip().strip('"').splitlines()[0][:120]
    payload = await shop.search_catalog(query=query, limit=6)
    offers = flatten_offers(payload, f"text: {query}")[:3]
    return {"offers": offers, "query": query, "latency_s": round(time.time() - t, 2)}


JUDGE_SCHEMA = {"type": "object", "properties": {"verdicts": {"type": "array", "items": {"type": "object", "properties": {
    "index": {"type": "integer"}, "fixes": {"type": "boolean"}, "why": {"type": "string"}},
    "required": ["index", "fixes", "why"]}}}, "required": ["verdicts"]}


async def judge(label: dict, offers: list[dict]) -> list[dict]:
    if not offers:
        return []
    lines = [f"[{i}] {o.get('title')} | {o.get('variant_title')} | {(o.get('description') or '')[:200]}" for i, o in enumerate(offers)]
    prompt = (f"Ground truth: the broken thing is: {label.get('description') or '(no description)'}. "
              f"The correct replacement must match: {', '.join(label['keywords'])}.\n\n"
              "For each product, would buying it fix the problem (correct, compatible part or whole replacement)? Be strict.\n"
              + "\n".join(lines))
    r = await gemini.client().aio.models.generate_content(
        model=JUDGE_MODEL, contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", response_json_schema=JUDGE_SCHEMA,
                                           temperature=0, thinking_config=gemini._thinking("low")))
    return json.loads(r.text).get("verdicts", [])


async def eval_clip(name: str, label: dict, clips: Path, systems: list[str], sem: asyncio.Semaphore) -> dict:
    path = str(clips / name)
    mime = label.get("mime") or mimetypes.guess_type(path)[0] or "video/mp4"
    out = {"clip": name, "keywords": label["keywords"], "description": label.get("description", "")}
    async with sem:
        shop = ShopMCP()
        try:
            for sysname in systems:
                fn = run_full if sysname == "full" else run_baseline
                try:
                    r = await fn(path, mime, shop)
                    offers = r["offers"]
                    kws = [kw_hit(o, label["keywords"]) for o in offers]
                    try:
                        verdicts = await judge(label, offers)
                    except Exception as e:
                        verdicts = [{"index": -1, "fixes": False, "why": f"judge error: {e}"}]
                    r.update({
                        "kw@1": bool(kws[:1] and kws[0]), "kw@3": any(kws[:3]),
                        "judge@1": any(v.get("fixes") for v in verdicts if v.get("index") == 0),
                        "judge@3": any(v.get("fixes") for v in verdicts if 0 <= v.get("index", -1) < 3),
                        "verdicts": verdicts,
                        "top3": [{"title": o.get("title"), "price_minor": o.get("price_minor"), "fit": o.get("fit"),
                                  "kw": k, "url": o.get("product_url")} for o, k in zip(offers, kws)],
                    })
                    r.pop("offers", None)
                except Exception as e:
                    r = {"error": str(e)[:300], "kw@1": False, "kw@3": False, "judge@1": False, "judge@3": False, "latency_s": None}
                out[sysname] = r
                print(f"  {name:40s} {sysname:8s} kw@3={r['kw@3']!s:5s} judge@3={r['judge@3']!s:5s} {r.get('latency_s')}s"
                      + (f"  ERROR {r['error'][:80]}" if r.get("error") else ""), flush=True)
        finally:
            await shop.aclose()
    return out


def summarize(rows: list[dict], systems: list[str]) -> str:
    n = len(rows)
    lines = [f"# Fix-It Cam eval — {time.strftime('%Y-%m-%d %H:%M')} — {n} clips", "",
             "| System | kw@1 | kw@3 | judge@1 | judge@3 | median latency | errors |", "|---|---|---|---|---|---|---|"]
    for s in systems:
        rs = [r[s] for r in rows if s in r]
        lat = sorted(x["latency_s"] for x in rs if x.get("latency_s"))
        med = f"{lat[len(lat)//2]:.1f}s" if lat else "–"
        pct = lambda k: f"{sum(1 for x in rs if x.get(k))}/{len(rs)} ({100*sum(1 for x in rs if x.get(k))/max(1,len(rs)):.0f}%)"  # noqa: E731
        lines.append(f"| {s} | {pct('kw@1')} | {pct('kw@3')} | {pct('judge@1')} | {pct('judge@3')} | {med} | {sum(1 for x in rs if x.get('error'))} |")
    lines += ["", "kw = all expected keywords appear in an offer; judge = Gemini 4 judge says the offer fixes the problem.", ""]
    return "\n".join(lines)


def failures(rows: list[dict], systems: list[str]) -> str:
    out = ["# Failure log", ""]
    for r in rows:
        for s in systems:
            x = r.get(s, {})
            if x.get("judge@3") and x.get("kw@3"):
                continue
            out.append(f"## {r['clip']} — {s}")
            out.append(f"- expected: {', '.join(r['keywords'])} ({r['description']})")
            if x.get("error"):
                out.append(f"- ERROR: {x['error']}")
            d = x.get("diagnosis")
            if d:
                out.append(f"- diagnosed: {d.get('item')} / {d.get('broken_part')} → buy: {d.get('replace')} (conf {d.get('confidence')})")
                out.append(f"- queries: {d.get('search_queries')}; uncertain: {d.get('uncertainties')}")
            if x.get("query"):
                out.append(f"- baseline query: {x['query']}")
            for i, t in enumerate(x.get("top3", [])):
                why = next((v.get("why") for v in x.get("verdicts", []) if v.get("index") == i), "")
                out.append(f"  {i+1}. {t['title']} (kw={t['kw']}, fit={t.get('fit')}) — judge: {why}")
            out.append("")
    return "\n".join(out)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", default=str(ROOT / "eval" / "clips"))
    ap.add_argument("--labels", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--systems", default="full,baseline")
    ap.add_argument("--concurrency", type=int, default=3)
    a = ap.parse_args()
    clips = Path(a.clips)
    labels = json.loads(Path(a.labels or clips / "labels.json").read_text())
    names = [n for n in labels if (clips / n).exists()]
    if a.limit:
        names = names[:a.limit]
    systems = [s.strip() for s in a.systems.split(",") if s.strip()]
    print(f"Evaluating {len(names)} clips × {systems}")
    sem = asyncio.Semaphore(a.concurrency)
    rows = await asyncio.gather(*[eval_clip(n, labels[n], clips, systems, sem) for n in names])
    outdir = ROOT / "eval" / "results" / time.strftime("%Y%m%d-%H%M%S")
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "results.json").write_text(json.dumps(rows, indent=2))
    summ = summarize(rows, systems)
    (outdir / "summary.md").write_text(summ)
    (outdir / "failures.md").write_text(failures(rows, systems))
    print("\n" + summ)
    print(f"Wrote {outdir}")


if __name__ == "__main__":
    asyncio.run(main())
