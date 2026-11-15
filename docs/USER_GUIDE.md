# Kullanım

## Sohbet

Asistan ekranında model seçip **Modeli yükle** düğmesine basın. Yükleme tamamlanınca mesaj gönderin. Enter gönderir; Shift+Enter yeni satır açar. Geçmiş soldadır; sohbet başlığına tıklayınca ad değiştirme ve silme seçenekleri açılır.

**Yanıtı durdur**, aktif model bağlantısını kapatarak mevcut üretimi iptal eder ve modeli yüklü bırakır. İptal edilen veya bağlantısı kesilen üretim geçmişe kaydedilmez. Üretim sürerken aynı sohbet başka sekmeden de silinemez; önce üretimi durdurun.

Uzun sohbetlerin tamamı geçmişte kalır. Modele gönderilen bağlam, modelin kendi tokenizer’ıyla ölçülür; sistem talimatı ve son soru korunur, sığmayan eski konuşma çiftleri çıkarılır. Bu durumda arayüz son mesajların kullanıldığını belirtir. Tek başına sığmayan yeni bir soru için kısaltma istenir; soru sessizce kesilmez.

Yanıt üretim uzunluğu sınırına ulaşırsa **Devam ettir** görünür. Bu seçenek mevcut yanıtı sürdürür; geçmişe ikinci bir kullanıcı mesajı eklemez. Devam işlemi iptal edilirse önceki yanıt korunur. Sohbetlerin varsayılan başlıkları, arayüz dilinden bağımsız olarak ilk sorudan oluşturulur; elle verdiğiniz başlık korunur. Sayfalar arasında geçmek akışı korur; tam tarayıcı yenilemesi sohbet akışını iptal eder, taslak ve tamamlanmış geçmiş korunur.

## Görsel stüdyosu

Sohbet modeli açıksa **Belleği boşalt** seçin. Görsel ekranında servisi başlatın. İngilizce istem yazın, gerekirse görsel seçin. Çözünürlük, adım, CFG ve seed **Gelişmiş üretim ayarları** içindedir.

- **Üret:** Z-Image Turbo INT8; görsel eklenirse img2img.
- **Düzenle:** FLUX.2 klein; girdi görseli ve değişiklik talimatı gerekir.

Üretim tek iş olarak yürür. Hatalar ana ekranda ve iş geçmişinde gösterilir. İş durumunda **İşi iptal et** kullanılabilir. İptal isteği sonuç kaydedilmeden geldiyse iş tamamlandı sayılmaz. Sayfa değiştirilebilir veya yenilenebilir; iş sunucuda sürer. İşlem bitince sonucu doğrulanan dosya geçmişte ve galeride görünür. **İndir** dosyayı kaydeder. Üretim işleri geçmişinde **Daha fazla yükle** eski kayıtlara ulaşır; arama bütün iş geçmişinde yapılır.

Düzenleme için PNG, JPEG veya WebP seçilebilir; dosya en fazla 12 MiB ve 16 megapiksel olmalıdır. Yükleme öncesinde sessiz küçültme veya JPEG dönüşümü yapılmaz. Modelin workflow’u işlem çözünürlüğünü ayrıca belirleyebilir. Geçici referans kopyası iş bitince temizlenir; durdurma doğrulanamazsa kayıt korunur ve yeni üretim engellenir. Önceki işlemlerden kalan uygulamaya ait referans kopyaları servis güvenle başlatılıp kuyruğun boş olduğu doğrulanınca temizlenir.

ComfyUI iş gönderiminin cevabı kaybolursa işi yeniden göndermek yerine uygulamanın yönettiği servis durdurulur; yeniden başlatmanız istenir. Servisin durduğu doğrulanamazsa iş **Kaynak kontrolü gerekli** durumuna geçer.

Uygulamanın kendisi beklenmedik biçimde kapanırsa yarım işler tekrar gönderilmez; geçmişte kurtarma gerektiği belirtilir. Uygulama dışından açılmış 8188 servisine iş gönderilmez ve o süreç durdurulmaz.

## Kod asistanı

Proje klasörünü ekleyin, dosya ağacından metin dosyası seçin. Sorularınıza seçili dosya bağlamı eklenir. Modelin önerisi dosyaya otomatik yazılmaz: editörde düzenleyin, **Diff önizle** ile inceleyin, mevcut dosya için üzerine yazma onayını verin ve uygulayın.

## Donanım ve sorun giderme

Üst durum çubuğu aktif model/servisi ve işi gösterir. İş bitmeden bellek boşaltma kapalıdır; önce yanıtı veya görsel işini iptal edin. Genel Bakış → **Servis günlükleri** model yükleme ve üretim hatalarını gösterir.

Görsel servisi RAM koşulu nedeniyle başlatılamıyorsa diğer ağır uygulamaları kapatın. Servis bellek sınırında kapanırsa mevcut iş hata olarak kaydolur; bellek boşaltma düğmesiyle kaynakları bırakıp yeniden başlayın. Rastgele servisleri terminalden zorla kapatmayın.

Sol menünün altındaki Sistem ve Tercihler panelinde tema ve kaynak yenileme aralığı değiştirilebilir. Tercihler otomatik olarak SQLite'a kaydedilir. Üst çubuktan seçilen dil tüm arayüze uygulanır ve bu tarayıcıda hatırlanır. Kullanıcı mesajları, dosya içerikleri, model adları ve ham servis günlükleri özgün dilinde kalır.


## Ses stüdyosu

Ses menüsünde Metni Seslendir, Ses Dönüştür ve Seslerim bölümleri bulunur. Yeni ses profili için kayıt yükleyin, adını ve isteğe bağlı kayıt metnini girin. Profiller bu tarayıcının IndexedDB deposunda tutulur. Klonlama sırasında seçilen kaydın bir kopyası bu bilgisayardaki ses motoruna aktarılır ve iş bitince silinir; dış servise gönderilmez. Referansın ilk 30 saniyesi kullanılır; kayıt metnini giriyorsanız bu bölümle eşleştirin. Kayıt metni girildiğinde model devam ettirme modunu kullanır; söyleyiş yönlendirmesi yerine referans kaydı esas alır. Tarayıcı verilerini silmek profilleri de siler. Seslerim bölümünde seçilen profili dinleyebilir veya silebilirsiniz.

Metni Seslendir bölümünde kendi sesinizi veya karakter tasarımını seçip metin, dil ve söyleyiş hazırlayabilirsiniz. Metin taslağı tarayıcıda hatırlanır. Ses Dönüştür bölümünde replik veya şarkı seçilir; kaynak kayıt seçilip dinlenebilir. Dönüşüm kaydın dilini değiştirmez.

Sol menü dosya adedini ve indirilen baytları okur; ağırlıkları belleğe yüklemez. Başarılı VoxCPM2 GPU smoke testinden sonra Metni Seslendir üretimi açılır. Ses üret düğmesi modeli yükler; sonucu dinleyebilir, WAV olarak indirebilir veya Ses geçmişi bölümünden tekrar açabilirsiniz. İş iptal edilebilir; sonuçlar ve iş geçmişi uygulamanın yerel veri klasöründe saklanır. Ses Dönüştür ve şarkı dönüşümü Seed-VC V1/SVC adaptörüne bağlıdır. Her mod, ayrı çalışma ortamında kaynak ve referans kaydıyla gerçek dönüşüm testi geçince açılır; yalnızca ağırlıkların indirilmiş olması yeterli değildir. Şarkı modu otomatik perde eşleştirmesi yapmaz; kaydın melodisini korumaya çalışır. Kaynak ses/video en fazla 10 dakika, referansın kullanılan bölümü en fazla 30 saniyedir. Tam miks kaydındaki enstrümanlar otomatik ayrılmaz; şarkı dönüşümü için ayrılmış vokal kullanın. Yeni API için uygulamayı yeniden başlatın.

## Güvenli dosya kaydı ve veri yedeği

Kod düzenlemelerinde mevcut dosyanın izinleri korunur. Yazma sırasında dosya değişirse eski veri sessizce atılmaz; değişen sürüm geri getirilir ve yeniden diff oluşturmanız istenir. Çakışma kopyaları proje klasöründe `.ai-workstation-conflict-*` adıyla korunabilir. Kimlik bilgisi dosyaları ve `.codex`, `.ssh`, `.aws`, `.kube` gibi hassas dizinler proje okuma/yazma kapsamından çıkarılır.

Uygulamayı kapattıktan sonra proje kökünde:

```bash
backend/.venv/bin/python scripts/backup_workstation.py backup ~/workstation-backup.zip
backend/.venv/bin/python scripts/backup_workstation.py restore ~/workstation-backup.zip --confirm-restore
```

Yedek; sohbetler, ayarlar, proje kayıtları, iş geçmişi ve tamamlanan ses çıktılarını içerir. Kaynak proje dosyaları, model ağırlıkları, ComfyUI görselleri ve tarayıcıdaki ses profilleri ayrı tutulur; bu yedeğe eklenmez. Geri yükleme dosya hash’lerini ve veritabanını doğrular, önceki veri klasörünü `.before-restore-*` adıyla korur. Çalışan uygulama varken işlem engellenir; yarım işler yeniden başlatılmaz.
