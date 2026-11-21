# Fix-It Cam 🔧

**Film the broken thing. Gemini 4 finds the exact part. Buy the replacement in one tap.**

Point your phone at something broken (a frayed charger, a leaky faucet aerator, a snapped strap) for 5–10 seconds.
Gemini 4 watches *and listens to* the clip, identifies the item, the broken part and the specs you need
(connector, size, wattage, thread…), cites the timestamps it used, and gives a repair tip. Fix-It Cam then searches the live
Shop catalog by **words and by a keyframe photo**, checks every offer's fit with the **Gemini Decisions API**, has Gemini 4 pick the top 3,
and **Buy now** opens the merchant's real checkout, where guests can pay without a Shop account.

> Built for the Gemini 4 NYC Hackathon. Theme: **Element 119** (video is the product), evaluated 5 Sigma-style against a single-frame baseline. Also targets the Shopify prize (real purchases through Shop MCP).

## Docs

- [PLAN.md](PLAN.md): goal, themes targeted, milestones (done vs remaining), risks and mitigations, judging-criteria mapping.
- [ARCHITECTURE.md](ARCHITECTURE.md): components, endpoints, Gemini and Shop MCP details, data shapes, buy paths, sequence diagram, latency, eval harness, deployment, security, failure modes.

## How it works

```mermaid
flowchart LR
  A[Phone clip / photo] -->|Files API| B[Gemini 4 Hydrogen<br/>structured diagnosis JSON<br/>item · part · specs · evidence timestamps]
  B --> C[ffmpeg keyframe<br/>at best_frame_seconds]
  B -->|2-3 queries| D[Shop MCP search_catalog<br/>text]
  C -->|like: image| E[Shop MCP search_catalog<br/>photo + text]
  D & E --> F[Gemini Decisions API<br/>gemini-decision-1<br/>P(fits) per offer, one call]
  F --> G[Gemini 4 ranks top 3<br/>with reasons + what to check]
  G --> H[Buy now → offer checkout_url<br/>merchant checkout, guest OK]
  G --> I[or: create_checkout<br/>→ continue_url, Shop sign-in]
```

| Step | Model / tool | Typical latency |
|---|---|---|
| Diagnose video | `gemini-4-hydrogen` (Files API, JSON schema) | 5–10 s |
| Search | Shop MCP `search_catalog` (3 text queries + 1 image query, parallel) | ~1 s |
| Fit gate | Gemini Decisions API `gemini-decision-1` (one `noul` question per offer) | ~0.5 s |
| Rank | `gemini-4-hydrogen`, thinking `low` | 2–6 s |
| Checkout | Offer `checkout_url` from `search_catalog` (instant), or `create_checkout` → `continue_url` | 0–1 s |

**Two buy paths, both from Shop MCP:**

1. **Buy now** opens an in-app sheet to confirm the item. Its **Checkout** button (primary) opens the offer's `checkout_url` from `search_catalog` exactly as returned. It redirects to the merchant's Shop Pay checkout page. That page shows **"Check out as guest"**. Nobodit confirmed this on an iPhone, and it was also checked with curl using an iPhone user agent. So a judge can buy without a Shop account.
2. **"or checkout with Shop"** (secondary, in the same sheet) calls `create_checkout` and opens its `continue_url` (`shop.app/checkouts/r/…`) unchanged. On a phone this path asks you to sign in to Shop. Buy now also falls back to it if an offer has no `checkout_url`.

Shop rules we follow: products are fetched live on every request (no caching), merchant images load from their original URLs,
product and checkout URLs are used exactly as returned, one merchant per checkout, and the shopper reviews and pays on the merchant's page.
The app never calls `complete_checkout`.

## Run it

```bash
cp .env.example .env      # put your GEMINI_API_KEY in .env
./run.sh                  # creates .venv, installs deps, serves http://localhost:8000
```

Requires Python 3.11+ and `ffmpeg` (for the keyframe photo search; without it the app still works with text search).

**Let judges try it from their phones:** on a laptop with normal internet, run in a second terminal
`cloudflared tunnel --protocol http2 --url http://localhost:8000` (or `ngrok http 8000`) and share the printed https URL.
Phone camera capture needs HTTPS, which the tunnel provides.

**Collect eval clips from a phone:** set `EVAL_UPLOAD_KEY` in `.env`, then open `/eval-upload?k=<key>`. Clips land in `eval/clips/` with `labels.json` (git-ignored).

CLI smoke test (diagnosis → top 3 → real checkout link, no purchase):

```bash
.venv/bin/python scripts/smoke_test.py path/to/clip.mp4
```

Config (env): `IDENTIFY_MODEL` (default `gemini-4-hydrogen`), `RANK_MODEL`, `DECISION_MODEL` (`gemini-decision-1`),
`DIAGNOSE_THINKING`, `RANK_THINKING` (default `low`), `PORT`.

## Code map

- `app/gemini.py`: diagnosis schema and prompt, Decisions fit gate, ranking
- `app/shop_mcp.py`: plain HTTP JSON-RPC client for Shop MCP (protocol `2026-07-28`, stateless)
- `app/pipeline.py`: keyframe extraction, multi-query search with merge and dedupe, end-to-end `run()`
- `app/server.py`: FastAPI with `/api/analyze` (streams NDJSON progress events; accepts a video, a photo or keyframes), `/api/checkout`, `/api/health`, `/eval-upload`
- `static/upload.js`: in-browser shrink of big clips (720p re-encode or keyframe fallback) and XHR upload with progress
- `static/index.html`: mobile-first single-page app (film, upload, diagnosis with tap-to-seek evidence timestamps, product cards, Buy)

## Evaluation (5 Sigma-style: messy inputs vs a simple baseline)

`eval/eval.py` runs two systems on every clip:

- **full**: Gemini 4 watches the whole clip, then specs and queries, Shop search by text and keyframe photo, the Decisions fit gate, and the Gemini 4 top 3.
- **baseline**: the middle still frame only. Gemini 4 writes one plain query, we run one Shop text search and take the first 3 results.

Metrics:

- **kw@k**: the top-k offers contain all expected keywords.
- **judge@k**: a strict Gemini 4 judge, which sees only the ground-truth label and the offers, says an offer would actually fix it.
- **Latency.**

Every miss is written to a failure log.

```bash
.venv/bin/python eval/eval.py                                  # your clips: eval/clips + eval/clips/labels.json
.venv/bin/python eval/eval.py --clips eval/samples             # synthetic smoke set (build with eval/samples/make_samples.sh)
```

Output goes to `eval/results/<timestamp>/` as `summary.md`, `failures.md` and `results.json`.

### Results so far: 17 public sample clips (`eval/samples`, sources and licenses in `eval/samples/SOURCES.md`)

Sample sets:

- **synthetic** (8): 4 items × a clean and a messy version (dark, blurred, noisy, shaky) built from Commons photos.
- **real-household** (5): real handheld Commons videos: dripping faucet, bulb burning out, flickering bulb, tire leak, worn bike rim.
- **restaurant** (4): real photos of broken commercial-kitchen parts as 8 s handheld pans: burnt blender motor, espresso group gasket, rusted cabinet hinge, immersion-blender coupling.

| Set | System | kw@1 | kw@3 | judge@3 |
|---|---|---|---|---|
| **All 17** | **Fix-It Cam (full video)** | **13/17 (76%)** | **13/17 (76%)** | **11/17 (65%)** |
| All 17 | Baseline (1 frame + plain search) | 10/17 (59%) | 11/17 (65%) | 7/17 (41%) |
| synthetic (8) | full / baseline | 8 / 6 | 8 / 6 | **8 / 4** |
| real-household (5) | full / baseline | 3 / 3 | 3 / 4 | 2 / 3 |
| restaurant (4) | full / baseline | 2 / 1 | 2 / 1 | **1 / 0** |

Median latency: full 21.1 s, baseline 3.6 s.

Per clip:

| Clip | Set | Full kw@3 | Full judge@3 | Base kw@3 | Base judge@3 | Full latency |
|---|---|---|---|---|---|---|
| real_bulb_burnout | real-household | ✅ | ❌ | ✅ | ✅ | 22.79s |
| real_dripping_faucet | real-household | ✅ | ✅ | ✅ | ✅ | 19.07s |
| real_flickering_bulb | real-household | ❌ | ❌ | ✅ | ❌ | 24.54s |
| real_tire_leak | real-household | ✅ | ✅ | ✅ | ✅ | 18.15s |
| real_worn_bike_rim | real-household-hard | ❌ | ❌ | ❌ | ❌ | 30.41s |
| kitchen_blender_burnt_motor | restaurant | ❌ | ❌ | ❌ | ❌ | 21.23s |
| kitchen_espresso_group_gasket | restaurant | ✅ | ❌ | ❌ | ❌ | 27.49s |
| kitchen_immersion_blender_coupling | restaurant | ❌ | ❌ | ❌ | ❌ | 52.89s |
| kitchen_rusty_cabinet_hinge | restaurant | ✅ | ✅ | ✅ | ❌ | 20.47s |
| aerator_clean | synthetic | ✅ | ✅ | ✅ | ✅ | 15.01s |
| aerator_messy | synthetic | ✅ | ✅ | ❌ | ❌ | 28.36s |
| brakepads_clean | synthetic | ✅ | ✅ | ✅ | ✅ | 21.09s |
| brakepads_messy | synthetic | ✅ | ✅ | ✅ | ❌ | 19.41s |
| macbook_cable_clean | synthetic | ✅ | ✅ | ✅ | ❌ | 22.66s |
| macbook_cable_messy | synthetic | ✅ | ✅ | ❌ | ❌ | 18.93s |
| umbrella_clean | synthetic | ✅ | ✅ | ✅ | ✅ | 18.27s |
| umbrella_messy | synthetic | ✅ | ✅ | ✅ | ✅ | 18.03s |

What these runs show (full logs in `eval/smoke_results/failures.md`):

- **Messy footage is where video wins.** On the dark, shaky clips the baseline's single middle frame came back as "ballpoint pen" (MacBook cable) or "garden-hose coupler" (aerator). The full pipeline got all 8 synthetic clips right.
- **Right words, wrong product.** For a MacBook MagSafe cable, the baseline returns iPhone *wireless* MagSafe chargers, and for a cabinet hinge it returns 18-inch gate strap hinges. The keyword metric counts these as hits; the judge rejects them.
- **Real, honest losses for the full pipeline:**
  - *Flickering ceiling bulb*: diagnosis said "replacement LED bulb", but catalog search returned whole ceiling fixtures and the gate let them through.
  - *Bulb-burnout demo*: Gemini correctly saw a DIY battery-and-filament rig and asked for the rig's parts (sockets, fuse holder). The label wanted "a bulb". Debatable label.
  - *Espresso gasket*: it found gaskets, but only generic O-ring kits. The catalog has no group-head gasket for that machine.
- **Where neither system works:**
  - *Worn bike rim*: handlebar-cam ride footage where the rim failure isn't visible. Both systems guess, and the full one picks the chain.
  - *Burnt blender motor*: the photo shows only the armature, and both systems return power-tool armatures.
  - *Bosch hand-blender latch*: the full pipeline identifies the exact Bosch MaxoMixx model and the release-ring part, but Bosch doesn't sell that part (per the photo's own source description), so the catalog only has unrelated Bosch rings.

### Real messy phone clips

_Pending: 20–30 clips filmed at the venue (the number that counts)._  Upload them at `/eval-upload?k=<EVAL_UPLOAD_KEY>` and run `eval/eval.py`._

**How to film the eval set (aim for 20–30 clips, 5–10 s each):**

- Use 8–12 different broken or worn items: chargers and cables, earbuds, faucet parts, zippers, straps, bulbs, batteries, wiper blades, bike parts, glasses screws, phone cases.
- Film each item 2–3 times, messier each time:
  1. normal light
  2. dim or backlit, with the label only visible for a moment
  3. shaky, part covered by a hand, background noise, and say the model number out loud instead of showing it
- In at least a few clips, put the deciding spec (wattage, connector, size) in only one moment or only in the audio. That is where watching the whole video should beat one frame.
- Label each upload with keywords the correct replacement must contain, e.g. `usb-c, 60w` or `aerator`.

## Where it breaks

- **Huge phone videos.** 4K HEVC clips are shrunk in the browser to 720p at about 2 Mbps (MediaRecorder, max 15 s) before upload. Where MediaRecorder isn't available, the browser sends 8 JPEG keyframes instead. Keyframes are measurably worse: on a 68 MB 4K test clip, the full video found the MagSafe adapter, but 8 keyframes of the same clip were read as a pen.
- **Catalog says no.** Some OEM parts aren't sold at all (e.g. the Bosch MaxoMixx latch), and some searches return whole fixtures when you need a bulb.

- **No model number visible or spoken.** It falls back to a family ("MagSafe 1 or 2, 45–85 W") and says so in `uncertainties`. The ranking adds a "check before buying" note, but the user still has to confirm.
- **Catalog coverage.** Shop's catalog is strong on consumer goods and weaker on OEM appliance and automotive parts. The pipeline then returns the closest whole-item replacement or a generic part (e.g. a universal aerator).
- **Speed.** About 17–30 s end to end. Most of it is Gemini 4 video understanding (6–20 s, varies by call). Upload, search (~1 s) and the Decisions gate (~0.5 s) are cheap.
- **The keyframe is one frame.** Photo search uses the frame Gemini picks as clearest. If the part is never clearly in view, photo search adds noise, and the gate filters it.
- **Keyword metric is gameable.** Hence the strict LLM judge column. The MagSafe-wireless case is the clearest example.
- **Checkout.** A checkout link is created live per merchant. Shipping address, payment and any extra steps (`requires_escalation`) happen on the merchant's page.

## Limitations

- The sample eval is small (17 clips, 4 of them photo-derived). Real phone footage filmed at the venue is the eval that counts.
- The fit gate and the judge are both Gemini models, so their failure modes may correlate. The judge sees the ground-truth label, which the gate never does.
- Search is US/USD by default (`search_catalog` context).
- No accounts and no order history. One item per checkout.

## 1-minute demo script

| Time | Shot | Voice-over |
|---|---|---|
| 0:00–0:08 | Hand holds a frayed charger or leaky aerator | "Something breaks. You don't know the part name, the wattage or the thread size. You just know it's broken." |
| 0:08–0:25 | Phone: **Film it**, a shaky 6 s clip, saying "it's from my 2015 MacBook" | "Fix-It Cam: film it. Gemini 4 watches *and listens* to the whole clip…" |
| 0:25–0:35 | Diagnosis card: part, spec chips (seen / heard / inferred), tap a timestamp to jump the video | "…finds the exact part and specs, and shows you where in the video it saw them." |
| 0:35–0:45 | Top-3 cards with fit %, reasons and "check before buying" | "Shop catalog search by words *and* by a keyframe photo. The Gemini Decisions API scores the fit of every offer in half a second, and Gemini 4 picks the top 3." |
| 0:45–0:52 | Tap **Buy now**, a real Shop checkout opens | "One tap to a real checkout. You pay on the merchant's page." |
| 0:52–1:00 | Eval table: full vs baseline, plus one failure example | "On messy clips, one frame plus a search picked a correct part 41% of the time. Watching the whole video: 65%, and 8 of 8 on the messiest synthetic clips. Here's where it still breaks." |

