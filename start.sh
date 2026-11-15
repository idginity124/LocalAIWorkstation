#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# Local, trusted shell configuration; never committed to the repository.
if [[ -f "$PROJECT_DIR/.env" ]]; then
  set -a
  source "$PROJECT_DIR/.env"
  set +a
fi
BACKEND_ENV="$PROJECT_DIR/backend/.venv"
FRONTEND_DIR="$PROJECT_DIR/frontend"
if [[ ! -x "$BACKEND_ENV/bin/uvicorn" || ! -x "$FRONTEND_DIR/node_modules/.bin/vite" ]]; then
  printf '%s\n' 'Bağımlılıklar eksik. docs/INSTALLATION.md dosyasına bakın.'
  exit 1
fi
if ss -ltn '( sport = :8000 )' | tail -n +2 | grep -q .; then
  printf '%s\n' '8000 portu kullanımda. Mevcut servisi durdurmadım.'
  exit 1
fi
if [[ "${1:-}" == "--dev" ]]; then
  if ss -ltn '( sport = :5173 )' | tail -n +2 | grep -q .; then
    printf '%s\n' '5173 portu kullanımda.'
    exit 1
  fi
  "$BACKEND_ENV/bin/uvicorn" app.main:app --app-dir "$PROJECT_DIR/backend" --host 127.0.0.1 --port 8000 &
  BACKEND_PID=$!
  (cd "$FRONTEND_DIR" && exec node node_modules/vite/bin/vite.js --host 127.0.0.1) &
  FRONTEND_PID=$!
  cleanup() {
    kill "$FRONTEND_PID" "$BACKEND_PID" 2>/dev/null || true
    wait "$FRONTEND_PID" "$BACKEND_PID" 2>/dev/null || true
  }
  trap cleanup EXIT INT TERM
  printf '%s\n' 'Arayüz: http://127.0.0.1:5173 · Durdurmak için Ctrl+C'
  wait -n "$BACKEND_PID" "$FRONTEND_PID"
else
  (cd "$FRONTEND_DIR" && npm run build)
  printf '%s\n' 'Yerel AI: http://127.0.0.1:8000 · Durdurmak için Ctrl+C'
  exec "$BACKEND_ENV/bin/uvicorn" app.main:app --app-dir "$PROJECT_DIR/backend" --host 127.0.0.1 --port 8000
fi
