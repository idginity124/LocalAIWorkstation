#!/usr/bin/env bash
# Only the authorized local editing assets; never upgrade Comfy/PyTorch/ROCm.
set -euo pipefail
ROOT="${AI_WORKSTATION_COMFYUI_DIR:-$HOME/AI/ComfyUI}"
NODE_REV=d4a318f00fffbd269418057f869e9bc912832229
NODE="$ROOT/custom_nodes/comfyui-inpaint-nodes"
command -v curl >/dev/null
command -v git >/dev/null
[[ -x "$ROOT/.venv/bin/python" ]] || { echo 'ComfyUI Python ortamı bulunamadı.'; exit 1; }
"$ROOT/.venv/bin/python" - <<'PY'
import importlib.util
missing=[name for name in ('spandrel','kornia') if importlib.util.find_spec(name) is None]
if missing: raise SystemExit('ComfyUI bağımlılıkları eksik: '+', '.join(missing)+'. Paket yükseltmeden bağımlılıkları kontrol edin.')
PY
fetch() {
  local url="$1" target="$2" expected="$3" actual
  mkdir -p "$(dirname "$target")"
  if [[ -f "$target" ]]; then
    actual=$(sha256sum "$target"); actual=${actual%% *}
    [[ "$actual" == "$expected" ]] || { echo "Var olan dosya beklenen SHA256 ile eşleşmiyor: $target"; exit 1; }
    echo "Doğrulandı: $(basename "$target")"; return
  fi
  echo "İndiriliyor: $(basename "$target")"
  curl --fail --location --retry 3 --connect-timeout 20 --continue-at - --output "$target.part" "$url"
  actual=$(sha256sum "$target.part"); actual=${actual%% *}
  [[ "$actual" == "$expected" ]] || { echo "SHA256 uyuşmuyor; dosya etkinleştirilmedi: $target.part"; exit 1; }
  mv -- "$target.part" "$target"
}
# 206MB LaMa mirror, byte identity checked against the published artifact digest.
fetch 'https://huggingface.co/gaspardbruno/BigLama/resolve/main/big-lama.pt' "$ROOT/models/inpaint/big-lama.pt" 344c77bbcb158f17dd143070d1e789f38a66c04202311ae3a258ef66667a9ea9
# Standard SDXL checkpoint and Fooocus patch from the Krita AI model manifest.
fetch 'https://huggingface.co/SG161222/RealVisXL_V5.0/resolve/main/RealVisXL_V5.0_fp16.safetensors' "$ROOT/models/checkpoints/RealVisXL_V5.0_fp16.safetensors" 6a35a7855770ae9820a3c931d4964c3817b6d9e3c6f9c4dabb5b3a94e5643b80
fetch 'https://huggingface.co/lllyasviel/fooocus_inpaint/resolve/main/fooocus_inpaint_head.pth' "$ROOT/models/inpaint/fooocus_inpaint_head.pth" 32f7f838e0c6d8f13437ba8411e77a4688d77a2e34df8857e4ef4d51f6b97692
fetch 'https://huggingface.co/lllyasviel/fooocus_inpaint/resolve/main/inpaint_v26.fooocus.patch' "$ROOT/models/inpaint/inpaint_v26.fooocus.patch" f8657a025104e22d70f9c060635d8e8c2196f433871a2f68dc40abd2171f0d59
if [[ -d "$NODE" ]]; then
  echo 'Var olan inpaint düğüm paketi korundu; güncellenmedi.'
else
  mkdir -p "$ROOT/custom_nodes"
  STAGE=$(mktemp -d "$ROOT/custom_nodes/.inpaint-setup-XXXXXX")
  trap 'rm -rf -- "$STAGE"' EXIT
  git -C "$STAGE" init -q
  git -C "$STAGE" remote add origin https://github.com/Acly/comfyui-inpaint-nodes.git
  git -C "$STAGE" fetch -q --depth 1 origin "$NODE_REV"
  git -C "$STAGE" checkout -q --detach FETCH_HEAD
  [[ "$(git -C "$STAGE" rev-parse HEAD)" == "$NODE_REV" ]]
  mv -- "$STAGE" "$NODE"
  trap - EXIT
fi
printf '\n%s\n' 'Modeller hazır. AI uygulamasını yeniden açın; ComfyUI için Durdur → Başlat yapın.'
printf '%s\n' 'Krita’da mor alanı boyayın; Hızlı sil, Alanı doldur veya Yazıyı değiştir seçin.'
