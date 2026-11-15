#!/usr/bin/env bash
# One-shot, desktop-session-only Gemma Vulkan smoke test.
# It never touches the application-managed port (18080) and always requests
# graceful server shutdown when this script exits.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_ROOT="${AI_WORKSTATION_MODEL_DIR:-$HOME/AI/models}"
MODEL="$MODEL_ROOT/gemma-4-12b/gemma-4-12B-it-Q4_0.gguf"
MMPROJ="$MODEL_ROOT/gemma-4-12b/mmproj-gemma-4-12B-it-Q8_0.gguf"
PORT=18081
REPORT_DIR="$PROJECT_ROOT/runtime-reports"
STAMP="$(date +%Y%m%d-%H%M%S)"
REPORT="$REPORT_DIR/gemma-gpu-smoke-$STAMP.txt"
SERVER_LOG="$REPORT_DIR/gemma-gpu-smoke-$STAMP-server.log"
SERVER_PID=""

mkdir -p "$REPORT_DIR"
exec > >(tee "$REPORT") 2>&1

finish() {
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "Gemma sunucusu kontrollü biçimde kapatılıyor."
    kill -TERM "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap finish EXIT INT TERM

for tool in llama-server curl ss; do
  command -v "$tool" >/dev/null || { echo "Eksik araç: $tool"; exit 1; }
done
[[ -f "$MODEL" ]] || { echo "Model dosyası bulunamadı: $MODEL"; exit 1; }
[[ -f "$MMPROJ" ]] || { echo "Multimodal projector bulunamadı: $MMPROJ"; exit 1; }
if ss -ltn "sport = :$PORT" | grep -q LISTEN; then
  echo "Test portu $PORT kullanımda; dış sürece dokunulmadı."
  exit 1
fi

snapshot() {
  local label="$1"
  echo "--- $label ---"
  date --iso-8601=seconds
  free -h
  for file in /sys/class/drm/card*/device/mem_info_vram_{used,total}; do
    [[ -r "$file" ]] && printf '%s: %s bytes\n' "$file" "$(<"$file")"
  done
}

echo "Gemma Vulkan smoke testi — uygulama portu kullanılmaz."
llama-server --list-devices
snapshot "başlangıç"
echo "Sunucu Vulkan0 ile başlatılıyor; tüm katmanlar GPU'ya isteniyor."
llama-server --model "$MODEL" --mmproj "$MMPROJ" \
  --host 127.0.0.1 --port "$PORT" --device Vulkan0 --gpu-layers 999 \
  --ctx-size 2048 --parallel 1 --threads 4 --batch-size 128 --ubatch-size 128 \
  --alias gemma-4-12b-smoke --no-webui --reasoning off >"$SERVER_LOG" 2>&1 &
SERVER_PID="$!"

for _ in $(seq 1 360); do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "Sunucu hazır olmadan kapandı. Günlük: $SERVER_LOG"
    tail -n 80 "$SERVER_LOG" || true
    exit 1
  fi
  if curl --fail --silent --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null; then
    break
  fi
  sleep 0.5
done

curl --fail --silent --max-time 10 "http://127.0.0.1:$PORT/health" >/dev/null || {
  echo "Sunucu 180 saniyede hazır olmadı. Günlük: $SERVER_LOG"; exit 1;
}
snapshot "model yüklendikten sonra"
echo "Kısa gerçek yanıt isteniyor."
curl --fail --silent --show-error --max-time 120 \
  -H 'Content-Type: application/json' \
  --data '{"model":"gemma-4-12b-smoke","stream":false,"messages":[{"role":"user","content":"Yalnızca şu metinle yanıt ver: GPU smoke testi başarılı."}],"temperature":0,"max_tokens":24}' \
  "http://127.0.0.1:$PORT/v1/chat/completions"
echo
snapshot "yanıttan sonra"
echo "Sunucu günlüğü: $SERVER_LOG"
echo "Ölçüm raporu: $REPORT"
