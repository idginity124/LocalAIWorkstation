#!/usr/bin/env bash
# Read-only ComfyUI API probe. Run after ComfyUI is started on loopback.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="$PROJECT_ROOT/runtime-reports"
STAMP="$(date +%Y%m%d-%H%M%S)"
REPORT="$REPORT_DIR/comfy-zimage-probe-$STAMP.json"
mkdir -p "$REPORT_DIR"

command -v curl >/dev/null || { echo "Eksik araç: curl" >&2; exit 1; }
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8188/system_stats >/dev/null || {
  echo "ComfyUI 127.0.0.1:8188 üzerinde hazır değil." >&2; exit 1;
}
curl --fail --silent --show-error --max-time 15 http://127.0.0.1:8188/object_info >"$REPORT"
echo "ComfyUI node envanteri kaydedildi: $REPORT"
echo "Beklenen temel node'lar:"
python - "$REPORT" <<'PY'
import json
import sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
for name in ("UNETLoader", "CLIPLoader", "VAELoader", "TextEncodeZImageOmni", "KSampler", "VAEDecode", "SaveImage"):
    print(f"- {name}: {'var' if name in data else 'YOK'}")
for name in ("UNETLoader", "CLIPLoader", "VAELoader"):
    entry = data.get(name, {})
    required = entry.get("input", {}).get("required", {})
    for key, value in required.items():
        if isinstance(value, list) and value and isinstance(value[0], list):
            matches = [item for item in value[0] if "z_image" in str(item).lower() or "qwen_3_4b" in str(item).lower() or str(item) == "ae.safetensors"]
            if matches:
                print(f"  {name}.{key}: {matches}")
PY
