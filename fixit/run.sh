#!/usr/bin/env bash
# One-command run: creates a venv, installs deps, starts Fix-It Cam on http://localhost:${PORT:-8000}
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -f .env ] && [ -z "${GEMINI_API_KEY:-}" ]; then echo "Set GEMINI_API_KEY (cp .env.example .env and edit)"; exit 1; fi
command -v ffmpeg >/dev/null || echo "warning: ffmpeg not found; keyframe photo search will be skipped"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
exec .venv/bin/python -m app.server
