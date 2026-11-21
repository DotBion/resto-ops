# Restaurant Ops Copilot

**Point a camera at the floor, or film something broken, and Gemini 4 handles it.** The input is always camera footage: a live camera, an uploaded clip, or a phone video. Gemini 4 reasons over the frames and decides what to do.

- **Queue watch (camera to staff task):** watches footage of the floor for lines of people waiting for service, at an ordering counter, buffet or food table, pickup counter or registration desk. A fast Gemini 4 model looks at every window of frames. When a line looks long, a stronger Gemini 4 model re-checks extra frames on its own, and a staff task with the evidence frames is raised only if the line persists. Seated people are not counted.
- **Fix-It (phone video to the right part to a real checkout):** film anything broken. Gemini 4 names the exact part and its specs from the video, **Shop MCP** searches the live catalog by words and by a keyframe photo, the **Gemini Decisions API** scores each offer's fit, a reasoning model ranks the top 3, and **Buy now** opens a real merchant checkout (guest checkout available).
- **One trace:** every observation, review, task, scan, fit score and checkout goes into one SQLite journal (`/api/timeline`). That trace is what the planned **Carbon closing review** reads after close (see [PLAN.md](PLAN.md); stretch, not implemented).

The web dashboard is just the viewer for those streams: video with live boxes, evidence frames and the timeline.

Built at the Gemini 4 NYC Hackathon (Cerebral Valley x Google DeepMind), Nov 21 2026.

## Which model does what

| Job | Model | Why this model | Setting |
|---|---|---|---|
| Queue: look at every window of frames (count the line, people boxes, groups) | `gemini-4-hydrogen` (thinking LOW) | Fastest Gemini 4; runs every 6 s on live or replayed video | `CAFE_OBSERVER_MODEL` |
| Queue: independent re-check before a staff task is raised or resolved | `gemini-4-argon` (thinking LOW) | Stronger reasoning, used only on the few windows that might trigger an alert | `CAFE_VERIFIER_MODEL` |
| Fix-It: diagnose the broken part and specs from the video | `gemini-4-hydrogen` | Fast video understanding for a live phone flow | `IDENTIFY_MODEL` |
| Fix-It: per-offer fit check (yes/no with a score) | `gemini-decision-1` (Decisions API) | Built for scored decisions over many candidates | `DECISION_MODEL` |
| Fix-It: rank the top 3 against the diagnosed specs | `gemini-4-argon` (thinking LOW) | Compares specs, compatibility and price across offers | `RANK_MODEL`, `RANK_THINKING` |
| Closing review after close (stretch, not built) | `gemini-4-carbon` | Deepest reasoning over a full day's trace | n/a |

`LOW` is the lowest thinking level Gemini 4 accepts (`MINIMAL` is rejected). Leaving it unset is much slower: about 17 s vs 4 s per call in our test.

## Run

Needs Python 3.11+, Node.js 22+, and FFmpeg (`ffprobe`, `libx264`).

```sh
cp .env.example .env        # set GEMINI_API_KEY (never commit .env)
./run.sh                    # venv + deps + dashboard build + server on http://localhost:8100
```

Or by hand:

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
npm --prefix frontend ci && npm --prefix frontend run build
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8100
```

| URL | What |
|---|---|
| `/` | Viewer: **Queue Monitor** (video + live boxes + evidence), **Fix-It**, **Ops timeline**, Evaluation, Run history |
| `/fixit/` | Fix-It phone page (open on a phone or through a tunnel; also embedded in the Fix-It tab) |
| `/api/health` | Combined health (both modules' models, key present) |
| `/api/fixit/health`, `/api/fixit/analyze`, `/api/fixit/checkout`, `/api/fixit/buy-click` | Fix-It API |
| `/api/config`, `/api/sources`, `/api/runs`, ... | Queue Monitor API (unchanged) |
| `/api/timeline` | Shared journal timeline (queue + Fix-It) |

**Default footage is real.** `./run.sh` runs `scripts/fetch_real_default.sh` once, which downloads three short clips from the [Café dataset](https://dk-kim.github.io/CAFE/) (Kim et al., ECCV 2024; café 8, clips 187/27/28, people lining up at the counter) by HTTP range (~42 MiB, about a minute) and stitches them into `demo/real/cafe-781-counter.mp4` (git-ignored). The dataset publishes no redistribution license, so the footage is fetched at setup instead of committed. The dashboard opens on that clip ("Café 781 counter · real footage") and runs live Gemini analysis on it. The authored cartoon scene stays available as **Offline demo (synthetic)**, for running without a key or network, and is never the default when real footage is present. You can also upload any MP4/MOV/WebM or use a webcam.

Fix-It needs `GEMINI_API_KEY`.

For a phone demo over a tunnel: `cloudflared tunnel --url http://localhost:8100 --protocol http2`, then open `https://<name>.trycloudflare.com/fixit/` (`*.trycloudflare.com` is allowed by `ALLOWED_HOSTS`). The tunnel runs on your Gemini key, so don't share it widely.

## Buying (Shopify / Shop MCP)

- Primary: **Buy now** opens a sheet with the product, then **Checkout** opens the offer's `checkout_url` exactly as Shop MCP returned it (merchant checkout, guest option).
- Fallback: "or checkout with Shop" calls `create_checkout` (one merchant per checkout) and opens `continue_url` exactly as returned.
- The app **never calls `complete_checkout`**; the shopper reviews and pays on the merchant page. Live data only: no caching of results, no re-hosting of images.

## Test

```sh
python -m unittest discover -v                          # queue monitor suite + Fix-It integration tests
python -m eval.benchmark --fixture --output /tmp/r.json && diff eval/fixture-report.json /tmp/r.json
cd fixit && python scripts/smoke_test.py eval/samples/aerator_messy.mp4   # live Fix-It end-to-end (creates, never completes, a checkout)
cd fixit && python eval/eval.py --clips eval/samples      # Fix-It sample-clip eval vs single-frame baseline
```

## Layout

```
backend/app/        FastAPI app (base: cafe-ops-agent). main.py mounts Fix-It at /api/fixit and /fixit/
  journal.py        SQLite journal; ops_log table + timeline() added for Fix-It events
fixit/              Fix-It Cam (subtree of DotBion/fixitcam, history preserved)
  app/              server.py (APIRouter + event sink), pipeline.py, gemini.py, shop_mcp.py
  static/           phone page (index.html, upload.js, eval_upload.html)
  eval/, scripts/   Fix-It eval clips, results, smoke test
frontend/           React + Vite dashboard (Queue Monitor, Fix-It, Ops timeline tabs)
demo/, eval/, tests/  Queue Monitor synthetic replay, benchmark, tests (+ tests/test_fixit_integration.py)
docs/               Queue Monitor docs (queue-monitor.md, queue-monitor-plan.md, evaluation, decisions, issues)
```

## Results

- **Fix-It** (17 public clips: 8 synthetic, 5 real household, 4 restaurant photo-pans): full video pipeline 13/17 keyword@3 (76%), 11/17 judge@3 (65%), median 21.1 s; single-frame baseline 11/17 (65%) and 7/17 (41%), 3.6 s. Details and failures: [fixit/README.md](fixit/README.md).
- **Queue Monitor**: agent vs single-observation baseline on the synthetic fixture: [eval/fixture-report.json](eval/fixture-report.json), [docs/evaluation.md](docs/evaluation.md).

## Docs

- [PLAN.md](PLAN.md): goals, themes, milestones, combined Carbon closing review (stretch)
- [ARCHITECTURE.md](ARCHITECTURE.md): components, request flows, shared journal, deployment, security
- Module detail: [docs/queue-monitor.md](docs/queue-monitor.md), [agent.md](agent.md), [docs/queue-monitor-plan.md](docs/queue-monitor-plan.md), [fixit/README.md](fixit/README.md), [fixit/PLAN.md](fixit/PLAN.md), [fixit/ARCHITECTURE.md](fixit/ARCHITECTURE.md)

## Credits

This repo merges two projects by [DotBion](https://github.com/DotBion):

- [DotBion/cafe-ops-agent](https://github.com/DotBion/cafe-ops-agent): Café Ops queue monitor (backend, dashboard, eval, tests). Imported as a snapshot of `main` in the first commit (its git history lives in the original repo).
- [DotBion/fixitcam](https://github.com/DotBion/fixitcam): Fix-It Cam. Merged under `fixit/` with full git history (subtree merge).
