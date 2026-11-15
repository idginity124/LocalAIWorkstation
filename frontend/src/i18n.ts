/** Tek Türkçe metin kataloğu: arayüzdeki tüm kullanıcı metinleri buradan gelir. */
import { dicts } from "./i18n-langs";
import en from "./locales/en.json";
import zh from "./locales/zh.json";
import hi from "./locales/hi.json";
import es from "./locales/es.json";
import ar from "./locales/ar.json";
import bn from "./locales/bn.json";
import pt from "./locales/pt.json";
import ru from "./locales/ru.json";
import ur from "./locales/ur.json";
import fr from "./locales/fr.json";

const trBase = {
  appName: "Yerel AI Çalışma İstasyonu", languageLabel: "Dil", loading: "Yükleniyor", backendOffline: "Yerel backend'e ulaşılamıyor",
  backendHelp: "Backend'i başlatıp yeniden deneyin.", backendConnected: "Yerel backend'e bağlı", overview: "Genel Bakış",
  system: "Sistem", gpu: "GPU", memory: "Bellek", unavailable: "Ölçülemiyor", unverified: "Henüz doğrulanmadı",
  notReady: "Henüz hazır değil", mainMenu: "Ana menü", localOnly: "Yalnızca bu bilgisayar", workspace: "YEREL ÇALIŞMA ALANI",
  settings: "Ayarlar", settingsUnavailable: "Ayarlar backend'den okunamadı. Backend bağlantısını kontrol edin.",
  invalidResponse: "Backend beklenmeyen bir yanıt verdi.", requestFailed: "İstek tamamlanamadı", preferences: "TERCİHLER",
  displaySettings: "Görünüm ve telemetri", savedOnDevice: "Bu bilgisayarda saklanır", themeLabel: "Tema",
  themeDescription: "Uygulamanın görünümünü seçin.", dark: "Koyu", light: "Açık", systemTheme: "Sistem ayarı",
  refreshLabel: "Telemetri yenileme", refreshDescription: "Sistem kaynaklarının ekranda ne sıklıkta yenileneceği.",
  seconds: "saniye", settingsSaved: "Ayarlar bu bilgisayara kaydedildi.", saving: "Kaydediliyor…", saveSettings: "Ayarları kaydet",
  systemStatus: "SİSTEM DURUMU", overviewHeadline: "Kaynak durumunu ve yerel servisleri buradan izleyin.",
  telemetryDescription: "Değerler yerel sistem arayüzlerinden periyodik olarak okunur. Erişilemeyen alanlar ölçülemiyor olarak gösterilir.",
  ramAvailable: "Kullanılabilir RAM", availableRam: "Kullanılabilir RAM", swapAvailable: "Kullanılabilir swap", gpuMemory: "Kullanılan GPU belleği",
  gpuStatus: "GPU kaynak durumu", unknown: "Belirsiz", total: "Toplam", computer: "BİLGİSAYAR",
  systemDiagnostics: "Sistem tanılama", readOnly: "Salt okunur", operatingSystem: "İşletim sistemi", kernel: "Kernel",
  desktopSession: "Masaüstü oturumu", temperature: "Sıcaklık", usage: "Kullanım", gettingStarted: "BAŞLANGIÇ",
  workspaceStatus: "Çalışma alanı", developmentVersion: "Geliştirme sürümü",
  modelWaitNotice: "Model ve AI servisleri, dosyaları ve donanım uygunluğu doğrulanana kadar başlatılmaz.",
  modelFolder: "Model klasörü", gpuUnknownNotice: "Telemetri periyodik olarak yenilenir. GPU'nun boş olduğu doğrulanmadı.",
  gpuNameUnavailable: "AMD aygıtı algılandı; model adı okunamadı.", amdGpuMissing: "AMD sysfs aygıtı bulunamadı.",
  projectWorkspace: "PROJE ÇALIŞMA ALANI", scopedFiles: "Seçtiğiniz klasörde çalışır", folderPathHelp: "Yalnızca burada belirttiğiniz klasör kaydedilir. Ev dizini veya başka konumlar taranmaz.",
  folderPath: "Proje klasörünün tam yolu", projectName: "Proje adı", optional: "İsteğe bağlı", addFolder: "Klasörü ekle", chooseFolder: "Klasör seç",
  selectedProject: "Açık proje", chooseProject: "Proje seçin",
  fileTree: "Dosyalar", parentFolder: "Üst klasör", emptyFolder: "Bu klasörde gösterilecek dosya yok.", fileReview: "Dosya inceleme", noFileSelected: "Dosya seçilmedi",
  fileContents: "Dosya içeriği", selectTextFile: "Soldaki listeden metin dosyası seçin. Gizli ve hassas dosyalar listelenmez.", previewDiff: "Diff önizle", reviewBeforeApply: "Uygulamadan önce inceleyin",
  noChanges: "Değişiklik yok.", confirmOverwrite: "Bu mevcut dosyanın üzerine yazmayı onaylıyorum.", applyApprovedDiff: "Onaylı diff'i uygula",
  addProjectFirst: "Başlamak için proje klasörünü seçin veya tam yolunu girip ekleyin.", projectAdded: "Proje klasörü bu bilgisayarda kaydedildi.", projectAlreadyAdded: "Bu klasör zaten kayıtlı; proje açıldı.", folderPickCancelled: "Klasör seçimi iptal edildi.", diffReady: "Diff hazır; dosya henüz değiştirilmedi.", editApplied: "Onaylı değişiklik atomik olarak uygulandı.",
  gemmaStatus: "Model durumu", gemmaIdle: "Kapalı", gemmaLoading: "Yükleniyor", gemmaRunning: "Çalışıyor", gemmaUnknown: "Belirsiz", gemmaUnavailable: "Erişilemiyor",
  contextTokens: "token bağlam", gemmaCpuNotice: "Vulkan0 üzerinde tek GPU işi olarak çalışır. Başlatmadan önce VRAM ölçülür; kapatıldıktan sonra VRAM başlangıç bandına dönmeden yeni ağır iş başlatılmaz. 2.048 token bağlamdaki GPU smoke testinde 47,7 token/s ölçüldü.",
  loadGemma: "Modeli yükle", stopGemma: "Modeli durdur", gemmaStarting: "Model yükleniyor…", gemmaReady: "Model hazır.", gemmaStopped: "Model kontrollü biçimde durduruldu.", localModel: "Yerel model", modelSelect: "Model", modelChangeCreatesConversation: "Başka model seçildi; bu modelle yeni bir sohbet oluşturun.", modelSwitchNotice: "Her model tek başına GPU'yu kullanır; model değişimi önce mevcut modeli güvenle kapatır.",
  codeAssistantQuestion: "Gemma'ya sor", codeAssistantPlaceholder: "Seçilen dosya hakkında ne öğrenmek veya değiştirmek istediğinizi yazın…",
  askGemma: "Yerel Gemma'ya sor", gemmaThinking: "Yerel model yanıtlıyor…", gemmaAnswer: "Model yanıtı", emptyChat: "Bir mesaj yazarak sohbete başlayın.", answerNotApplied: "Modelin verdiği kod önerileri dosyaya kendiliğinden uygulanmaz. Düzenlemeyi editöre aktarın, diff'i inceleyin ve ayrıca onaylayın.",
  conversationHistory: "Sohbet geçmişi", newConversation: "Yeni sohbet", noConversationSelected: "Sohbet seçin", conversationTitle: "Sohbet başlığı",
  renameConversation: "Adı değiştir", deleteConversation: "Sohbeti sil", confirmDeleteConversation: "Bu sohbeti ve mesajlarını kalıcı olarak silmek istiyor musunuz?", conversationDeleted: "Sohbet silindi.", conversationRenamed: "Sohbet adı güncellendi.", you: "Sen",
  assistantIntro: "Yerel modellerle cihazınızda sohbet edin. Mesajlar bu bilgisayardaki SQLite veritabanında saklanır.", assistantQuestion: "Mesajınız", assistantPlaceholder: "Bir şey sorun…", sendMessage: "Gönder", stopResponse: "Yanıtı durdur", responseStopped: "Yanıt durduruldu. Kısmi mesaj kaydedilmedi; yeni mesaj gönderebilirsiniz.", responseCancelled: "Yanıt iptal edildi; model yeni mesaj için hazır.", copyMessage: "Mesajı kopyala", messageCopied: "Mesaj panoya kopyalandı.", copyFailed: "Mesaj panoya kopyalanamadı.", lastResponseSpeed: "Son yanıt hızı", tokensPerSecond: "token/s", noResponsesYet: "Henüz ölçüm yok", streamInterrupted: "Yanıt akışı kesildi. Tamamlanmamış mesaj kaydedilmedi.", modelMustLoad: "Sohbet etmek için önce modeli yükleyin.", shiftEnterHint: "Göndermek için Enter, yeni satır için Shift+Enter.", codeAssistantChatTitle: "Kod Asistanı sohbeti", markdownCode: "Kod",
  modelManagement: "Model Yönetimi", modelInventory: "Yerel model envanteri", modelInventoryHelp: "Dosyalar yalnızca izinli model klasöründe okunur. .part uzantılı indirmeler geçerli model sayılmaz.", modelName: "Model", modelFormat: "Biçim", modelLicense: "Lisans", modelStatus: "Durum", modelMissing: "Eksik", modelFilesPresent: "Dosyalar var; hash kontrol edilmedi", modelHashVerified: "Hash doğrulandı", modelWarning: "Durum notu", modelSource: "Kaynak", modelPath: "Yerel yol", modelSize: "Beklenen boyut", loadingModels: "Model envanteri okunuyor…", modelsUnavailable: "Model envanteri okunamadı.",
  ready: "Hazır", visualPending: "Görsel üretim, ComfyUI ve Z-Image Turbo gerçek donanımda doğrulanana kadar etkinleştirilmeyecek.", zImageTurboDescription: "Z-Image Turbo, ComfyUI üzerinden yerel çalışır. Üretim yalnızca sabitlenmiş workflow ve gerçek API doğrulamasından sonra açılır.", zImageReadiness: "Üretim hazırlığı", zImageModels: "Model dosyaları", zImageComfy: "İzole ComfyUI", zImageWorkflow: "Doğrulanmış workflow", zImageService: "Yerel ComfyUI servisi", zImagePromptPolicyTitle: "Prompt politikası", zImagePromptPolicy: "Görsel üretim prompt'ları İngilizce girilir. Z-Image Turbo CFG'sizdir; bu yüzden CFG ve negatif prompt alanları gösterilmez. Prompt dönüşmeden saklanır ve workflow'a aktarılır.",
  startComfy: "ComfyUI'yi Başlat", stopComfy: "ComfyUI'yi Durdur", comfyStarting: "ComfyUI başlatılıyor…", comfyStopping: "ComfyUI durduruluyor…",
  comfyOnline: "ComfyUI Aktif (127.0.0.1:8188)", comfyOffline: "ComfyUI Kapalı", imageStudioTitle: "Z-Image Turbo Görsel Stüdyosu",
  imagePromptLabel: "Görsel Promptu (İngilizce)", imagePromptPlaceholder: "A single red apple on a clean white studio background, soft natural shadow, photorealistic...",
  generateImage: "✦ Görsel Üret", generatingImage: "Görsel üretiliyor (lütfen bekleyin)…",
  stepsLabel: "Adım Sayısı", cfgLabel: "CFG Ölçeği", seedLabel: "Seed (Tohum)", randomSeed: "🎲 Rastgele", resolutionLabel: "Çözünürlük",
  presetPrompts: "Hızlı İlham Promptları", presetApple: "🍎 Kırmızı Elma", presetCyberpunk: "⚡ Siber Gezgin", presetLandscape: "🌲 Mistik Doğa", presetCat: "🐱 Neon Kedi",
  activePreview: "Aktif Görsel Önizlemesi", galleryTitle: "Üretim Galerisi & Geçmiş", noImagesInGallery: "Henüz üretilmiş görsel bulunmuyor.",
  copyPath: "Yolu Kopyala", pathCopied: "Dosya yolu panoya kopyalandı!", generationDetails: "Üretim Detayları", durationSec: "Süre", fullSize: "Tam Boyut",
  navigation: ["Genel Bakış", "Asistan", "Kod Asistanı", "Görsel", "Ses", "Belgeler", "Tanılama", "Modeller", "GPU ve Kaynaklar", "Galeri / Geçmiş", "Kuyruk", "Ayarlar"],
} as const;

export type Lang = "tr" | "en" | "zh" | "hi" | "es" | "ar" | "bn" | "pt" | "ru" | "ur" | "fr";
export const LANGS: ReadonlyArray<{ code: Lang; name: string; rtl: boolean }> = [
  { code: "tr", name: "Türkçe", rtl: false }, { code: "en", name: "English", rtl: false }, { code: "zh", name: "中文", rtl: false },
  { code: "hi", name: "हिन्दी", rtl: false }, { code: "es", name: "Español", rtl: false }, { code: "ar", name: "العربية", rtl: true },
  { code: "bn", name: "বাংলা", rtl: false }, { code: "pt", name: "Português", rtl: false }, { code: "ru", name: "Русский", rtl: false },
  { code: "ur", name: "اردو", rtl: true }, { code: "fr", name: "Français", rtl: false },
];

const LANG_STORAGE_KEY = "ai-workstation-lang";
let current: Lang = "tr";

function applyDocumentLanguage(lang: Lang): void {
  const root = document.documentElement;
  root.lang = lang === "zh" ? "zh-Hans" : lang;
  root.dir = LANGS.find(item => item.code === lang)?.rtl ? "rtl" : "ltr";
}

export function getLang(): Lang { return current; }

export function setLang(lang: Lang): void {
  current = lang;
  applyDocumentLanguage(lang);
  try { window.localStorage.setItem(LANG_STORAGE_KEY, lang); } catch { /* Dil tercihi kaydedilemese de arayüz çalışır. */ }
}

try {
  const saved = window.localStorage.getItem(LANG_STORAGE_KEY);
  const known = LANGS.find(item => item.code === saved);
  if (known) current = known.code;
} catch { /* Kayıtlı dil okunamazsa Türkçe kalır. */ }
applyDocumentLanguage(current);

const catalogs: Record<string, Record<string, string>> = { en, zh, hi, es, ar, bn, pt, ru, ur, fr };
const sourceKeys = new Map<string, string>(Object.entries(trBase).filter(([, value]) => typeof value === "string").map(([key, value]) => [value as string, key]));
const translatedSources = new Map<string, string>();
for (const catalog of Object.values(catalogs)) {
  for (const [source, translated] of Object.entries(catalog)) translatedSources.set(translated, source);
}
const serviceAliases: Record<string, string> = {
  "Sohbet modeli GPU belleğini kullanıyor. Üst çubuktan belleği boşaltın.": "Önce çalışan servisi sol menüden durdurun.",
  "Görsel servisi GPU belleğini kullanıyor. Üst çubuktan belleği boşaltın.": "Önce çalışan servisi sol menüden durdurun.",
  "Bu portta uygulamanın başlatmadığı bir servis var.": "Uygulamanın yönetmediği bir servis bu portu kullanıyor.",
  "8188 portunda dışarıdan başlatılmış bir servis var. Bu uygulama onu yönetmiyor; kendi terminalinden kapatıp burada başlatın.": "Uygulamanın yönetmediği bir servis bu portu kullanıyor.",
};

/** Translate application copy only; never pass user content or file names here. */
export function t(source: string): string {
  const canonical = serviceAliases[source] ?? ((source in en) ? source : translatedSources.get(source) ?? source);
  if (current === "tr") return canonical;
  const local = catalogs[current]?.[canonical];
  if (local) return local;
  if (current !== "en") {
    const key = sourceKeys.get(canonical);
    const translated = key ? dicts[current]?.[key] : undefined;
    if (typeof translated === "string") return translated;
  }
  return (en as Record<string, string>)[canonical] ?? source;
}

export const tr: typeof trBase = new Proxy(trBase, {
  get(target, property, receiver) {
    if (property === "navigation" && current !== "tr") return dicts[current]?.navigation ?? dicts.en.navigation;
    const source = Reflect.get(target, property, receiver);
    return typeof source === "string" ? t(source) : source;
  },
});

/** Server diagnostics stay in the log viewer; unknown service errors use localized UI copy. */
export function localizeMessage(message: string): string {
  if (!message) return message;
  const canonical = serviceAliases[message] ?? ((message in en) ? message : translatedSources.get(message));
  if (canonical) return t(canonical);
  return current === "tr" ? message : t("Servis isteği tamamlanamadı. Ayrıntılar için servis günlüklerini inceleyin.");
}

export function getLocale(): string { return current === "zh" ? "zh-Hans" : current; }
export function formatNumber(value: number, digits = 1): string {
  return new Intl.NumberFormat(getLocale(), { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
}
export function formatDate(value: string, utc = false): string {
  const normalized = value.replace(" ", "T");
  const date = new Date(utc && !/(Z|[+-]\d{2}:?\d{2})$/.test(normalized) ? normalized + "Z" : normalized);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(getLocale());
}
