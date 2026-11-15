# Deneysel Krita entegrasyonu

Krita, özel Xvfb ekranında ayrı süreç olarak çalışır; React editörü yerel API üzerinden dosya tabanlı komutlar gönderir. Eklenti işlemleri Qt ana iş parçacığında uygular. Mevcut masaüstü Krita belgelerine bağlanmaz. Bu ayrım bir dosya sistemi sandbox'ı değildir.

## Gereksinimler

Krita, Krita'nın Qt sürümüyle uyumlu Python bağları, `xvfb-run` ve `xauth` gerekir. Paket adları dağıtıma göre değişir; Arch/CachyOS tarafında Xvfb ve xauth paketleri `xorg-server-xvfb` ve `xorg-xauth` olarak bulunur. Qt offscreen yolu yerine Xvfb/xcb kullanılır.

```bash
bash scripts/krita-deneme.sh
```

Bu isteğe bağlı test ayrı rapor klasöründe küçük bir belge açar; katmanlar, PNG/KRA çıktısı ve temel işlemleri denetler. Çıktılar `runtime-reports/` altında yerel tutulur. Önceki donanım raporları bu depoya dahil değildir; kendi kurulumunuzda yeniden deneyin.

## Kullanım

1. Görsel çalışma alanından **Krita’yla düzenle** modunu açın.
2. Görsel yükleyin veya seçili galeri görselini alın.
3. Fırça/silgi, seçim, katman, metin/şekil, kırpma ve geri alma araçlarını kullanın.
4. AI düzenlemesi için ilgili yerel ComfyUI servisi ve model dosyaları gerekir. Alanı fırçalayıp talimat verin; sonucu görsel olarak kontrol edin.
5. Çalışmanızı PNG veya KRA olarak dışa aktarın.

Varsayılan AI düzenleme FLUX.2 Klein ile seçimin çevresini işler; seçim dışı pikseller birleştirme sırasında korunur. Sonuç yeni bileşik katmana gelir; önceki katmanlar gizlenerek korunur. Düzenleme sürerken belge değiştiyse sonuç otomatik uygulanmaz. Modelin işi tamamlaması, talimatı doğru gerçekleştirdiğini göstermez. Özellikle raster yazının içeriğini ve tipografisini koruyarak değiştirme güvenilir biçimde doğrulanmış değildir.

## Ek modeller

`scripts/krita-modelleri-kur.sh` isteğe bağlı LaMa, standart RealVisXL/SDXL, Fooocus Inpaint dosyaları ve sabitlenmiş Acly inpaint düğümleri için ayrı kurulum aracıdır. Normal `setup.sh` bunları indirmez. Betiğin kaynaklarını, lisanslarını ve disk gereksinimini inceleyerek çalıştırın. Mevcut ComfyUI/PyTorch/ROCm ortamı yükseltilmez. Yeni modelleri kurduktan sonra uygulamanın yönettiği ComfyUI servisini yeniden başlatın.

## Sınırlar

- En fazla 2048 piksel kenar, 12 MiB girdi, 20 katman ve sekiz geçmiş adımı.
- Tek belge ve seri komutlar; ilk motor açılışı uzun sürebilir.
- KRA dışa aktarma vardır; KRA içe aktarma sunulmaz.
- Metin, parametreleri KRA annotation alanında saklanan bir piksel katmanıdır. Metne boya/filtre/dönüşüm uygulamak onu normal piksel katmanına çevirebilir.
- Tam masaüstü Krita arayüzü veya bütün fırça motorları sunulmaz.
- Uygulamayı kapatmadan önce dışa aktarın. Birim testler gerçek Krita/GPU uyumluluğunu veya düzenleme kalitesini kanıtlamaz.
