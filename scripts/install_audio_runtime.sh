#!/usr/bin/env bash
# Separate audio environments. Model weights are reused, never downloaded again.
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
AUDIO_ENGINE=tts
AUDIO_DEVICE=rocm
AUDIO_SMOKE=0
for arg in "$@"; do
  case "$arg" in
    tts|conversion|separation) AUDIO_ENGINE="$arg" ;;
    --cpu) AUDIO_DEVICE=cpu ;;
    --smoke) AUDIO_SMOKE=1 ;;
    *) printf 'Bilinmeyen seçenek: %s\n' "$arg" >&2; exit 2 ;;
  esac
done
command -v uv >/dev/null || { printf '%s\n' 'uv bulunamadı.' >&2; exit 1; }
AUDIO_RUNTIME="$PROJECT_DIR/runtime/audio-$AUDIO_ENGINE"
AUDIO_PY_VERSION=3.12
if [[ "$AUDIO_ENGINE" == conversion ]]; then AUDIO_PY_VERSION=3.11; fi
mkdir -p "$AUDIO_RUNTIME"
uv venv --allow-existing --python "$AUDIO_PY_VERSION" "$AUDIO_RUNTIME/.venv"
AUDIO_PY="$AUDIO_RUNTIME/.venv/bin/python"
if [[ "$AUDIO_DEVICE" == rocm ]]; then
  uv pip install --python "$AUDIO_PY" --index-url https://stable.repo.amd.com/rocm/whl-next/ 'torch[device-gfx1030]' 'torchvision[device-gfx1030]' torchaudio
else
  uv pip install --python "$AUDIO_PY" --index-url https://download.pytorch.org/whl/cpu torch==2.8.0 torchaudio==2.8.0 torchvision==0.23.0
fi
# Preserve the installed CPU/AMD torch family when resolving engine dependencies.
uv pip freeze --python "$AUDIO_PY" > "$AUDIO_RUNTIME/torch-install.txt"
"$AUDIO_PY" - "$AUDIO_RUNTIME" <<'PY'
from pathlib import Path
import sys
root=Path(sys.argv[1])
lines=[line for line in (root/'torch-install.txt').read_text().splitlines() if line.lower().startswith(('torch==','torchaudio==','torchvision==','rocm'))]
(root/'torch-constraints.txt').write_text('\n'.join(lines)+'\n')
PY
case "$AUDIO_ENGINE" in
  tts)
    uv pip install --python "$AUDIO_PY" --constraint "$AUDIO_RUNTIME/torch-constraints.txt" 'voxcpm>=2,<3'
    ;;
  conversion)
    if [[ ! -d "$AUDIO_RUNTIME/source/.git" ]]; then
      git clone --depth 1 https://github.com/Plachtaa/seed-vc.git "$AUDIO_RUNTIME/source"
    fi
    "$AUDIO_PY" - "$AUDIO_RUNTIME" <<'PY'
from pathlib import Path
import sys
root=Path(sys.argv[1])
lines=[line for line in (root/'source/requirements.txt').read_text().splitlines() if not line.strip().lower().startswith(('torch ', 'torch==', 'torchvision ', 'torchvision==', 'torchaudio ', 'torchaudio=='))]
(root/'engine-requirements.txt').write_text('\n'.join(lines)+'\n')
PY
    uv pip install --python "$AUDIO_PY" --constraint "$AUDIO_RUNTIME/torch-constraints.txt" -r "$AUDIO_RUNTIME/engine-requirements.txt"
    git -C "$AUDIO_RUNTIME/source" rev-parse HEAD > "$AUDIO_RUNTIME/source-commit.txt"
    "$AUDIO_PY" "$PROJECT_DIR/scripts/prepare_audio_cache.py" --seed-source "$AUDIO_RUNTIME/source"
    ;;
  separation)
    uv pip install --python "$AUDIO_PY" --constraint "$AUDIO_RUNTIME/torch-constraints.txt" demucs==4.0.1
    ;;
esac
uv pip check --python "$AUDIO_PY"
uv pip freeze --python "$AUDIO_PY" > "$AUDIO_RUNTIME/installed-requirements.txt"
AUDIO_PROBE_ARGS=(--engine "$AUDIO_ENGINE" --device "$AUDIO_DEVICE")
if [[ "$AUDIO_SMOKE" == 1 ]]; then AUDIO_PROBE_ARGS+=(--smoke); fi
"$AUDIO_PY" "$PROJECT_DIR/scripts/probe_audio_runtime.py" "${AUDIO_PROBE_ARGS[@]}"
