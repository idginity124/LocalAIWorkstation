import React from "react";
import { KritaEditor } from "../components/KritaEditor";
import { createPortal } from "react-dom";
import { Icon } from "../components/Icon";
import { t, getLocale, formatDate, formatNumber, localizeMessage, tr } from "../i18n";
import { responseJson, sendJson } from "../lib/shared";
import { ACTIVE_IMAGE_JOBS as ACTIVE, imageJobFeedback, validateImageSettings, readOriginalImage, imageOutputPath, type ImageJob, type GalleryItem } from '../lib/image-studio';
type ZImageStatus = {
  model: string;
  assets: Array<{ path: string; filename: string; role: string; present: boolean; bytes: number | null }>;
  models_ready: boolean;
  comfy_root: string;
  output_dir: string;
  comfy_installed: boolean;
  workflow_path: string;
  workflow_ready: boolean;
  comfy_running: boolean;
  managed: boolean;
  start_allowed?: boolean;
  start_reason?: string;
  generation_available: boolean;
  reason: string;
  edit?: { model: string; ready: boolean; available: boolean; missing: string[]; hint: string };
};

export function ImageWorkspace() {
const JOB_LABELS: Record<string, string> = {QUEUED: t("Sırada"), PREPARING: t("Hazırlanıyor"), RUNNING: t("Üretiliyor"), CANCELLING: t("İptal ediliyor"), COMPLETED: t("Tamamlandı"), FAILED: t("Başarısız"), INTERRUPTED: t("İptal edildi"), RECOVERY_REQUIRED: t("Kaynak kontrolü gerekli")};
const PRESETS = [
  { label: tr.presetApple, prompt: "A single red apple on a clean white studio background, soft natural shadow, photorealistic." },
  { label: tr.presetCyberpunk, prompt: "A cinematic portrait of a futuristic cyberpunk explorer in neon rain, glowing visor, ultra-detailed, photorealistic, 8k." },
  { label: tr.presetLandscape, prompt: "Ethereal morning mist over an ancient mossy pine forest, golden sunbeams piercing through tall trees, cinematic lighting." },
  { label: tr.presetCat, prompt: "A sleek black cat with glowing emerald eyes resting on a dark velvet cushion, minimalist cinematic portrait, 35mm photography." },
];

  const [sidebarHost, setSidebarHost] = React.useState<HTMLElement | null>(null);
  React.useEffect(() => { setSidebarHost(document.getElementById("sidebar-image-controls")); }, []);
  const [status, setStatus] = React.useState<ZImageStatus | null>(null);
  const [error, setError] = React.useState("");
  const [serviceAction, setServiceAction] = React.useState(false);

  const [prompt, setPrompt] = React.useState("A single red apple on a clean white studio background, soft natural shadow, photorealistic.");
  const [resolution, setResolution] = React.useState("1024x1024");
  const [steps, setSteps] = React.useState(8);
  const [cfg, setCfg] = React.useState(1.0);
  const [seed, setSeed] = React.useState<number | string>(-1);
  const [initImage, setInitImage] = React.useState("");
  const [preparingImage, setPreparingImage] = React.useState(false);
  const [historyOpen, setHistoryOpen] = React.useState(false);
  const [historyTab, setHistoryTab] = React.useState<"images" | "jobs">("images");
  const [historySearch, setHistorySearch] = React.useState("");
  const historyDialog = React.useRef<HTMLDialogElement>(null);
  React.useEffect(() => {
    const dialog = historyDialog.current;
    if (historyOpen && !dialog?.open) dialog?.showModal();
    else if (!historyOpen && dialog?.open) dialog.close();
  }, [historyOpen]);
  const [mode, setMode] = React.useState<"generate" | "edit" | "krita">("generate");

  const [jobs, setJobs] = React.useState<ImageJob[]>([]);
  const [submitting, setSubmitting] = React.useState(false);
  const [jobsReady, setJobsReady] = React.useState(false);
  const activeJob = jobs.find(job => ACTIVE.includes(job.status));
  const generating = submitting || !!activeJob;
  const seenCompletion = React.useRef("");
  const submissionKey = React.useRef({fingerprint: "", key: ""});
  const [generateMessage, setGenerateMessage] = React.useState("");
  const [generateError, setGenerateError] = React.useState(false);

  const [archiveJobs, setArchiveJobs] = React.useState<ImageJob[]>([]);
  const [archiveCursor, setArchiveCursor] = React.useState<number | null>(null);
  const [archiveLoading, setArchiveLoading] = React.useState(false);
  const [archiveError, setArchiveError] = React.useState('');
  const archiveAbort = React.useRef<AbortController | null>(null);
  const [galleryError, setGalleryError] = React.useState('');
  const [gallery, setGallery] = React.useState<GalleryItem[]>([]);
  const [currentImage, setCurrentImage] = React.useState<GalleryItem | null>(null);

  const refreshStatus = React.useCallback(async () => {
    try {
      const res = await fetch("/api/v1/image/z-image-turbo/status", { headers: { Accept: "application/json" } });
      const data = await responseJson(res) as unknown as ZImageStatus;
      setStatus(data);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : tr.requestFailed);
    }
  }, []);

  const refreshGallery = React.useCallback(async () => {
    try {
      const res = await fetch("/api/v1/image/gallery", { headers: { Accept: "application/json" } });
      const data = await responseJson(res);
      if (!Array.isArray(data.images)) throw new Error(tr.invalidResponse);
      {
        const items = data.images as GalleryItem[];
        setGallery(items);
        setGalleryError('');
        setCurrentImage(cur => cur || (items.length > 0 ? items[0] : null));
      }
    } catch {
      setGalleryError(t('Galeri yüklenemedi. Yeniden deneyin.'));
    }
  }, []);

  React.useEffect(() => {
    void refreshStatus();
    void refreshGallery();
  }, [refreshStatus, refreshGallery]);

  React.useEffect(() => {
    const timer = setInterval(() => {
      void refreshStatus();
    }, 5000);
    return () => clearInterval(timer);
  }, [refreshStatus]);

  React.useEffect(() => {
    let live = true; let timer: number;
    const poll = async () => {
      try {
        const result = await responseJson(await fetch("/api/v1/image/jobs"));
        if (!live) return;
        const next = result.jobs as ImageJob[];
        setJobs(next); setJobsReady(true);
        setArchiveJobs(current => current.map(job => next.find(item => item.id === job.id) || job));
        const newest = next[0];
        if (newest && !ACTIVE.includes(newest.status) && seenCompletion.current !== newest.id) {
          seenCompletion.current = newest.id;
          const feedback = imageJobFeedback(newest);
          if (feedback) { setGenerateMessage(feedback.message); setGenerateError(feedback.error); }
          if (newest.result) { setCurrentImage(newest.result); void refreshGallery(); }
        }
      } catch { if (live) setJobsReady(false); }
      finally { if (live) timer = window.setTimeout(poll, 1500); }
    };
    void poll();
    return () => { live = false; clearTimeout(timer); };
  }, [refreshGallery]);

  const loadArchive = React.useCallback(async (before?: number) => {
    archiveAbort.current?.abort();
    const controller = new AbortController();
    archiveAbort.current = controller;
    setArchiveLoading(true); setArchiveError('');
    try {
      const query = new URLSearchParams({limit:'50', search:historySearch});
      if (before) query.set('before', String(before));
      const data = await responseJson(await fetch('/api/v1/image/jobs?' + query, {signal:controller.signal}));
      if (controller.signal.aborted) return;
      const items = data.jobs as ImageJob[];
      setArchiveJobs(current => before ? [...current, ...items.filter(item => !current.some(old => old.id === item.id))] : items);
      setArchiveCursor(typeof data.next_cursor === 'number' ? data.next_cursor : null);
    } catch {
      if (!controller.signal.aborted) setArchiveError(t('Geçmiş yüklenemedi. Yeniden deneyin.'));
    } finally { if (!controller.signal.aborted) setArchiveLoading(false); }
  }, [historySearch]);
  React.useEffect(() => {
    if (!historyOpen || historyTab !== 'jobs') return;
    setArchiveJobs([]); setArchiveCursor(null); setArchiveLoading(true);
    const timer = window.setTimeout(() => void loadArchive(), 250);
    return () => { window.clearTimeout(timer); archiveAbort.current?.abort(); };
  }, [historyOpen, historyTab, loadArchive]);

  const cancelJob = async () => {
    if (!activeJob) return;
    try {
      const result = await sendJson(`/api/v1/image/jobs/${activeJob.id}/cancel`, "POST", {}) as unknown as ImageJob;
      setJobs(current => current.map(job => job.id === result.id ? result : job));
    } catch (reason) { setGenerateMessage(reason instanceof Error ? reason.message : tr.requestFailed); setGenerateError(true); }
  };

  const handleStartComfy = async () => {
    setServiceAction(true);
    setGenerateMessage("");
    try {
      const res = await sendJson("/api/v1/image/z-image-turbo/start", "POST", {});
      setStatus(res as unknown as ZImageStatus);
    } catch (e) {
      setGenerateMessage(e instanceof Error ? e.message : tr.requestFailed);
      setGenerateError(true);
    } finally {
      setServiceAction(false);
      void refreshStatus();
    }
  };

  const handleStopComfy = async () => {
    setServiceAction(true);
    try {
      const res = await sendJson("/api/v1/image/z-image-turbo/stop", "POST", {});
      setStatus(res as unknown as ZImageStatus);
    } catch (e) {
      setGenerateMessage(e instanceof Error ? e.message : tr.requestFailed);
      setGenerateError(true);
    } finally {
      setServiceAction(false);
      void refreshStatus();
    }
  };

  const handleGenerate = async () => {
    if (mode === "krita" || generating || !prompt.trim()) return;
    const actualSeed = seed === "" ? -1 : Number(seed);
    try { validateImageSettings(actualSeed, mode === 'edit' ? 4 : steps, mode === 'edit' ? 1 : cfg); }
    catch (error) { setGenerateMessage((error as Error).message); setGenerateError(true); return; }
    setSubmitting(true); setGenerateMessage(""); setGenerateError(false);
    const [width, height] = resolution.split("x").map(Number);
    const body = {mode, prompt: prompt.trim(), seed: actualSeed, steps:mode === 'edit' ? 4 : steps, cfg:mode === 'edit' ? 1 : cfg, width, height, ...(mode === "edit" && initImage ? {init_image: initImage} : {})};
    // Reuse a key on a network retry; never accidentally enqueue the same work twice.
    const fingerprint = JSON.stringify(body);
    if (submissionKey.current.fingerprint !== fingerprint) submissionKey.current = {fingerprint, key: crypto.randomUUID()};
    const key = submissionKey.current.key;
    try {
      const job = await sendJson("/api/v1/image/jobs", "POST", {...body, idempotency_key: key}) as unknown as ImageJob;
      setJobs(current => [job, ...current.filter(item => item.id !== job.id)]);
      submissionKey.current = {fingerprint: "", key: ""};
    } catch (reason) { setGenerateMessage(reason instanceof Error ? reason.message : tr.requestFailed); setGenerateError(true); }
    finally { setSubmitting(false); }
  };

  const pickInitImage = async (file: File | undefined) => {
    if (!file) return;
    setPreparingImage(true); setGenerateMessage(''); setGenerateError(false);
    try {
      const original = await readOriginalImage(file);
      await sendJson('/api/v1/image/input/validate', 'POST', {init_image:original});
      setInitImage(original);
      return true;
    } catch (reason) { setGenerateMessage(reason instanceof Error ? reason.message : tr.requestFailed); setGenerateError(true); return false; }
    finally { setPreparingImage(false); }
  };

  const editCurrentImage = async () => {
    if (!currentImage || generating || preparingImage) return;
    setPreparingImage(true); setGenerateMessage(""); setGenerateError(false);
    try {
      const response = await fetch(currentImage.url);
      if (!response.ok) throw new Error(t("Görsel yüklenemedi."));
      const prepared = await pickInitImage(new File([await response.blob()], currentImage.filename));
      if (prepared) { setMode("edit"); setPrompt(""); document.getElementById("studio-prompt")?.focus(); }
    } catch (reason) { setGenerateMessage(reason instanceof Error ? reason.message : tr.requestFailed); setGenerateError(true); }
    finally { setPreparingImage(false); }
  };

  const copyPath = async () => {
    if (!currentImage) return;
    try {
      await navigator.clipboard.writeText(imageOutputPath(currentImage, status?.output_dir));
      setGenerateMessage(tr.pathCopied); setGenerateError(false);
    } catch (error) {
      setGenerateMessage(error instanceof Error ? error.message : tr.copyFailed); setGenerateError(true);
    }
  };

  if (!status) return <section className="panel"><p className="muted">{error ? localizeMessage(error) : tr.loading}</p></section>;

  return (
    <div className="image-workspace image-studio-v3">
      {sidebarHost && createPortal(<header className="sidebar-model sidebar-image-service">
        <div className="panel-head" style={{ marginBottom: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <span className="brand-mark" style={{ background: "#213831" }}>✦</span>
            <div>
              <span className="eyebrow">{tr.localOnly} • S3-DiT 6B (INT8 ConvRot)</span>
              <h2 style={{ margin: "2px 0 0" }}>{tr.imageStudioTitle}</h2>
            </div>
          </div>
          <div className="service-controls">
            <div className="service-status">
              <span className={`state-dot${status.comfy_running ? "" : " error"}`} />
              <span>{status.comfy_running ? tr.comfyOnline : tr.comfyOffline}</span>
            </div>
            <button
              type="button"
              className={status.comfy_running ? "secondary-button danger-button" : "primary-button"}
              disabled={serviceAction || generating || (!status.comfy_running && status.start_allowed === false)}
              onClick={() => void (status.comfy_running ? handleStopComfy() : handleStartComfy())}
            >
              {serviceAction
                ? (status.comfy_running ? tr.comfyStopping : tr.comfyStarting)
                : (status.comfy_running ? tr.stopComfy : tr.startComfy)}
            </button>
          </div>
        </div>
      </header>, sidebarHost)}

      <div className="studio-workspace-switch" role="group" aria-label={t("Görsel çalışma modu")}>
        <button type="button" aria-pressed={mode === "generate"} disabled={generating || preparingImage} onClick={() => setMode("generate")}><Icon name="sparkles" size={16}/>{t("Üret")}</button>
        <button type="button" aria-pressed={mode === "edit"} disabled={generating || preparingImage} onClick={() => setMode("edit")}><Icon name="image" size={16}/>{t("Düzenle")}</button>
        <button type="button" aria-pressed={mode === "krita"} disabled={generating || preparingImage} onClick={() => setMode("krita")}><Icon name="layers" size={16}/>{t("Krita’yla düzenle")}</button>
      </div>
      <div hidden={mode !== "krita"} className="studio-krita-workspace"><KritaEditor embedded selectedImage={currentImage?.url} onClose={() => setMode("generate")} onSendToAI={async file => {
        const prepared=await pickInitImage(file);if(!prepared)throw new Error(t("Görsel yüklenemedi."));setMode("edit");setPrompt("");
      }}/></div>
      <div hidden={mode === "krita"}>
      <div className="image-studio-grid">
        <section className="panel studio-controls" aria-label={t("Görsel oluşturma kontrolleri")}>
          <div className="studio-control-heading"><span className="studio-kicker">{t("GÖRSEL STÜDYOSU")}</span><h2>{mode === "edit" ? t("Yeniden yorumlayın.") : t("Bir fikirle başlayın.")}</h2><p>{mode === "edit" ? t("Görselinizi seçin, değiştirmek istediğiniz ayrıntıyı anlatın.") : t("Hayal ettiğiniz sahneyi kelimelere dökün.")}</p></div>

          {mode === "edit" && <div className="studio-input-image">
            {initImage && <div className="studio-input-preview"><img src={initImage} alt={t("Düzenlenecek görsel")}/><button type="button" aria-label={t("Girdi görselini kaldır")} disabled={generating || preparingImage} onClick={() => setInitImage("")}><Icon name="x" size={15}/></button></div>}
            <label className="studio-upload"><Icon name="plus" size={18}/><span>{preparingImage ? t("Görsel hazırlanıyor…") : initImage ? t("Başka görsel seç") : t("Düzenlenecek görseli seç")}<small>{t("PNG, JPG veya WebP · En fazla 12 MB")}</small></span><input aria-label={t("Girdi görseli seç")} type="file" accept="image/png,image/jpeg,image/webp" disabled={generating || preparingImage} onChange={event => { void pickInitImage(event.target.files?.[0]); event.target.value = ""; }}/></label>
          </div>}
          <div className="studio-prompt"><div className="studio-field-heading"><label htmlFor="studio-prompt">{mode === "edit" ? t("Ne değişsin?") : t("Görsel açıklaması")}</label><span>{t("İngilizce")}</span></div><textarea id="studio-prompt" aria-label={tr.imagePromptLabel} rows={6} value={prompt} onChange={event => setPrompt(event.target.value)} placeholder={mode === "edit" ? "Change the bag color to blue." : tr.imagePromptPlaceholder} disabled={generating}/></div>
          {mode === "generate" && <details className="studio-inspiration"><summary><Icon name="sparkles" size={14}/>{t("İlham al")}<Icon name="chevron-down" size={14}/></summary><div>{PRESETS.map(preset => <button type="button" key={preset.label} disabled={generating} onClick={() => setPrompt(preset.prompt)}>{preset.label}</button>)}</div></details>}
          {mode === "generate" && <label className="studio-size"><span>{t("Görsel boyutu")}</span><select value={resolution} onChange={event => setResolution(event.target.value)} disabled={generating}><option value="1024x1024">{t("Kare · 1024 × 1024")}</option><option value="1024x768">{t("Yatay · 1024 × 768")}</option><option value="768x1024">{t("Dikey · 768 × 1024")}</option><option value="512x512">{t("Taslak · 512 × 512")}</option></select></label>}
          <details className="studio-advanced"><summary>{t("Gelişmiş ayarlar")}<Icon name="chevron-down" size={14}/></summary>{mode === "generate" && <div className="studio-advanced-fields"><label>{t("Adım sayısı")}<input type="number" min={1} max={30} value={steps} disabled={generating} onChange={event => setSteps(Number(event.target.value))}/></label><label>CFG<input type="number" min={0.5} max={10} step={0.1} value={cfg} disabled={generating} onChange={event => setCfg(Number(event.target.value))}/></label></div>}<div className="studio-seed"><label>{t("Boş bırakırsanız rastgele seçilir")}<input aria-label="Seed" type="text" value={seed === -1 ? "" : seed} placeholder={t("Rastgele")} disabled={generating} onChange={event => setSeed(event.target.value === "" ? -1 : event.target.value)}/></label></div></details>

          <div className="studio-action-area"><button type="button" className="primary-button generate-button" disabled={!jobsReady || serviceAction || generating || preparingImage || !prompt.trim() || (mode === "edit" ? (!initImage || !status.edit?.available) : !status.generation_available)} onClick={() => void handleGenerate()}><Icon name="sparkles" size={17}/>{generating ? t("Oluşturuluyor…") : mode === "edit" ? t("Görseli düzenle") : t("Görsel üret")}</button><small>{mode === "edit" ? "FLUX.2 klein" : "Z-Image Turbo"} {" "}{t("· Cihazınızda çalışır")}</small></div>
          {generateMessage ? <p className={`studio-feedback${generateError ? " error-text" : ""}`} role={generateError ? "alert" : "status"}>{localizeMessage(generateMessage)}</p> : error ? <p className="studio-feedback error-text" role="alert">{localizeMessage(error)}</p> : !status.comfy_running ? <p className="studio-feedback">{t("Başlamak için sol menüden ComfyUI’yi açın.")}{status.start_allowed === false && status.start_reason ? ` ${localizeMessage(status.start_reason)}` : ""}</p> : mode === "edit" && !status.edit?.available ? <p className="studio-feedback">{status.edit?.hint ? localizeMessage(status.edit.hint) : t("Düzenleme modeli şu anda kullanılamıyor.")}</p> : !status.generation_available && mode === "generate" ? <p className="studio-feedback">{localizeMessage(status.reason)}</p> : null}
        </section>
        <section className="studio-canvas" aria-label={t("Görsel önizleme")}>
          <div className="studio-canvas-toolbar"><h2>{t("Önizleme")}</h2>{currentImage && <div><button type="button" disabled={generating || preparingImage} onClick={() => void editCurrentImage()}><Icon name="image" size={15}/><span>{t("Bu görseli düzenle")}</span></button><a href={currentImage.url} download={currentImage.filename} aria-label={t("Görseli indir")}><Icon name="arrow-down" size={16}/><span>{t("İndir")}</span></a><a href={currentImage.url} target="_blank" rel="noopener noreferrer" aria-label={t("Görseli tam boyut aç")}><Icon name="expand" size={16}/></a><details className="studio-image-info" key={currentImage.filename}><summary aria-label={t("Görsel bilgileri")}><Icon name="info" size={17}/></summary><div><strong>{t("Görsel bilgileri")}</strong><p>{currentImage.prompt || t("Prompt bilgisi yok.")}</p><dl><div><dt>{t("Dosya")}</dt><dd>{currentImage.filename}</dd></div>{currentImage.width && currentImage.height && <div><dt>{t("Boyut")}</dt><dd>{currentImage.width} × {currentImage.height}</dd></div>}{currentImage.seed != null && <div><dt>{tr.seedLabel}</dt><dd>{currentImage.seed}</dd></div>}{currentImage.duration_seconds != null && <div><dt>{t("Süre")}</dt><dd>{formatNumber(currentImage.duration_seconds)} {" "}{t("sn")}</dd></div>}</dl><button type="button" onClick={() => void copyPath()}>{t("Dosya yolunu kopyala")}</button></div></details></div>}</div>
          <div className="studio-artboard">{currentImage ? <img src={currentImage.url} alt={currentImage.prompt || t("Üretilen görsel")}/> : <div className="studio-canvas-empty"><span><Icon name="image" size={32}/></span><h3>{t("Fikrinize yer açın.")}</h3><p>{t("İlk görseliniz burada görünecek.")}</p></div>}{generating && <div className="studio-generation-overlay"><Icon name="sparkles" size={22}/><span>{t("Görseliniz hazırlanıyor")}</span></div>}</div>
          <div className="studio-job-status" role="status">{activeJob ? <><progress aria-label={t("Görsel üretimi devam ediyor")}/><span>{JOB_LABELS[activeJob.status] || activeJob.status}</span><button type="button" disabled={activeJob.status === "CANCELLING"} onClick={() => void cancelJob()}>{t("İptal et")}</button></> : <><span className="studio-status-dot"/><span>{!jobsReady ? t("İş durumuna bağlanılıyor…") : submitting ? t("İş sıraya alınıyor…") : !status.comfy_running ? t("Üretim sürmüyor") : t("Yeni bir fikir için hazır")}</span></>}<button type="button" className="studio-history-link" onClick={() => { setHistoryTab("jobs"); setHistoryOpen(true); }}>{t("Üretim işleri")}<Icon name="chevron-right" size={13}/></button></div>
        </section>
      </div>
      </div>
      <section className="studio-recent" aria-label={t("Son çalışmalar")}><div className="studio-recent-heading"><h2>{t("Son çalışmalar")}{" "}<span>{gallery.length}</span></h2><button type="button" onClick={() => { setHistoryTab("images"); setHistoryOpen(true); }}>{t("Tüm geçmiş")}<Icon name="arrow-right" size={14}/></button></div>{galleryError && <p className="studio-feedback error-text" role="alert">{galleryError} <button type="button" className="text-button" onClick={() => void refreshGallery()}>{t("Yeniden dene")}</button></p>}{gallery.length ? <div className="studio-filmstrip">{gallery.slice(0, 12).map(item => <button type="button" key={item.filename} aria-label={item.prompt || item.filename} aria-pressed={currentImage?.filename === item.filename} onClick={() => setCurrentImage(item)}><img src={item.url} alt={item.prompt || item.filename} loading="lazy"/></button>)}</div> : <p className="studio-feedback">{t("Ürettiğiniz görseller burada birikir.")}</p>}</section>
      <dialog ref={historyDialog} className="studio-history-dialog" aria-labelledby="studio-history-title" onCancel={event => { event.preventDefault(); setHistoryOpen(false); }} onClose={() => setHistoryOpen(false)} onClick={event => { if (event.target === event.currentTarget) setHistoryOpen(false); }}><div className="studio-history-content"><header><div><h2 id="studio-history-title">{t("Çalışmalarınız")}</h2><p>{t("Görselleri keşfedin, üretim durumlarını inceleyin.")}</p></div><button type="button" aria-label={t("Geçmişi kapat")} onClick={() => setHistoryOpen(false)} autoFocus><Icon name="x" size={20}/></button></header><div className="studio-history-tools"><div className="studio-mode" role="group" aria-label={t("Geçmiş türü")}><button type="button" aria-pressed={historyTab === "images"} onClick={() => setHistoryTab("images")}>{t("Görseller")}</button><button type="button" aria-pressed={historyTab === "jobs"} onClick={() => setHistoryTab("jobs")}>{t("Üretim işleri")}</button></div><label className="studio-history-search"><Icon name="search" size={16}/><input aria-label={t("Geçmişte ara")} placeholder={t("Açıklama veya dosya adı ara…")} value={historySearch} maxLength={200} onChange={event => setHistorySearch(event.target.value)}/></label></div>
        {historyTab === "images" ? <div className="studio-archive-grid">{galleryError && <p className="error-text" role="alert">{galleryError}<button type="button" className="text-button" onClick={() => void refreshGallery()}>{t("Yeniden dene")}</button></p>}{gallery.filter(item => `${item.prompt} ${item.filename}`.toLocaleLowerCase(getLocale()).includes(historySearch.toLocaleLowerCase(getLocale()))).map(item => <button type="button" key={item.filename} aria-label={`${t("Önizle:")} ${item.prompt || item.filename}`} onClick={() => { setCurrentImage(item); setHistoryOpen(false); }}><img src={item.url} alt={item.prompt || item.filename} loading="lazy"/><strong>{item.prompt || item.filename}</strong><small>{formatDate(item.created_at)}</small></button>)}{!gallery.some(item => `${item.prompt} ${item.filename}`.toLocaleLowerCase(getLocale()).includes(historySearch.toLocaleLowerCase(getLocale()))) && <p className="studio-feedback">{t("Gösterilecek görsel yok.")}</p>}</div> : <div className="studio-archive-jobs">{!jobsReady && <p role="status">{t("İş durumuna ulaşılamıyor; bağlantı yeniden deneniyor.")}</p>}{archiveJobs.map(job => <article key={job.id}><div><strong>{job.prompt}</strong><small>{formatDate(job.created_at, true)}</small>{job.error && <p className="error-text">{localizeMessage(job.error)}</p>}</div><span>{JOB_LABELS[job.status] || job.status}</span>{job.result && <button type="button" onClick={() => { setCurrentImage(job.result!); setHistoryOpen(false); }}>{t("Göster")}</button>}</article>)}{archiveError && <p className="error-text" role="alert">{archiveError}<button type="button" className="text-button" onClick={() => void loadArchive(archiveCursor || undefined)}>{t("Yeniden dene")}</button></p>}{archiveLoading && <p role="status">{tr.loading}</p>}{archiveCursor && <button type="button" className="secondary-button" disabled={archiveLoading} onClick={() => void loadArchive(archiveCursor)}>{t("Daha fazla yükle")}</button>}{!archiveLoading && !archiveError && archiveJobs.length === 0 && <p className="studio-feedback">{t("Gösterilecek üretim işi yok.")}</p>}</div>}
      </div></dialog>
    </div>
  );
}
