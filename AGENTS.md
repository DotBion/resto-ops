# Working on Café Ops

Start with the [README](README.md) for setup, [plan.md](plan.md) for scope and milestones, and [agent.md](agent.md) for the current agent behavior and the closing shift proposal.

- The FastAPI entry point is [backend/app/main.py](backend/app/main.py). The React dashboard starts in [frontend/src/main.tsx](frontend/src/main.tsx).
- Keep observations and decisions tied to source time. Use frames available at the playback watermark and preserve run boundaries when the source or playhead changes.
- Keep estimate confidence, evidence freshness, and task state distinct. A stale, missing, or invalid observation cannot justify a task change. Apply task transitions in the backend.
- Keep reviewed labels in the evaluator. Describe which footage, model, and labels support each result. The fixture comparison exercises app behavior, and the Gemini smoke test checks the request and response path.
- Configure Gemini on the backend with a local environment variable or a GitHub Actions secret. Keep credentials, runtime media, and local evaluation data out of commits.

For backend changes, run `python -m unittest discover -v`. For evaluator or policy changes, run `python -m eval.benchmark --fixture --output /tmp/cafe-evaluation.json` and check the result against [eval/fixture-report.json](eval/fixture-report.json). For dashboard changes, run `npm --prefix frontend run build`. The Gemini smoke workflow is a separate credentialed check.

Log decisions and tradeoffs in [docs/decisions.md](docs/decisions.md), observed problems in [docs/issues.md](docs/issues.md), and measured results in [docs/evaluation.md](docs/evaluation.md). Keep setup commands and links current in the README.
