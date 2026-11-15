#!/usr/bin/env bash
set -euo pipefail
PROJECT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$PROJECT/backend/.venv/bin/python" -u "$PROJECT/scripts/probe_krita_bridge.py"
