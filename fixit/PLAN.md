# Fix-It Cam: Plan

## Goal

Win a **top-3 overall** prize at the Gemini 4 NYC Hackathon (Cerebral Valley × Google DeepMind) **and** the **Shopify prize**, with one product:

> Film the broken thing. Gemini 4 finds the exact part. Buy the replacement in one tap.

The submission is a public GitHub repo (this one) plus a 1-minute demo video, **due 5:00 PM ET**.

## Themes targeted

| Theme / prize | How Fix-It Cam fits | Where in the code |
|---|---|---|
| **Element 119**: only works because Gemini 4 can see and hear media, with video at the core | The whole clip (frames + audio) goes to `gemini-4-hydrogen` through the Files API. It returns a structured diagnosis with specs tagged *seen / heard / inferred* and timestamped evidence. The keyframe used for photo search is picked by Gemini (`best_frame_seconds`). The **Gemini Decisions API** (`gemini-decision-1`) scores every offer's fit in one call. | `app/gemini.py` (`diagnose`, `fit_gate`), `app/pipeline.py` |
| **5 Sigma**: reliability on messy inputs vs a simple baseline, showing where it fails | `eval/eval.py` compares the full video pipeline with a single-middle-frame + plain-text-search baseline. It scores keyword top-1/top-3, a strict LLM-judge top-1/top-3 and latency, and writes a failure log. | `eval/eval.py`, `eval/smoke_results/` |
| **Shopify prize**: commerce through Shop MCP, and a judge can make a real purchase | Live `search_catalog` (text + image `like`). **Buy now** opens the offer's `checkout_url`, which leads to the merchant's checkout where guests can pay. `create_checkout` → `continue_url` is the fallback. The app never calls `complete_checkout`. | `app/shop_mcp.py`, `static/index.html`, `app/server.py` (`/api/checkout`) |

## Build plan and milestones

| # | Milestone | Status |
|---|---|---|
| 1 | Find the real Gemini 4 model ids, video → Files API → structured JSON, and connect Shop MCP (list tools and schemas) | ✅ Done. `gemini-4-{argon,carbon,neon,hydrogen}` and `gemini-decision-1` found; Shop MCP protocol `2026-07-28` works over plain HTTP |
| 2 | Full pipeline + mobile web app + one-command run, tested end to end up to a real checkout URL | ✅ Done. `./run.sh`; `/api/analyze` streams progress; Buy opens a real checkout |
| 3 | Eval harness: full vs baseline, top-3 hit rate, LLM judge, latency, failure log; clip-collection page | ✅ Done. `eval/eval.py`, `/eval-upload`; 17 public sample clips evaluated |
| 4 | README: pitch, theme fit, architecture, setup, results, limitations, demo script | ✅ Done |
| 4b | Phone-upload hardening: progress bar, in-browser shrink to 720p, keyframe fallback, multi-image analyze | ✅ Done |
| 4c | Guest-friendly purchase: Buy now → offer `checkout_url`; `create_checkout` as fallback | ✅ Done. "Check out as guest" confirmed on iPhone |
| 5 | **Rerun the eval on 20–30 real messy phone clips** filmed at the venue (`/eval-upload` → `eval/eval.py`); put the numbers in the README and demo script | ⏳ Remaining |
| 6 | **Record the 1-minute demo video** (script in README) | ⏳ Remaining |
| 7 | **Submit** (repo public, video, form) **by 5:00 PM ET**, aiming for 4:45 | ⏳ Remaining |
| 8 (stretch) | **End-of-day closing report (Carbon)**: see below | 🟡 Stretch: build one screen only if the core demo and video are done by ~4 PM; otherwise pitch it as the next step |

### Stretch milestone 8: End-of-day closing report (Carbon)

**Idea:** when a restaurant closes, batch the day's full traces to **`gemini-4-carbon`**, the deep-reasoning tier according to Google's model docs, for one overnight analysis. **`gemini-4-hydrogen` stays the live, in-service path** (fast diagnosis and ranking), and the **Decisions API** stays the per-offer fit gate.

**Traces per scan (what gets batched):**

- the clip reference
- the diagnosis JSON with `confidence` and `uncertainties`
- the Decisions fit-gate scores per offer
- the ranking (top 3 with reasons and checks)
- user events: buy, skip, checkout opened (`checkout_url` vs Shop fallback), abandoned
- per-stage latencies (`timings`)

**Problems it addresses:**

- Repeat equipment failures go unnoticed when each scan is handled on its own.
- Rushed, wrong or overpriced part buys in the middle of service.
- No maintenance log, so upkeep is reactive instead of preventive.
- App reliability blind spots (the 5 Sigma theme): where the live path was unsure or wrong.

**Nightly questions Carbon answers:**

1. Which equipment failed or was scanned repeatedly, and what is the likely root cause?
2. Were any buys band-aids for a deeper problem?
3. Which spare parts should be stocked, given failure frequency and shipping time?
4. Where was the app unsure or wrong (low-confidence diagnoses, overridden fit gates, abandoned checkouts), with clip references?
5. A pre-service checklist for tomorrow.
6. A spend summary, plus avoidable or overpriced buys compared with other sellers.

**Scope for today:**

- Only if the core demo and the 1-minute video are done by ~4 PM ET: build a single "closing report" screen that feeds **today's eval traces** (`eval/results/*/results.json`, `eval/smoke_results/results.json`) to `gemini-4-carbon` and renders the six answers.
- Otherwise it is **not built**. It goes in the pitch and the README as the next step.

### Results so far (17 public sample clips: 8 synthetic, 5 real household videos, 4 restaurant photo-pans)

| System | kw@3 | judge@3 | median latency |
|---|---|---|---|
| Full video pipeline | 13/17 (76%) | 11/17 (65%) | 21.1 s |
| Baseline (1 frame + plain search) | 11/17 (65%) | 7/17 (41%) | 3.6 s |

Per-clip results and failure analysis are in `README.md` and `eval/smoke_results/`.

## Remaining timeline (ET)

- **Now → ~3:30**: film 20–30 messy clips (see the README filming guide), upload them at `/eval-upload?k=<key>`, then run `python eval/eval.py` and update the README tables.
- **3:30 → 4:15**: record the 1-minute video: live film → diagnosis → top 3 → Buy now → merchant checkout, then the eval slide.
- **4:15 → 4:45**: final README pass, check the repo is public, submit.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Venue Wi-Fi with big iPhone videos (4K HEVC, tens to hundreds of MB) stalls uploads | Clips over 15 MB are shrunk in the browser to 720p / 2 Mbps / max 15 s (MediaRecorder). If that isn't possible, 8 JPEG keyframes are sent. An upload progress bar and clear timeout errors help. The UI says to keep clips 5–10 s. |
| Shop sign-in wall on phones blocks judges from buying | Buy now opens the offer's `checkout_url` (merchant checkout with guest checkout); `create_checkout` is kept as "or checkout with Shop". |
| Gemini latency spikes (diagnosis 6–20 s, longer occasionally) | Streamed stage-by-stage progress. The ranking uses thinking level `low`. The Decisions gate is ~0.5 s. Search queries run in parallel. Record a backup demo run. |
| Catalog doesn't carry the exact OEM part | The diagnosis lists what to buy and what's uncertain. The ranking adds a "check before buying" note. Failures are shown honestly in the eval. |
| Decisions API error | `fit_gate` is wrapped: on failure the pipeline continues without it and records `gate_error` in timings. |
| Keyword metric over-counts (right words, wrong product) | A strict LLM-judge column, which is reported as the headline number. |
| Laptop tunnel drops during judging | Run on a Mac with a cloudflared quick tunnel (`--protocol http2`). Restarting gives a new URL, and a recorded backup demo is ready. |
| Secrets leak | Key only in env / `.env` (git-ignored). `.env.example` has placeholders. The eval upload page is protected by `EVAL_UPLOAD_KEY`. |

## Judging-criteria mapping

| Likely criterion | Our evidence |
|---|---|
| **Uses Gemini 4 in a way that wasn't possible before** | Whole-clip video + audio diagnosis with tap-to-seek timestamped evidence. The Decisions API scores fit in one call. The 68 MB 4K test: the full video identified a MagSafe adapter, while 8 keyframes of the same clip were read as "a pen". |
| **Technical depth** | A stateless MCP client for protocol `2026-07-28` over plain JSON-RPC; multimodal search (text + keyframe image); a calibrated fit gate; a streaming FastAPI backend; client-side video transcoding. |
| **Reliability / evaluation (5 Sigma)** | Baseline comparison, two metrics, latency, a public failure log, and documented "where it breaks". |
| **Real-world impact** | Fixing beats throwing away. It works for households and for restaurant and commercial-kitchen parts (blender, espresso gasket, hinges). |
| **Demo quality** | A judge's broken item → a checkout page in about 30 s, live on a phone. |
| **Shopify prize** | Real live catalog, real checkout links used exactly as returned, guest purchase possible, no caching or re-hosting of merchant images. |
