# İsteğe bağlı ses modelleri

Normal kurulum ses modellerini veya motorlarını indirmez. Model dosyalarının bulunması, üretimin çalıştığı anlamına gelmez. Entegre üretim kontrolleri başarılı motor doğrulaması gerektirir.

| Paket | Amaç | Kullanılan model |
| --- | --- | --- |
| `tts` | Metin seslendirme ve referansla klonlama | VoxCPM2 |
| `conversion` | Mevcut konuşmayı başka sesle yeniden üretme | Seed-VC |
| `singing` | Ayrılmış vokalin sesini dönüştürme | Seed-VC SVC |
| `separation` | Ayrı denemeler için vokal ayırma ağırlıkları | HTDemucs |

Şarkı dönüşümü yeni söz, beste veya altyapı üretmez; kaydın dilini değiştirmez. Tam miks içindeki enstrümanlar dönüşüm sırasında otomatik ayrılmaz. HTDemucs dosyalarının indirilmesi, uygulamada ayrı bir ayırma iş akışı sunulduğu anlamına gelmez.

## Dosyaları indirme

Depo kökünde, standart Python ile:

```bash
python3 scripts/download_audio_models.py --list
python3 scripts/download_audio_models.py --packs tts --plan
python3 scripts/download_audio_models.py --packs tts
```

Konuşma veya şarkı için `--packs conversion` ya da `--packs singing` seçilebilir. Paket belirtilmezse manifestteki tüm paketler seçilir. Yalnızca ihtiyacınız olanları indirin.

Varsayılan kök `~/AI/models/audio/`. `AI_WORKSTATION_MODEL_DIR` dışa aktarılmışsa onun `audio/` alt dizini kullanılır; `--root /path/to/audio` açıkça başka konum seçer. Uygulamayla aynı kökü kullanın. Bu ayrı betikler `.env` dosyasını otomatik okumaz.

Manifest `scripts/audio-models.json` içindedir; indirilen depoların kaynak ve dosya listelerini buradan inceleyin. Modellerin ve yardımcı bileşenlerin lisansları uygulama kodunun MIT lisansından ayrıdır. Kaynak kodu ve ağırlıkları kullanmadan önce kendi koşullarını okuyun.

İndirici metadata sorgusuyla revizyonları `download-lock.json` içine sabitler. Büyük dosyalarda SHA-256, küçük Hugging Face dosyalarında Git blob SHA-1; doğrudan HTDemucs dosyasında SHA-256 öneki kontrol edilir. Yarım indirmeler `.part` olarak tutulur; doğrulanmış dosyalar yeniden indirilmez. `--plan` dosya listesi ve metadata için ağ erişimi kullanır, ağırlıkları indirmez.

## Motor kurulumu

İsteğe bağlı motor kurulum betiği ayrıca `uv`, paket depolarına erişim ve uygun donanım gerektirir. Modelleri indirdikten sonra:

```bash
bash scripts/install_audio_runtime.sh tts --smoke
bash scripts/install_audio_runtime.sh conversion
```

Varsayılan GPU yolu AMD gfx1030 odaklı ROCm paketleri kurar; farklı AMD/NVIDIA donanımları için genel kurulum betiği değildir. CPU tanılaması için `--cpu` vardır; uygulamanın TTS hazır olma kontrolü başarılı ROCm probe'u ister. Motorlar depo altındaki `runtime/audio-*` sanal ortamlarına kurulur, ana backend ortamına eklenmez.

Konuşma ve şarkı modlarını kendi/izinli kayıtlarınızla ayrı doğrulayın; komutlar [kurulum belgesinde](INSTALLATION.md) bulunur. Çıktı ve probe dosyaları `runtime/` altında kalır ve Git'e eklenmez. Bir motorun doğrulanması diğer modun da çalıştığını göstermez. GPU modellerini aynı anda yüklemeyin.

Tarayıcıdaki ses profilleri IndexedDB'de tutulur; tarayıcı verilerini temizlemek profilleri siler. Tamamlanan üretim çıktıları uygulamanın veri dizinindedir. Kaynak ve referans kayıtlara ilişkin hak/izin sahibi olun; kişisel kayıtları hata raporlarına eklemeyin.

## Kaynaklar

- [VoxCPM](https://github.com/OpenBMB/VoxCPM)
- [VoxCPM2 ağırlıkları](https://huggingface.co/openbmb/VoxCPM2)
- [Seed-VC](https://github.com/Plachtaa/seed-vc)
- [Seed-VC ağırlıkları](https://huggingface.co/Plachta/Seed-VC)
- [Demucs](https://github.com/facebookresearch/demucs)
