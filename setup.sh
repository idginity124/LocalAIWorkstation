#!/usr/bin/env bash
# Install application dependencies only; model weights / GPU engines are separate.
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
for tool in python3 node npm; do
  command -v "$tool" >/dev/null || { printf 'Eksik araç: %s\n' "$tool" >&2; exit 1; }
done
python3 - <<'PY'
import sys
if not (3, 12) <= sys.version_info < (3, 15):
    raise SystemExit('Python 3.12–3.14 gerekli.')
PY
node -e 'if (Number(process.versions.node.split(".")[0]) < 22) { console.error("Node.js 22+ gerekli."); process.exit(1); }'
if [[ ! -x "$PROJECT_DIR/backend/.venv/bin/python" ]]; then
  python3 -m venv "$PROJECT_DIR/backend/.venv"
fi
"$PROJECT_DIR/backend/.venv/bin/python" -m pip install -e "$PROJECT_DIR/backend[dev]"
npm ci --prefix "$PROJECT_DIR/frontend"
printf '%s\n' 'Bağımlılıklar kuruldu. İsterseniz .env.example dosyasını .env olarak kopyalayıp yolları ayarlayın.' 'Başlatmak için: bash start.sh'
