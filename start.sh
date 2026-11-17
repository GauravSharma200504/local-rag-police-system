#!/usr/bin/env bash
# Bharat Police Intelligence - local start (Linux/macOS).  Usage: ./start.sh [--seed]
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] || { cp .env.example .env; echo "Created .env from .env.example (edit SECRET_KEY!)"; }
docker compose up -d db
[ -d backend/.venv ] || python3 -m venv backend/.venv
PY=backend/.venv/bin/python
$PY -m pip install -q -r backend/requirements.txt
$PY -c "import sentence_transformers" 2>/dev/null || { $PY -m pip install -q torch --index-url https://download.pytorch.org/whl/cpu; $PY -m pip install -q -r backend/requirements-ml.txt; }
sleep 3
(cd backend && ../$PY -m alembic upgrade head)
if [ "${1:-}" = "--seed" ]; then
  $PY scripts/generate_sample_data.py
  (cd backend && ../$PY -m app.cli download-models --yes && ../$PY -m app.cli seed-demo)
fi
(cd backend && ../$PY -m uvicorn app.main:app --port 8000 &)
(cd frontend && { [ -d node_modules ] || npm install; } && npm run dev &)
echo "Open http://localhost:5173  (Ollama: 'ollama serve' and 'ollama pull llama3.2:3b')"
wait
