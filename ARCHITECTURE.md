# Restaurant Ops Copilot: Architecture

## Components

```
                         Browser (laptop)                      Phone (QR / tunnel)
                 React dashboard  "/"                          Fix-It page "/fixit/"
        [Queue Monitor] [Fix-It (iframe /fixit/)] [Ops timeline]        |
                 |                    |                  |               |
                 v                    v                  v               v
   +--------------------------------------------------------------------------------+
   | FastAPI  backend.app.main:app  (one process, port 8100)                         |
   |  TrustedHost (ALLOWED_HOSTS)  +  cross-site POST guard + upload size guard      |
   |                                                                                 |
   |  Queue Monitor  /api/config /api/sources /api/runs/... (SSE events)             |
   |    runs.py -> analysis.py (investigate, persistence, tasks) -> models.py        |
   |    media.py (ffmpeg frames)                         gemini-4-hydrogen           |
   |                                                                                 |
   |  Fix-It  /api/fixit/{health,analyze,checkout,buy-click,eval-*}  (APIRouter)     |
   |    fixit/app/pipeline.py -> gemini.py (diagnose, fit_gate, rank)                |
   |                          -> shop_mcp.py (search_catalog, create_checkout)       |
   |    gemini-4-hydrogen  +  gemini-decision-1 (Decisions API)  +  Shop MCP         |
   |                                                                                 |
   |  Shared journal  journal.py -> CAFE_HOME/operations.sqlite3                     |
   |    sources, runs, events (queue)  +  ops_log (Fix-It)  ->  /api/timeline        |
   +--------------------------------------------------------------------------------+
                 |                                   |
        Gemini API (google-genai / REST)     Shop MCP https://mcp.shop.com/ (stateless, 2026-07-28)
```

## How the two apps were joined

- **Base**: cafe-ops-agent's `create_app()` (lifespan, journal, run manager, static dashboard mount).
- **Fix-It routes**: `fixit/app/server.py` now defines its endpoints on an `APIRouter` (`router`) instead of directly on an app. The restaurant-ops app includes it at `/api/fixit`; the standalone Fix-It app (`fixit.app.server:app`, `create_standalone_app()`) includes the same router at `/api`, so the original Fix-It Cam still runs on its own unchanged paths. Pipeline, Gemini and Shop MCP modules are untouched.
- **Fix-It page**: served at `/fixit/` (with `/fixit` -> 307), static files at `/fixit/static/`. The page picks its API base from its path (`/fixit...` -> `/api/fixit`, otherwise `/api`) and loads `static/upload.js` relatively, so the same HTML works in both hosts.
- **Event sink**: `fixit_server.EVENT_SINKS` is a list of `(kind, payload)` callables. In the lifespan the merged app registers `journal.log("fixit", kind, payload)` and removes it on shutdown. Sink errors are swallowed so logging can never break a scan or a checkout.
- **Dashboard**: `frontend/src/main.tsx` adds **Fix-It** (same-origin iframe of `/fixit/` plus an "open full screen / on phone" link) and **Ops timeline** (polls `/api/timeline` every 4 s) next to the existing Queue Monitor, Evaluation and Run history views.

## Shared journal

| Table | Written by | Content |
|---|---|---|
| `sources`, `runs`, `events` | Queue Monitor (unchanged) | video sources, runs, per-run events (`observation`, `review_*`, `decision`, `task`, `run_status`, `error`) |
| `ops_log` (new) | Fix-It via event sink | `fixit.diagnosis` (diagnosis JSON, note, media type, timings), `fixit.results` (item/part, confidence, fit scores for up to 8 offers, top 3 with price/shop/product_url, timings), `fixit.checkout_created` (shop, variant, status, total), `fixit.buy_click` (path `checkout_url` or `create_checkout`, title, shop, price, fit), `fixit.error` |

`Journal.timeline(limit)` merges `ops_log` with queue events of kind `task`, `decision`, `review_completed`, `run_status`, `error`, newest first. It is the input for the planned Carbon closing review ([PLAN.md](PLAN.md)).

## Fix-It request flow

1. Phone uploads a clip (or keyframes, shrunk on-device if large) to `POST /api/fixit/analyze`; the response is NDJSON stages.
2. Video goes to the Gemini Files API; `gemini-4-hydrogen` returns a structured diagnosis (item, broken part, specs seen/heard/inferred, evidence timestamps, search queries, best frame, confidence, uncertainties).
3. ffmpeg grabs the best frame; Shop MCP `search_catalog` runs by text queries and by image (`like`).
4. `gemini-decision-1` scores each offer's fit; offers are sorted and filtered.
5. `gemini-4-hydrogen` picks the top 3 with reasons and checks.
6. Buy: the sheet's **Checkout** opens `checkout_url` exactly as returned (merchant checkout, guest option); fallback `POST /api/fixit/checkout` -> Shop MCP `create_checkout` -> `continue_url` exactly as returned. `complete_checkout` is never called. Checkout pages refuse framing, so the last step opens a new tab. Each tap posts `/api/fixit/buy-click` to the journal.

Measured on the merged server (box, sample `kitchen_rusty_cabinet_hinge.mp4`): upload 3.4 s, diagnose 6.4 s, search 0.8 s, gate 1.0 s, rank 5.5 s, total 17.2 s, 18 offers considered.

## Queue Monitor flow

Unchanged from cafe-ops-agent; see [agent.md](agent.md) and [docs/queue-monitor.md](docs/queue-monitor.md): sample frames per window, estimate queue, investigate ambiguous changes (denser frames, crop, earlier observations), create/update/resolve a staff task only after the condition persists, stream events over SSE, store evidence references.

## Models

| Use | Model | Setting |
|---|---|---|
| Queue observer / verifier | `gemini-4-hydrogen` (LOW thinking) | `CAFE_OBSERVER_MODEL`, `CAFE_VERIFIER_MODEL`, `CAFE_THINKING_LEVEL` |
| Fix-It diagnose / rank | `gemini-4-hydrogen` | `IDENTIFY_MODEL`, `RANK_MODEL`, `DIAGNOSE_THINKING`, `RANK_THINKING` |
| Fix-It fit gate | `gemini-decision-1` (Decisions API) | `DECISION_MODEL` |
| Closing review (stretch) | `gemini-4-carbon` | not implemented |

## Deployment

- `./run.sh` or `uvicorn backend.app.main:app --port 8100` after `npm --prefix frontend run build` (dashboard served from `frontend/dist`).
- Phone/judges: cloudflared quick tunnel (`--protocol http2`) to port 8100; `*.trycloudflare.com` is in the default `ALLOWED_HOSTS`.
- `CAFE_HOME` holds the SQLite journal and prepared media (default `.cafe-ops/`, git-ignored).

## Security

- `GEMINI_API_KEY` only in the server env or `.env` (git-ignored); only the backend calls Google and Shop MCP.
- Host header allow-list; cross-site POSTs rejected; upload size limits (queue 150 MiB, Fix-It `MAX_UPLOAD_MB`).
- No purchase is ever completed server-side; checkout URLs and product images are used exactly as returned (no caching, no re-hosting).
- The public tunnel runs on the owner's Gemini key: share it only with judges.

## Failure modes

- No key: queue synthetic replay still works; Fix-It analyze returns an `error` event.
- Shop MCP errors: `/api/fixit/checkout` returns 502 with the message; the page shows it and keeps the sheet open.
- Decisions API failure: offers keep search order and `gate_error` is reported in timings.
- Unknown tunnel host: 400 from TrustedHost; add it to `ALLOWED_HOSTS`.
- Journal write failure in the Fix-It sink: ignored (scan continues).

Module detail: [fixit/ARCHITECTURE.md](fixit/ARCHITECTURE.md), [docs/queue-monitor-plan.md](docs/queue-monitor-plan.md#4-architecture).
