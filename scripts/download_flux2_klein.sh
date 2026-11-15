#!/usr/bin/env bash
# FLUX.2 [klein] 4B (FP8) görsel düzenleme modeli — kaynak: ComfyUI resmi şablonu.
# Kullanım: bash scripts/download_flux2_klein.sh
# Kesilirse aynı komutu tekrar çalıştırın; indirme kaldığı yerden devam eder.
set -euo pipefail

DEST="${AI_WORKSTATION_MODEL_DIR:-$HOME/AI/models}/flux2-klein"
mkdir -p "$DEST"

fetch() {
  local url="$1" name="$2"
  if [[ -s "$DEST/$name" ]]; then
    printf '%s\n' "Zaten var, atlandı: $name"
    return
  fi
  printf '%s\n' "İndiriliyor: $name"
  curl -L --fail -C - -o "$DEST/$name.part" "$url"
  mv "$DEST/$name.part" "$DEST/$name"
}

# ~3,8 GB diffusion modeli (Apache 2.0)
fetch "https://huggingface.co/black-forest-labs/FLUX.2-klein-4b-fp8/resolve/main/flux-2-klein-4b-fp8.safetensors" "flux-2-klein-4b-fp8.safetensors"
# ~320 MB VAE (FLUX.1 VAE'sinden farklıdır; Z-Image'ın ae.safetensors dosyası kullanılamaz)
fetch "https://huggingface.co/Comfy-Org/flux2-dev/resolve/main/split_files/vae/flux2-vae.safetensors" "flux2-vae.safetensors"

# Metin kodlayıcı (Qwen3 4B): varsayılan olarak Z-Image klasöründeki qwen_3_4b_fp8_mixed kullanılır.
# O dosya çalışmazsa resmî ~7,5 GB sürümü için: bash scripts/download_flux2_klein.sh --with-qwen
if [[ "${1:-}" == "--with-qwen" ]]; then
  fetch "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors" "qwen_3_4b.safetensors"
fi

printf '%s\n' "Tamam. ComfyUI'yi yeniden başlatın (uygulamada Durdur → Başlat)."
ls -lh "$DEST"
