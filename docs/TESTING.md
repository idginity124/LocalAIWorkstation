# Testler

Depo kökünde, `bash setup.sh` sonrasında:

```bash
PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python -m unittest discover -s backend/tests -q
backend/.venv/bin/python -m unittest discover -s scripts/tests -q
npm --prefix frontend run build
npm --prefix frontend run test:i18n
bash -n start.sh setup.sh
```

Backend testleri geçici veriler ve taklit çıkarım servisleriyle sohbet/SSE, bağlam bütçesi, iptal, dosya sınırları, onaylı diff yazma, model kataloğu, GPU kilidi, görsel işleri, ses işleri, belge yardımcıları ve yedekleme davranışını sınar. Ses testleri FFmpeg gerektirir. Betik testleri indirme hash'lerini, devam ettirmeyi ve çevrimdışı model önbelleğini sınar. Hiçbiri gerçek GPU üretiminin veya model kalitesinin kanıtı değildir.

Arayüz derlemesi TypeScript ve Vite kontrolüdür. `test:i18n`, dil katalogları, 11 dilde sunucu tarafı bileşen çıktıları ve istemci akışlarının regresyonlarını denetler; görsel tarayıcı testi değildir.

GitHub Actions Python 3.12/3.14 backend testlerini, betik testlerini, shell sözdizimini, Node.js 22 arayüz derlemesini ve çeviri kontrollerini çalıştırır. Bu iş akışı ancak GitHub'a gönderildikten sonra uzak ortamda doğrulanmış olur.

## Tarayıcı testleri

Playwright'ın kendi Chromium sürümünü kurun:

```bash
cd frontend
npx playwright install chromium
```

Gerekirse Linux tarayıcı sistem bağımlılıklarını Playwright'ın talimatlarına göre kurun. Ayrı terminalde `bash start.sh` ile uygulamayı açın. Kişisel sohbetlerinizle karışmaması için test sırasında ayrı veri dizini kullanın:

```bash
AI_WORKSTATION_DATA="$(mktemp -d)" bash start.sh
```

Yerel `.env` içindeki `AI_WORKSTATION_DATA` bu değeri geçersiz kılabilir; test öncesinde `.env` dosyasını kontrol edin. Sonra `npm --prefix frontend run test:e2e` çalıştırın. Testler gerçek model yerine taklit API yanıtları da kullanır. Ekran görüntüleri `runtime-reports/` altında üretilir; raporlar ve test çıktıları Git kapsamı dışındadır.

## Gerçek motor denemeleri

`scripts/gemma_gpu_smoke.sh`, `scripts/llm_gpu_smoke.sh`, görsel deneme betikleri ve ses/Krita probe'ları isteğe bağlıdır. Yerel dosyalar, uygun donanım ve boş GPU gerektirirler. Bunları CI birim testlerinden ayrı çalıştırın. Raporlar yerel kalır; önceki bilgisayardan alınmış özel raporlar kaynak sürümüne dahil edilmez.
