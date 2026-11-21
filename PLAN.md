# Restaurant Ops Copilot: Plan

## Goal

One copilot for a restaurant shift that (1) notices a line building before it costs sales and (2) turns "something broke" into the right replacement part with a real checkout in about 20 seconds. Both feed one operations journal that a deep-reasoning model reviews after close.

Hackathon: Gemini 4 NYC (Cerebral Valley x Google DeepMind), Sat Nov 21 2026. Submission due **5:00 PM ET**: 1-minute demo video + public GitHub repo.

## Themes targeted

- **5 Sigma (reliability)**: both modules are measured against a baseline on messy inputs and report failures.
  - Queue Monitor: agent (investigate + persistence) vs single-observation baseline on the synthetic fixture; holds a false alert, raises a task on a sustained queue ([docs/evaluation.md](docs/evaluation.md)).
  - Fix-It: full video pipeline vs one-frame + plain search baseline on 17 clips: 76% vs 65% keyword@3, 65% vs 41% judge@3 ([fixit/README.md](fixit/README.md)).
- **Element 119 (video/images at the core, Decisions API)**: both modules reason over video frames; Fix-It uses `gemini-decision-1` as a per-offer fit gate and shows where it breaks.
- **Shopify prize**: Fix-It uses Shop MCP (`search_catalog` by text and by image, `create_checkout`); a judge can make a real purchase. URLs are used exactly as returned; `complete_checkout` is never called.

## Milestones

| # | Milestone | Status |
|---|---|---|
| 1 | Queue Monitor: FastAPI backend, run manager, SQLite journal, React dashboard, synthetic replay, benchmark, tests | Done (from cafe-ops-agent) |
| 2 | Fix-It: video diagnosis, Shop MCP search (text + keyframe), Decisions fit gate, top-3 rank, buy sheet with guest checkout | Done (from fixitcam) |
| 3 | Merge: one FastAPI app; Fix-It router at `/api/fixit`, phone page at `/fixit/`; host allow-list for tunnels | Done |
| 4 | Shared journal: Fix-It diagnosis, results (fit scores, top 3), checkout created, buy clicks written to `ops_log`; `/api/timeline` merges with queue tasks/decisions | Done |
| 5 | Dashboard tabs: Queue Monitor, Fix-It (embedded `/fixit/`), Ops timeline | Done |
| 6 | Tests: queue suite + Fix-It integration tests; fixture benchmark unchanged | Done |
| 7 | Real restaurant clips for both modules; rerun evals; update numbers | Pending (needs filming) |
| 8 | 1-minute video; repo public; submit by ~4:45 PM ET | Pending |
| 9 | **Carbon closing review** (below) | Stretch, **not implemented** |
| 10 | Real-footage queue fixes: service-line prompt (buffet/pickup/registration lines), 6 s cadence, 30 s lag, verified ranges can raise tasks; Argon as verifier and Fix-It ranker | Done |
| 11 | **Local person detector + tracker for live boxes** (below) | Next step, **not built** |

## Stretch: Carbon closing review (not implemented)

**Idea:** after close, send the day's journal (`/api/timeline` plus per-run events and Fix-It traces) to **`gemini-4-carbon`**, Google's deepest-reasoning Gemini 4 tier, for one overnight review. `gemini-4-hydrogen` stays the live path for both modules; the Decisions API stays the per-offer fit gate. The output is a short report that ends in concrete decisions for the owner, not a summary.

**Inputs:** queue estimates and ranges, reviews, task creation/acknowledgment/resolution, camera coverage, recorded staff interventions; short timestamped footage around significant events plus a few quiet/uncertain windows; for each Fix-It scan the clip reference, diagnosis with `confidence` and `uncertainties`, fit-gate scores, top-3 ranking, buy events (`checkout_url` vs Shop fallback, abandoned) and per-stage timings.

**Problems it addresses:** recurring service bottlenecks nobody connects across shifts; repeat equipment failures handled one at a time; rushed, wrong or overpriced part buys; no maintenance log; reliability blind spots in the live system itself.

**Queue questions** (from [agent.md](agent.md)):

1. When did the queue build and clear? Which backed-up periods recur on comparable shifts? Cite frames and report gaps where coverage was too sparse.
2. What preceded each buildup (burst of arrivals, stationary line, pickup traffic mixing with the ordering line), and what evidence supports or weakens each explanation?
3. Which alerts were supported or questionable? When did staff acknowledge them, and when did the queue visibly shrink?
4. Did any quiet or uncertain windows show a queue the live system missed?
5. What is one change worth testing on the next comparable shift, and how will the manager measure it?

**Fix-It questions** (from [fixit/PLAN.md](fixit/PLAN.md) milestone 8):

6. Which equipment failed or was scanned repeatedly, and what is the likely root cause?
7. Were any buys band-aids for a deeper problem?
8. Which spare parts should be stocked, given failure frequency and shipping time?
9. Where was the app unsure or wrong (low-confidence diagnoses, overridden fit gates, abandoned checkouts), with clip references?
10. A pre-service checklist for tomorrow.
11. A spend summary, plus avoidable or overpriced buys compared with other sellers.

**Cross-module question:** 12. Did any breakdown coincide with a queue buildup (for example the espresso machine down at the morning rush), and what would have prevented it?

**Scope today:** build only if the demo and video are done by ~4 PM ET (one "closing report" screen over today's journal). Otherwise it is the next step in the pitch.

## Next step: local detector + tracker, Gemini for reasoning (not built)

Gemini 4 calls take about 4-15 s, so the live view only refreshes every few seconds. The next step splits the work:

- **On-device, every frame (about 30 fps):** a YOLO-style person detector (e.g. YOLO11n or RT-DETR, exported to ONNX or CoreML) plus a tracker (ByteTrack or BoT-SORT). This draws live boxes with stable IDs, per-person dwell time, a line-zone count over time, and arrival/service rates. No API cost, no lag.
- **Gemini 4, every few seconds or on a trigger:** send the tracker's numbers (count series, dwell times, track IDs inside the line zone) plus 3-6 key frames. Hydrogen confirms who is actually queueing versus standing nearby or seated; Argon re-checks before a staff task; Carbon reads the day's track log at close.
- **Why both:** the detector is fast but cannot tell a line from a crowd or know what the people are waiting for; Gemini can, but is too slow and costly for every frame. Counts from the tracker also make evaluation exact (per-frame count error against labels).
- **Scope:** about half a day: a `detector/` worker that writes track events to the same journal, a line-zone editor in the viewer, and a prompt that takes the counts as evidence.

## Risks

- Live demo latency (Fix-It ~17-25 s end to end): use `gemini-4-hydrogen`; stage progress streams to the page.
- Shop checkout sign-in wall: primary path is the merchant `checkout_url` (guest checkout confirmed on iPhone); Shop `continue_url` is the fallback.
- Checkout pages cannot be framed (X-Frame-Options), so the final step opens a new tab.
- Tunnel: quick tunnels change URL on restart; `ALLOWED_HOSTS` must include the host.
- Merge regressions: covered by `tests/test_fixit_integration.py` (routes, page paths, journal sink) and the unchanged queue suite.

Module detail: [docs/queue-monitor-plan.md](docs/queue-monitor-plan.md), [fixit/PLAN.md](fixit/PLAN.md).
