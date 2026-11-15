"""Small allow-listed model catalog; scans only the configured model root."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL_ROOT = Path.home() / "AI/models"


@dataclass(frozen=True)
class Asset:
    filename: str
    relative_path: str
    expected_bytes: int | None
    expected_size_label: str
    sha256: str
    source: str


@dataclass(frozen=True)
class Model:
    id: str
    name: str
    format: str
    license: str
    assets: tuple[Asset, ...]
    warning: str


CATALOG: tuple[Model, ...] = (
    Model(
        id="gemma-4-12b-it-q4_0",
        name="Gemma 4 12B IT Q4_0",
        format="GGUF Q4_0 + GGUF Q8_0 mmproj",
        license="Apache-2.0 (ggml-org conversion; upstream Gemma terms also apply)",
        assets=(
            Asset(
                "gemma-4-12B-it-Q4_0.gguf",
                "gemma-4-12b/gemma-4-12B-it-Q4_0.gguf",
                7_219_673_216,
                "7,219,673,216 bayt",
                "3712b9bd32cae83a22f67ee7a4466d8d7a4f21646ac8a07d19bf9418e8767a70",
                "https://huggingface.co/ggml-org/gemma-4-12B-it-GGUF/blob/main/gemma-4-12B-it-Q4_0.gguf",
            ),
            Asset(
                "mmproj-gemma-4-12B-it-Q8_0.gguf",
                "gemma-4-12b/mmproj-gemma-4-12B-it-Q8_0.gguf",
                158_987_648,
                "158,987,648 bayt",
                "6b1088334bda27d7f293dcf426c0efaf1f1f20b65415ea354b695dbed9a0d65d",
                "https://huggingface.co/ggml-org/gemma-4-12B-it-GGUF/blob/main/mmproj-gemma-4-12B-it-Q8_0.gguf",
            ),
        ),
        warning="Metin sohbeti uygulama API üzerinden doğrulandı. Görsel girdi bu arayüzde sunulmuyor.",
    ),
    Model(
        id="z-image-turbo",
        name="Z-Image Turbo",
        format="ComfyUI INT8 ConvRot + Qwen3 FP8 + VAE",
        license="Apache-2.0 (Comfy-Org repack)",
        assets=(
            Asset(
                "z_image_turbo_int8_convrot.safetensors",
                "Z-image turbo/z_image_turbo_int8_convrot.safetensors",
                None,
                "6,2 GB; SHA-256 henüz sabitlenmedi",
                "",
                "https://huggingface.co/Comfy-Org/z_image_turbo",
            ),
            Asset(
                "qwen_3_4b_fp8_mixed.safetensors",
                "Z-image turbo/qwen_3_4b_fp8_mixed.safetensors",
                None,
                "5.63 GB (kaynağın yuvarlanmış gösterimi)",
                "72450b19758172c5a7273cf7de729d1c17e7f434a104a00167624cba94f68f15",
                "https://huggingface.co/Comfy-Org/Z-Image-Turbo/blob/main/split_files/text_encoders/qwen_3_4b_fp8_mixed.safetensors",
            ),
            Asset(
                "ae.safetensors",
                "Z-image turbo/ae.safetensors",
                None,
                "335 MB (kaynağın yuvarlanmış gösterimi)",
                "afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38",
                "https://huggingface.co/Comfy-Org/Z-Image-Turbo/blob/main/split_files/vae/ae.safetensors",
            ),
        ),
        warning="INT8 sürümü kullanılır. RX 6800 XT için eager INT8 uyumluluk yaması ve bellek sınırlı servis gereklidir; BF16 bu makinede kullanılmaz.",
    ),
    Model(
        id="flux2-klein", name="FLUX.2 klein 4B", format="FP8 + Qwen3 FP8 + VAE",
        license="Model kaynağındaki lisans koşullarına bakın",
        assets=(
            Asset("flux-2-klein-4b-fp8.safetensors", "flux2-klein/flux-2-klein-4b-fp8.safetensors", None, "FP8 model; boyut dosyadan okunur", "", "https://huggingface.co/black-forest-labs/FLUX.2-klein-4b-fp8"),
            Asset("flux2-vae.safetensors", "flux2-klein/flux2-vae.safetensors", None, "VAE; boyut dosyadan okunur", "", "https://huggingface.co/Comfy-Org/flux2-dev"),
            Asset("qwen_3_4b_fp8_mixed.safetensors", "Z-image turbo/qwen_3_4b_fp8_mixed.safetensors", None, "Z-Image ile paylaşılan kodlayıcı", "", "https://huggingface.co/Comfy-Org/Z-Image-Turbo"),
        ),
        warning="Görsel düzenleme iş akışı; dosya varlığı kalite ve hash doğrulaması değildir.",
    ),
    Model(
        id="qwen3.5-9b-q8_0",
        name="Qwen 3.5 9B Q8_0",
        format="GGUF Q8_0 (metin; görsel girdi için ayrı doğrulanmış mmproj gerekir)",
        license="Apache-2.0 (upstream Qwen lisansı; GGUF dönüşüm kaynağı ayrıca doğrulanır)",
        assets=(
            Asset(
                "qwen3.5-9b-Q8_0.gguf",
                "qwen3.5-9b/qwen3.5-9b-Q8_0.gguf",
                None,
                "9.8 GB (kaynak gösterimi)",
                "b58fe056b5435070240de259f3f981aa38fee96825bbd78c088d5fd90e46f2b5",
                "https://huggingface.co/gguf/Qwen3.5-9B-GGUF/blob/main/qwen3.5-9b-Q8_0.gguf",
            ),
        ),
        warning="Metin sohbeti uygulama API üzerinden AMD Vulkan ile doğrulandı. Hash kontrolü envanter sorgusunda yapılmaz.",
    ),
    Model(
        id="gpt-oss-20b-mxfp4",
        name="gpt-oss-20b MXFP4",
        format="GGUF MXFP4",
        license="Apache-2.0",
        assets=(
            Asset(
                "gpt-oss-20b-MXFP4.gguf",
                "gpt-oss-20b/gpt-oss-20b-MXFP4.gguf",
                None,
                "12.1 GB (kaynak gösterimi)",
                "27cd6c432c7672cb812a92f611cf3ba7bbc35928262bb1e1253ff4ee6ae35901",
                "https://huggingface.co/ggml-org/gpt-oss-20b-GGUF/blob/main/gpt-oss-20b-MXFP4.gguf",
            ),
        ),
        warning="Metin sohbeti uygulama API üzerinden AMD Vulkan ile doğrulandı. 16 GB VRAM nedeniyle bağlam 2048 token ile sınırlıdır.",
    ),

)


def model_root() -> Path:
    """Use a fixed user-selected root; environment override is explicit."""
    return Path(os.environ.get("AI_WORKSTATION_MODEL_DIR", DEFAULT_MODEL_ROOT)).expanduser()


def _safe_asset_path(root: Path, relative: str) -> Path:
    candidate = root / relative
    resolved_root = root.resolve()
    resolved = candidate.resolve(strict=False)
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError("Model yolu izin verilen kökün dışına çıkıyor.")
    return candidate


def inspect_catalog(*, verify_hashes: bool = False) -> list[dict[str, object]]:
    root = model_root()
    results: list[dict[str, object]] = []
    for model in CATALOG:
        asset_results: list[dict[str, object]] = []
        present = True
        verified = True
        for asset in model.assets:
            path = _safe_asset_path(root, asset.relative_path)
            exists = path.is_file()
            size = path.stat().st_size if exists else None
            size_matches = size == asset.expected_bytes if exists and asset.expected_bytes is not None else None
            digest_matches: bool | None = None
            if verify_hashes and exists and asset.sha256:
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                        digest.update(block)
                digest_matches = digest.hexdigest() == asset.sha256
            present &= exists
            verified &= digest_matches is True
            asset_results.append(
                {
                    "filename": asset.filename,
                    "path": str(path),
                    "expected_bytes": asset.expected_bytes,
                    "expected_size_label": asset.expected_size_label,
                    "actual_bytes": size,
                    "present": exists,
                    "size_matches": size_matches,
                    "hash_verified": digest_matches,
                    "sha256_expected": asset.sha256,
                    "source": asset.source,
                }
            )
        if not present:
            status = "missing"
        elif verify_hashes and verified:
            status = "hash_verified"
        else:
            status = "files_present_hash_not_checked"
        results.append(
            {
                "id": model.id,
                "name": model.name,
                "format": model.format,
                "license": model.license,
                "status": status,
                "assets": asset_results,
                "warning": model.warning,
            }
        )
    return results
