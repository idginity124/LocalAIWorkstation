# Mimari

## İstemci

`frontend/src/App.tsx` uygulama kabuğu, tema, gezinme ve telemetriyi yönetir. `pages/` sohbet, görsel, kod ve model envanteri ekranlarını içerir. `lib/shared.tsx` HTTP/SSE taşıması ve Markdown bileşenlerini paylaşır. `theme.css` tek stil girişidir.

Ziyaret edilen çalışma ekranları gezinme sırasında kaldırılmaz; gizlenir. Böylece devam eden SSE akışı, editör ve üretim formu korunur. Sohbet taslağı ve son sohbet seçimi tarayıcıda saklanır. Tam yenilemede sohbet akışı iptal edilir; görsel işleri API üzerinden yeniden bulunur.

## Sunucu ve kalıcılık

FastAPI yalnızca 127.0.0.1 üzerinde dinler. Üretim derlemesi API ile aynı 8000 portundan sunulur; geliştirmede Vite 5173 üzerinden API'ye proxy yapar. Host/Origin kontrolleri ve mutasyonlarda CSRF korunur.

SQLite şema sürümü 4 korunur. Mevcut sohbetler, projeler ve ayarlar değiştirilmez. Görsel işleri mevcut `jobs` tablosuna, sonuç/hata bilgileri `history` tablosuna yazılır. Görsel verisi iş tablosuna kopyalanmaz; tekrar istek kontrolü için girdinin SHA-256 özeti kullanılır. Her görsel iş thread'i ayrı SQLite bağlantısı açar.

`ImageJobs` tek etkin işe izin verir, tekrar istek anahtarını doğrular ve işi HTTP bağlantısından bağımsız bir worker'da çalıştırır. Uygulama yeniden başladığında yarım işler `RECOVERY_REQUIRED` olur; kendiliğinden tekrar gönderilmez. İptal yalnızca uygulamanın gönderdiği Comfy prompt kimliğine uygulanır. İptal doğrulanamazsa yalnızca uygulamanın oluşturduğu görsel servisi kapatılır.

## GPU ve süreçler

LLM adaptörleri ve ComfyManager aynı `GpuResourceManager` örneğini paylaşır. Kilit farklı thread/event loop'lardan kullanım için korunur. Kilit servis yaşamı boyunca tutulur; kapatma sonrası VRAM başlangıç bandına dönmeden bırakılmaz. Harici servisler sahiplenilmez.

ComfyUI `systemd-run --user` ile ayrı bir servis olarak çalışır. Başlangıçta kullanılabilir RAM ≥10 GiB şartı vardır; MemoryMax en çok 10 GiB, MemorySwapMax 512 MiB ve OOMPolicy=stop uygulanır. GPU modellerinin disk destekli yüklenmesi ve eşzamansız offload'un kapatılması ilk AMD denemelerindeki RAM baskısını azaltır. Model ağırlıkları veya sistem sürücüleri değiştirilmez.

LLM yanıt iptali üretimin iptal olayını işaretler; model süreci yüklü kalır. Yeni mesaj, mevcut stream kapanınca gönderilir. Uygulama kapanışında worker tamamlanır/iptal edilir ve uygulamanın yönettiği servisler durdurulur.

Günlükler `AI_WORKSTATION_DATA/logs/` altında tutulur. Genel Bakış ekranı sınırlı son günlük metnini gösterir; model API anahtarları bu yanıtta sansürlenir.
