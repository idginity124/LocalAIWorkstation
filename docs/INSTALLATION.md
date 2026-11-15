# Kurulum

## Gereksinimler

- Linux masaüstü; ilk donanım denemeleri CachyOS / KDE / AMD RX 6800 XT üzerinde yapıldı.
- Python 3.12–3.14 ve venv/pip desteği; Node.js 22+ ve npm.
- Sohbet için ayrıca güncel, katalogdaki model mimarilerini destekleyen `llama-server` ve uygun CPU/Vulkan arka ucu.
- Görsel üretimi için ayrı ComfyUI kurulumu, `.venv/bin/python` ve çalışan systemd kullanıcı oturumu.
- Ses işlemleri için FFmpeg; isteğe bağlı ses motorlarının bağımlılıkları ayrı ortamlara kurulur.

Model olmadan arayüz açılabilir. Eksik model/motor üretim kontrollerini devre dışı bırakır. Sistem Python'ına paket kurulmaz; `setup.sh` backend için sanal ortam oluşturur.

## Uygulamayı kurma

GitHub'dan indirdiğiniz veya klonladığınız depo klasöründe:

```bash
bash setup.sh
cp .env.example .env
bash start.sh
```

Kurulum paket depolarına internet erişimi gerektirir. `setup.sh` model, ComfyUI, PyTorch veya GPU sürücüsü indirmez. Mevcut `.env` dosyanız varsa kopyalama adımını atlayın.

Normal başlatma arayüzü derler ve API ile aynı adreste sunar: **http://127.0.0.1:8000**. `Ctrl+C` ile kapatın. `bash start.sh --dev` arayüzü 5173, API'yi 8000 portunda açar; meşgul porttaki servisler kapatılmaz.

## Yapılandırma

`.env.example` dosyasını temel alın:

| Değişken | Varsayılan |
| --- | --- |
| `AI_WORKSTATION_MODEL_DIR` | `$HOME/AI/models` |
| `AI_WORKSTATION_COMFYUI_DIR` | `$HOME/AI/ComfyUI` |
| `AI_WORKSTATION_DATA` | `$HOME/.local/share/ai-workstation` |

`start.sh` proje kökündeki `.env` dosyasını Bash olarak okur ve değişkenleri alt süreçlere aktarır. Yalnızca güvendiğiniz yerel dosyayı kullanın. Ayrı betikleri veya uvicorn'u doğrudan çalıştırırken bu değişkenleri terminalde `export` edin. Uygulama geliştirme amaçlı düzenlenebilir kurulumla depo içinden çalıştırılır; tek başına Python wheel dağıtımı desteklenmez.

## Sohbet modelleri

`llama-server --list-devices` ile motorun aygıt keşfini kendi terminalinizde kontrol edin. CPU modu arayüzden seçilebilir; GPU modu Vulkan0 aygıtını ve model başına sabit kaynak eşiklerini kullanır. Farklı donanımlar ayrıca doğrulama gerektirir. Dosya yolları katalogda sabittir:

```text
$AI_WORKSTATION_MODEL_DIR/
├── gemma-4-12b/
│   ├── gemma-4-12B-it-Q4_0.gguf
│   └── mmproj-gemma-4-12B-it-Q8_0.gguf
├── qwen3.5-9b/
│   └── qwen3.5-9b-Q8_0.gguf
└── gpt-oss-20b/
    └── gpt-oss-20b-MXFP4.gguf
```

Kaynak bağlantıları ve mevcut hash bilgileri `backend/app/catalog.py` içinde bulunur. Her modelin lisans koşullarını kaynağında okuyun. Varlık denetimi hash doğrulaması değildir. Kullanıcı tarafından seçilen kökün dışına yönlendiren model symlink'leri reddedilir. LM Studio'nun kendi model dizini bu uygulamanın katalog düzeniyle aynı değildir.

Uygulama kendi `llama-server` sürecini başlatır. LM Studio veya Ollama API bağlantısı yoktur. Aynı GPU'da başka bir ağır model çalıştırıyorsanız onu kendi uygulamasından boşaltın.

## ComfyUI

ComfyUI'yi kendi resmî kurulum talimatlarıyla ayrı dizine kurun ve bağımlılıklarını `.venv` altında hazırlayın. Projedeki `workflows/` dizini API şablonlarını içerir. Uygulama mevcut modeller için çalışma anında ek model yolu yapılandırması oluşturur.

Beklenen görsel dosyaları:

```text
$AI_WORKSTATION_MODEL_DIR/
├── Z-image turbo/
│   ├── z_image_turbo_int8_convrot.safetensors
│   ├── qwen_3_4b_fp8_mixed.safetensors
│   └── ae.safetensors
└── flux2-klein/
    ├── flux-2-klein-4b-fp8.safetensors
    └── flux2-vae.safetensors
```

FLUX paylaşılan Qwen kodlayıcısını kullanır; `scripts/download_flux2_klein.sh` isteğe bağlı indirme aracıdır. INT8 Z-Image ve FP8 modellerinin eski AMD kartlarında uyumluluğu kurulu ComfyUI/PyTorch sürümlerine bağlıdır. Önceki tek makine denemesinde `comfy_kitchen` eager INT8 yaması kullanılmıştır; bu yama depoyla dağıtılmaz. Bu nedenle temiz kurulumda aynı GPU sonucunu garanti etmiyoruz.

ComfyUI `systemd-run --user` ile yönetilir; `--fast-disk --disable-async-offload --cache-classic` seçenekleri kullanılır. En az 10 GiB kullanılabilir RAM gerekir. Servis en fazla 10 GiB RAM ve 512 MiB swap kullanır. Bu eşikler küçük sistemlerde görsel üretimini engelleyebilir. Çıktılar `ComfyUI/output/LocalAIWorkstation/` altındadır.

## İsteğe bağlı ses ve Krita

Ses modelleri ve indirme paketleri: [AUDIO_MODELS](AUDIO_MODELS.md). Ses motorları AMD ROCm odaklıdır; normal uygulama kurulumu bunları yüklemez. `--cpu` tanılama kurulumu yapılabilse de entegre TTS hazır olma kontrolü başarılı ROCm doğrulaması ister.

```bash
python3 scripts/download_audio_models.py --list
# İlgili lisans ve indirme içeriğini inceledikten sonra:
python3 scripts/download_audio_models.py --packs tts
bash scripts/install_audio_runtime.sh tts --smoke
```

Seed-VC için `bash scripts/install_audio_runtime.sh conversion` kullanılır. Konuşma ve şarkı modları ayrı ayrı, size ait/izinli kaynak ve referans kayıtlarıyla doğrulanmalıdır:

```bash
runtime/audio-conversion/.venv/bin/python scripts/probe_audio_conversion.py --mode conversion --source /path/to/source.wav --reference /path/to/reference.wav
runtime/audio-conversion/.venv/bin/python scripts/probe_audio_conversion.py --mode singing --source /path/to/source.wav --reference /path/to/reference.wav
```

Krita editörü için Krita, uyumlu Qt/Python bağları, Xvfb ve xauth gerekir. [Krita entegrasyonu](KRITA_INTEGRATION.md) kurulum ve sınırları açıklar.

## Yedekleme

Uygulama kapalıyken yapılandırılmış veri dizinini, görsel çıktılarını ve ihtiyacınız olan dışa aktarılmış KRA/PNG dosyalarını ayrı yedekleyin. Git kaynak yedeğidir; sohbetlerinizi, kayıtlarınızı ve modellerinizi içermez.
