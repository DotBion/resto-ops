#!/usr/bin/env bash
# One command: venv + deps + dashboard build + server on http://localhost:${PORT:-8100}
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -f .env ] && [ -z "${GEMINI_API_KEY:-}" ]; then echo "warning: GEMINI_API_KEY not set (synthetic queue demo still works; Fix-It needs it)"; fi
command -v ffmpeg >/dev/null || echo "warning: ffmpeg not found; queue video upload and Fix-It keyframe search need it"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
# Real café footage for the Queue Monitor default (fetched, not redistributed). Falls back to the synthetic demo.
[ -f demo/real/cafe-781-counter.mp4 ] || PYTHON=.venv/bin/python ./scripts/fetch_real_default.sh || echo "warning: could not fetch real café footage; the dashboard will default to the offline synthetic demo"
if [ ! -d frontend/dist ]; then npm --prefix frontend ci && npm --prefix frontend run build; fi
exec .venv/bin/python -m uvicorn backend.app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8100}"
