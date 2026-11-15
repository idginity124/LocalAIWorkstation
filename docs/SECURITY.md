# Güvenlik modeli

Uygulama tek kullanıcılı Linux masaüstü içindir. Çok kullanıcılı kimlik doğrulaması yoktur; internete veya LAN'a sunulması desteklenmez.

- Varsayılan dinleme adresi `127.0.0.1`. API, loopback istemciyi, izinli Host/Origin değerlerini ve değiştiren isteklerde süreç başına CSRF belirtecini denetler.
- Sohbet motoru yerel `llama-server` sürecidir. İstemci ortam proxy ayarlarını yok sayar; model API anahtarı çalışma anında üretilir. CPU veya Vulkan modu arayüzden seçilir.
- Sohbetler, işler ve tercihler yerel veri dizininde, ses profilleri tarayıcının IndexedDB deposunda kalır. Bunlar Git'e eklenmemelidir. Günlükler ve tanılama raporları yerel yollar içerebilir; paylaşmadan önce inceleyin.
- Kod erişimi kayıtlı proje köküyle sınırlıdır. Symlink'ler, gizli/hassas dosyalar ve kök dışı yollar reddedilir. UTF-8 dosya boyutu sınırlıdır.
- Kod değişiklikleri saklanan diff, açık kullanıcı onayı ve beklenen hash doğrulaması üzerinden uygulanır. Modelin ürettiği shell komutları çalıştırılmaz.
- Yanıt iptali HTTP akışının kapatılması üzerinden yapılır; modelin bellekte tutulması amaçlanır. Servis kapatma/boşaltma ayrı işlemdir. Harici süreçler sahiplenilmez.
- Yönetilen GPU servisleri ortak kilit kullanır. Bellek ve süreç kurtarma kontrolleri bulunur; bunlar tüm donanımlar için uyumluluk garantisi değildir.
- Ses klonlama için kaynak üzerinde hak/izin gerekir. Ses örnekleri ve kişisel çıktılar yayın paketine dahil edilmez.
- `start.sh` isteğe bağlı `.env` dosyasını Bash olarak çalıştırır. Bu dosyayı kod gibi değerlendirin ve yalnızca güvendiğiniz içeriği kullanın.
- Model/bağımlılık indirme araçları ağ erişimi kullanır. Tüm modellerin sabit hash'i bulunmaz; yalnızca dosyanın varlığı güvenilirlik veya lisans doğrulaması sayılmaz. Ayrı motorlar kendi kodlarını çalıştırır; kurulumdan önce kaynaklarını inceleyin.

Dosya erişimi, stale diff, onay ve API güvenlik kontrolleri backend testleriyle sınanır. Testlerin geçmesi bağımsız güvenlik denetimi anlamına gelmez. Hassas bir bulguyu kamuya açık issue yerine depo sahibine özel olarak bildirin; [SECURITY](../SECURITY.md) dosyasına bakın.
