# Restaurant Ops Copilot

One app for the two things that wreck a restaurant shift: **a line nobody is handling** and **equipment that breaks mid-service**.

- **Queue Monitor**: watches a camera feed or uploaded footage for customers waiting to order, double-checks ambiguous moments with extra frames, and raises a staff task (with evidence frames) only when the queue persists. Built on `gemini-4-hydrogen`.
- **Fix-It**: film anything broken on your phone. `gemini-4-hydrogen` names the exact part and its specs, **Shop MCP** searches the live catalog by words and by keyframe photo, the **Gemini Decisions API** (`gemini-decision-1`) scores fit per offer, Gemini ranks the top 3, and **Buy now** opens a real merchant checkout (guest checkout available).
- **One timeline**: queue tasks/decisions and Fix-It scans, fit results, checkouts and buy clicks are written to one SQLite journal (`/api/timeline`, **Ops timeline** tab). That trace is what the planned Gemini 4 **Carbon closing review** reads at night (see [PLAN.md](PLAN.md), stretch, not implemented).

Built at the Gemini 4 NYC Hackathon (Cerebral Valley x Google DeepMind), Nov 21 2026.

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
| `/` | React dashboard: **Queue Monitor**, **Fix-It**, **Ops timeline**, Evaluation, Run history |
| `/fixit/` | Fix-It phone page (open on a phone or through a tunnel; also embedded in the Fix-It tab) |
| `/api/health` | Combined health (both modules' models, key present) |
| `/api/fixit/health`, `/api/fixit/analyze`, `/api/fixit/checkout`, `/api/fixit/buy-click` | Fix-It API |
| `/api/config`, `/api/sources`, `/api/runs`, ... | Queue Monitor API (unchanged) |
| `/api/timeline` | Shared journal timeline (queue + Fix-It) |

The synthetic queue replay (**Play the synthetic demo**) runs without a key. Fix-It needs `GEMINI_API_KEY`.

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
