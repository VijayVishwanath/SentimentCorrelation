#!/usr/bin/env bash
# One-command setup and launch (macOS / Linux / Git Bash). Usage: ./run.sh [port]
set -euo pipefail
cd "$(dirname "$0")"
PORT="${1:-8000}"
[ -d .venv ] || python3 -m venv .venv
PY=.venv/bin/python; [ -x "$PY" ] || PY=.venv/Scripts/python
"$PY" -m pip install -q -r backend/requirements-dev.txt
(cd frontend && { [ -d node_modules ] || npm install --no-audit --no-fund; } && npm run build)
cd backend && exec "../$PY" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
