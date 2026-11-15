#!/usr/bin/env bash
# Desktop-session-only text GGUF Vulkan smoke test for Qwen or gpt-oss.
# This has a dedicated port, records measurements, and always asks the server
# to terminate on exit. It never uses an application-managed port.
set -euo pipefail

if [[ $# -ne 1 ]] || [[ "$1" != "qwen" && "$1" != "gpt-oss" ]]; then
  echo "Kullanım: $0 {qwen|gpt-oss}" >&2
  exit 2
fi
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_ROOT="${AI_WORKSTATION_MODEL_DIR:-$HOME/AI/models}"
if [[ "$1" == "qwen" ]]; then
  MODEL="$MODEL_ROOT/qwen3.5-9b/qwen3.5-9b-Q8_0.gguf"; PORT=18082; ALIAS="qwen3.5-9b-q8_0"; LABEL="Qwen3.5 9B Q8_0"
else
  MODEL="$MODEL_ROOT/gpt-oss-20b/gpt-oss-20b-MXFP4.gguf"; PORT=18083; ALIAS="gpt-oss-20b-mxfp4"; LABEL="gpt-oss 20B MXFP4"
fi
REPORT_DIR="$PROJECT_ROOT/runtime-reports"; STAMP="$(date +%Y%m%d-%H%M%S)"
REPORT="$REPORT_DIR/${1}-gpu-smoke-$STAMP.txt"; SERVER_LOG="$REPORT_DIR/${1}-gpu-smoke-$STAMP-server.log"; SERVER_PID=""
mkdir -p "$REPORT_DIR"; exec > >(tee "$REPORT") 2>&1
finish() { if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then echo "Sunucu kontrollü biçimde kapatılıyor."; kill -TERM "$SERVER_PID" 2>/dev/null || true; wait "$SERVER_PID" 2>/dev/null || true; fi; }
trap finish EXIT INT TERM
for tool in llama-server curl ss; do command -v "$tool" >/dev/null || { echo "Eksik araç: $tool"; exit 1; }; done
[[ -f "$MODEL" ]] || { echo "Model dosyası bulunamadı: $MODEL"; exit 1; }
if ss -ltn "sport = :$PORT" | grep -q LISTEN; then echo "Test portu $PORT kullanımda; dış sürece dokunulmadı."; exit 1; fi
snapshot() { echo "--- $1 ---"; date --iso-8601=seconds; free -h; for file in /sys/class/drm/card*/device/mem_info_vram_{used,total}; do [[ -r "$file" ]] && printf '%s: %s bytes\n' "$file" "$(<"$file")"; done; }
echo "$LABEL Vulkan smoke testi — uygulama portu kullanılmaz."; llama-server --list-devices; snapshot "başlangıç"
llama-server --model "$MODEL" --host 127.0.0.1 --port "$PORT" --device Vulkan0 --gpu-layers 999 --ctx-size 2048 --parallel 1 --threads 4 --batch-size 128 --ubatch-size 128 --alias "$ALIAS" --no-webui >"$SERVER_LOG" 2>&1 & SERVER_PID="$!"
for _ in $(seq 1 360); do kill -0 "$SERVER_PID" 2>/dev/null || { echo "Sunucu hazır olmadan kapandı. Günlük: $SERVER_LOG"; tail -n 80 "$SERVER_LOG" || true; exit 1; }; curl --fail --silent --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null && break; sleep 0.5; done
curl --fail --silent --max-time 10 "http://127.0.0.1:$PORT/health" >/dev/null || { echo "Sunucu 180 saniyede hazır olmadı. Günlük: $SERVER_LOG"; exit 1; }
snapshot "model yüklendikten sonra"; echo "Kısa gerçek yanıt isteniyor."
curl --fail --silent --show-error --max-time 180 -H 'Content-Type: application/json' --data "{\"model\":\"$ALIAS\",\"stream\":false,\"messages\":[{\"role\":\"user\",\"content\":\"Yalnızca şu metinle yanıt ver: GPU smoke testi başarılı.\"}],\"temperature\":0,\"max_tokens\":24}" "http://127.0.0.1:$PORT/v1/chat/completions"; echo
snapshot "yanıttan sonra"; echo "Sunucu günlüğü: $SERVER_LOG"; echo "Ölçüm raporu: $REPORT"
