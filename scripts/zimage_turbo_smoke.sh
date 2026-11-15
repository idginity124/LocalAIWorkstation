#!/usr/bin/env bash
# One controlled real ComfyUI Z-Image Turbo smoke job, 1024x1024, 8 steps.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKFLOW="$PROJECT_ROOT/workflows/z-image-turbo-api.json"
REPORT_DIR="$PROJECT_ROOT/runtime-reports"
STAMP="$(date +%Y%m%d-%H%M%S)"
REPORT="$REPORT_DIR/z-image-turbo-smoke-$STAMP.txt"
mkdir -p "$REPORT_DIR"
exec > >(tee "$REPORT") 2>&1

for tool in curl python; do command -v "$tool" >/dev/null || { echo "Eksik araç: $tool"; exit 1; }; done
[[ -f "$WORKFLOW" ]] || { echo "Workflow bulunamadı: $WORKFLOW"; exit 1; }
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8188/system_stats >/dev/null || { echo "ComfyUI hazır değil."; exit 1; }

snapshot() { echo "--- $1 ---"; date --iso-8601=seconds; free -h; for file in /sys/class/drm/card*/device/mem_info_vram_{used,total}; do [[ -r "$file" ]] && printf '%s: %s bytes\n' "$file" "$(<"$file")"; done; }
PAYLOAD="$(mktemp)"; trap 'rm -f "$PAYLOAD"' EXIT
python - "$WORKFLOW" "$PAYLOAD" <<'PY'
import json, sys
workflow = json.load(open(sys.argv[1], encoding="utf-8"))
workflow["4"]["inputs"]["text"] = "A single red apple on a clean white studio background, soft natural shadow, photorealistic."
json.dump({"prompt": workflow, "client_id": "local-ai-zimage-smoke"}, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
PY

snapshot "başlangıç"
RESPONSE="$(curl --fail --silent --show-error --max-time 30 -H 'Content-Type: application/json' --data-binary "@$PAYLOAD" http://127.0.0.1:8188/prompt)"
echo "Kuyruk yanıtı: $RESPONSE"
PROMPT_ID="$(python -c 'import json,sys; print(json.load(sys.stdin).get("prompt_id", ""))' <<<"$RESPONSE")"
[[ -n "$PROMPT_ID" ]] || { echo "ComfyUI prompt_id vermedi."; exit 1; }
echo "Gerçek iş tamamlanması bekleniyor: $PROMPT_ID"
for _ in $(seq 1 720); do
  HISTORY="$(curl --fail --silent --show-error --max-time 10 "http://127.0.0.1:8188/history/$PROMPT_ID")"
  STATUS="$(python -c 'import json,sys; d=json.load(sys.stdin); x=next(iter(d.values()),{}); print(x.get("status",{}).get("status_str", "pending"))' <<<"$HISTORY")"
  if [[ "$STATUS" == "success" ]]; then
    echo "$HISTORY" >"$REPORT_DIR/z-image-turbo-smoke-$STAMP-history.json"; echo "Başarılı çıktı kaydı: $REPORT_DIR/z-image-turbo-smoke-$STAMP-history.json"; snapshot "işten sonra"; exit 0
  fi
  if [[ "$STATUS" == "error" ]]; then
    echo "$HISTORY" >"$REPORT_DIR/z-image-turbo-smoke-$STAMP-history.json"; echo "ComfyUI işi hata verdi; geçmiş: $REPORT_DIR/z-image-turbo-smoke-$STAMP-history.json"; snapshot "hata sonrası"; exit 1
  fi
  sleep 1
done
echo "İş 12 dakikada tamamlanmadı; ComfyUI'yi ve geçmişi inceleyin."; exit 1
