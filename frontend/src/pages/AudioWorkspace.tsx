import React from "react";
import { createPortal } from "react-dom";
import { t, tr, localizeMessage, LANGS, formatDate, formatNumber } from "../i18n";
import { Icon } from "../components/Icon";
import { formatBytes, responseJson, sendJson, HttpError } from "../lib/shared";
import { listVoices, saveVoice, deleteVoice, type VoiceProfile } from "../lib/voice-library";

type Tab = "tts" | "conversion" | "voices";
type Pack = { present: number; total: number; partial: number; bytes: number };
type AudioResult = { filename: string; url: string; sample_rate: number; seconds: number; bytes: number };
type AudioJob = { id: string; status: string; text: string; created_at: string; error?: string; result?: AudioResult };
const ACTIVE_AUDIO = ["QUEUED", "PREPARING", "RUNNING", "CANCELLING", "CLEANUP"];
type Preparation = { engines?: Record<string, boolean>; engine_available: boolean; active_job_id?: string | null; packs: Record<string, Pack> };

function AudioPreview({ audio, name }: { audio: Blob; name: string }) {
  const [url, setUrl] = React.useState("");
  const [peaks, setPeaks] = React.useState<number[]>([]);
  React.useEffect(() => {
    const objectUrl = URL.createObjectURL(audio);
    setUrl(objectUrl); setPeaks([]);
    let live = true;
    const decode = async () => {
      if (audio.size > 25 * 1024**2 || !window.AudioContext) return;
      const context = new AudioContext();
      try {
        const buffer = await context.decodeAudioData(await audio.arrayBuffer());
        const samples = buffer.getChannelData(0);
        const values = Array.from({ length: 96 }, (_, bar) => {
          const start = Math.floor(bar * samples.length / 96);
          const end = Math.floor((bar + 1) * samples.length / 96);
          let peak = 0;
          for (let index = start; index < end; index += Math.max(1, Math.floor((end - start) / 300))) peak = Math.max(peak, Math.abs(samples[index]));
          return peak;
        });
        const maximum = Math.max(...values, .001);
        if (live) setPeaks(values.map(value => value / maximum));
      } catch { /* The browser player can support formats AudioContext cannot decode. */ }
      finally { await context.close(); }
    };
    void decode();
    return () => { live = false; URL.revokeObjectURL(objectUrl); };
  }, [audio]);
  return <div className="audio-player"><div className="audio-player-name"><Icon name="audio" size={17}/><strong title={name}>{name}</strong><span>{formatBytes(audio.size)}</span></div>{peaks.length > 0 && <svg className="audio-waveform" viewBox="0 0 576 90" preserveAspectRatio="none" aria-hidden="true">{peaks.map((peak, index) => <rect key={index} x={index * 6} y={45 - Math.max(1, peak * 39)} width={3} height={Math.max(2, peak * 78)} rx={1.5}/>)}</svg>}<audio src={url || undefined} controls preload="metadata" aria-label={name}/></div>;
}

function AudioUpload({ file, onChange, video = false }: { file: File | null; onChange: (file: File) => void; video?: boolean }) {
  return <label className={`audio-upload${file ? " has-file" : ""}`} onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); const dropped = event.dataTransfer.files[0]; if (dropped) onChange(dropped); }}><span className="audio-upload-icon"><Icon name={file ? "audio" : "upload"} size={22}/></span><strong>{file ? file.name : t("Kayıt seç veya sürükleyip bırak")}</strong><small>{video ? t("Ses veya video kaydı") : t("Ses dosyası")} · WAV, MP3, M4A, OGG, WebM</small><input type="file" accept={video ? "audio/*,video/mp4,video/webm" : "audio/*"} aria-label={video ? t("Dönüştürülecek kayıt") : t("Referans kayıt")} onChange={event => { const selected = event.target.files?.[0]; if (selected) onChange(selected); event.target.value = ""; }}/></label>;
}

export function AudioWorkspace({ isActive }: { isActive: boolean }) {
  const workspace = React.useRef<HTMLDivElement>(null);
  const [tab, setTab] = React.useState<Tab>("tts");
  const [conversion, setConversion] = React.useState<"speech" | "singing">("speech");
  const [voiceMode, setVoiceMode] = React.useState<"clone" | "design">("clone");
  const [text, setText] = React.useState(() => { try { return localStorage.getItem("audio-text-draft") || ""; } catch { return ""; } });
  const [design, setDesign] = React.useState("");
  const [style, setStyle] = React.useState("natural");
  const [language, setLanguage] = React.useState("tr");
  const [profiles, setProfiles] = React.useState<VoiceProfile[]>([]);
  const [selectedId, setSelectedId] = React.useState("");
  const [source, setSource] = React.useState<File | null>(null);
  const [status, setStatus] = React.useState<Preparation | null>(null);
  const [sidebarHost, setSidebarHost] = React.useState<HTMLElement | null>(null);
  const [notice, setNotice] = React.useState("");
  const [profileDialog, setProfileDialog] = React.useState(false);
  const dialog = React.useRef<HTMLDialogElement>(null);
  const [reference, setReference] = React.useState<File | null>(null);
  const [name, setName] = React.useState("");
  const [transcript, setTranscript] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [profileError, setProfileError] = React.useState("");
  const [jobs, setJobs] = React.useState<AudioJob[]>([]);
  const [jobsReady, setJobsReady] = React.useState(false);
  const [posting, setPosting] = React.useState(false);
  const [result, setResult] = React.useState<AudioResult | null>(null);
  const [resultAudio, setResultAudio] = React.useState<Blob | null>(null);
  const seenResult = React.useRef("");
  const seenFailure = React.useRef("");
  const pending = React.useRef<{ fingerprint: string; key: string; referenceId?: string; sourceId?: string }>({ fingerprint: "", key: "" });
  const [historyCursor, setHistoryCursor] = React.useState<number | null>(null);
  const [loadingHistory, setLoadingHistory] = React.useState(false);
  const loadedOlder = React.useRef(false);
  const activeJob = jobs.find(job => ACTIVE_AUDIO.includes(job.status));
  const busy = posting || Boolean(activeJob);
  const labels: Record<string, string> = { QUEUED: t("Sırada"), PREPARING: t("Hazırlanıyor"), RUNNING: t("Üretiliyor"), CANCELLING: t("İptal ediliyor"), CLEANUP: t("Temizleniyor"), COMPLETED: t("Tamamlandı"), FAILED: t("Başarısız"), INTERRUPTED: t("İptal edildi"), RECOVERY_REQUIRED: t("Kaynak kontrolü gerekli") };
  const selected = profiles.find(profile => profile.id === selectedId);
  const packId = tab === "conversion" ? conversion === "singing" ? "singing" : "conversion" : "tts";
  const pack = status?.packs[packId];
  const requestedEngine = tab === 'conversion' ? conversion === 'singing' ? 'singing' : 'conversion' : 'tts';
  const engineReady = status?.engines?.[requestedEngine] ?? (requestedEngine === 'tts' && status?.engine_available);
  const engine = tab === "conversion" ? conversion === "singing" ? "Seed-VC SVC" : "Seed-VC V1 / V2" : "VoxCPM2";

  React.useEffect(() => { setSidebarHost(document.getElementById("sidebar-audio-controls")); }, []);
  React.useEffect(() => {
    let live = true;
    void listVoices().then(items => { if (live) { setProfiles(items); setSelectedId(items[0]?.id || ""); } }).catch(() => { if (live) setNotice(t("Ses kütüphanesi açılamadı.")); });
    return () => { live = false; };
  }, []);
  React.useEffect(() => { try { localStorage.setItem("audio-text-draft", text); } catch { /* Draft persistence is optional. */ } }, [text]);
  React.useEffect(() => {
    if (!isActive) return;
    let live = true;
    let timer: number;
    const refresh = async () => {
      try { const value = await responseJson(await fetch("/api/v1/audio/status")); if (live) setStatus(value as unknown as Preparation); }
      catch { if (live) setStatus(null); }
      finally { if (live) timer = window.setTimeout(refresh, 4000); }
    };
    void refresh();
    return () => { live = false; window.clearTimeout(timer); };
  }, [isActive]);
  React.useEffect(() => {
    if (profileDialog && !dialog.current?.open) dialog.current?.showModal();
    else if (!profileDialog && dialog.current?.open) dialog.current.close();
  }, [profileDialog]);

  React.useEffect(() => {
    if (!isActive) return;
    let live = true;
    let timer: number;
    const refresh = async () => {
      try {
        const data = await responseJson(await fetch("/api/v1/audio/jobs"));
        if (live && Array.isArray(data.jobs)) {
          const next = data.jobs as AudioJob[];
          setJobs(current => [...next, ...current.filter(job => !next.some(item => item.id === job.id))]); setJobsReady(true);
          if (!loadedOlder.current) setHistoryCursor(typeof data.next_cursor === 'number' ? data.next_cursor : null);
          const newest = next[0];
          if (newest && seenFailure.current !== newest.id && ['FAILED','RECOVERY_REQUIRED'].includes(newest.status)) { seenFailure.current = newest.id; setNotice(newest.error || tr.requestFailed); }
          const latest = next.find(job => job.result);
          if (latest?.result && seenResult.current !== latest.id) { seenResult.current = latest.id; setResult(latest.result); }
        }
      } catch { if (live) setJobsReady(false); }
      finally { if (live) timer = window.setTimeout(refresh, 1500); }
    };
    void refresh();
    return () => { live = false; clearTimeout(timer); };
  }, [isActive]);
  React.useEffect(() => {
    setResultAudio(null);
    if (!result) return;
    const controller = new AbortController();
    void fetch(result.url, { signal: controller.signal }).then(response => { if (!response.ok) throw new Error(); return response.blob(); }).then(blob => { if (!controller.signal.aborted) setResultAudio(blob); }).catch(() => { if (!controller.signal.aborted) setNotice(tr.requestFailed); });
    return () => controller.abort();
  }, [result]);
  const loadMoreHistory = async () => {
    if (!historyCursor || loadingHistory) return;
    loadedOlder.current = true; setLoadingHistory(true);
    try {
      const data = await responseJson(await fetch('/api/v1/audio/jobs?before=' + historyCursor));
      const items = data.jobs as AudioJob[];
      setJobs(current => [...current,...items.filter(job => !current.some(old => old.id === job.id))]);
      setHistoryCursor(typeof data.next_cursor === 'number' ? data.next_cursor : null);
    } catch { setNotice(tr.requestFailed); }
    finally { setLoadingHistory(false); }
  };
  const generate = async () => {
    if (busy || !engineReady || (tab === 'tts' ? !text.trim() || (voiceMode === 'clone' && !selected) : !source || !selected)) return;
    setPosting(true); setNotice('');
    const fingerprint = JSON.stringify({text,voiceMode,profile:selected?.id,design,style,language,requestedEngine,source:source && [source.name,source.size,source.lastModified]});
    if (pending.current.fingerprint !== fingerprint) {
      const previous = pending.current;
      pending.current = {fingerprint,key:crypto.randomUUID()};
      for (const id of [previous.referenceId,previous.sourceId]) if (id) void sendJson('/api/v1/audio/references/'+id,'DELETE',{}).catch(() => {});
    }
    try {
      const upload = async (audio: Blob) => {
        const session = await responseJson(await fetch('/api/v1/session'));
        const data = await responseJson(await fetch('/api/v1/audio/references', {method:'POST',headers:{'Content-Type':'application/octet-stream','X-CSRF-Token':String(session.csrf_token)},body:audio}));
        return data.reference_id as string;
      };
      const needsReference = requestedEngine !== 'tts' || voiceMode === 'clone';
      if (needsReference && selected && !pending.current.referenceId) pending.current.referenceId = await upload(selected.audio);
      if (requestedEngine !== 'tts' && source && !pending.current.sourceId) pending.current.sourceId = await upload(source);
      const created = await sendJson('/api/v1/audio/jobs','POST',{
        engine:requestedEngine,text:requestedEngine === 'tts' ? text : source?.name || '',
        mode:requestedEngine === 'tts' ? voiceMode : 'clone',description:voiceMode === 'design' ? design : '',language,style,
        reference_id:needsReference ? pending.current.referenceId : null,source_id:requestedEngine === 'tts' ? null : pending.current.sourceId,
        transcript:requestedEngine === 'tts' && voiceMode === 'clone' ? selected?.transcript || '' : '', idempotency_key:pending.current.key,
      }) as unknown as AudioJob;
      setJobs(current => [created,...current.filter(job => job.id !== created.id)]);
      pending.current = {fingerprint:'',key:''};
    } catch (error) {
      setNotice(error instanceof Error ? error.message : tr.requestFailed);
      if (error instanceof HttpError && error.status >= 400 && error.status < 500) {
        for (const id of [pending.current.referenceId,pending.current.sourceId]) if (id) void sendJson('/api/v1/audio/references/'+id,'DELETE',{}).catch(() => {});
        pending.current = {fingerprint:'',key:''};
      }
    } finally {setPosting(false);}
  };
  const cancel = async () => {
    if (!activeJob) return;
    try { const updated = await sendJson(`/api/v1/audio/jobs/${activeJob.id}/cancel`, "POST", {}) as unknown as AudioJob; setJobs(current => current.map(job => job.id === updated.id ? updated : job)); }
    catch (error) { setNotice(error instanceof Error ? error.message : tr.requestFailed); }
  };

  const openProfile = () => { setName(""); setTranscript(""); setReference(null); setProfileError(""); setProfileDialog(true); };
  const selectFile = (file: File, target: "source" | "reference") => {
    if (file.size > 100 * 1024**2) { if (target === "reference") setProfileError(t("Kayıt 100 MB altında olmalı.")); else setNotice(t("Kayıt 100 MB altında olmalı.")); return; }
    if (!file.size || (!file.type.startsWith("audio/") && !file.type.startsWith("video/") && !/\.(wav|mp3|m4a|flac|ogg|webm|mp4)$/i.test(file.name))) {
      if (target === "reference") setProfileError(t("Geçerli bir ses kaydı seçin.")); else setNotice(t("Geçerli bir ses kaydı seçin."));
      return;
    }
    if (target === "source") { setSource(file); setNotice(""); }
    else { setReference(file); setProfileError(""); if (!name) setName(file.name.replace(/\.[^.]+$/, "")); }
  };
  const createProfile = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!reference || !name.trim() || saving) return;
    setSaving(true); setProfileError("");
    try {
      const profile: VoiceProfile = { id: crypto.randomUUID(), name: name.trim(), transcript: transcript.trim(), audio: reference, filename: reference.name, createdAt: new Date().toISOString() };
      await saveVoice(profile); setProfiles(current => [...current, profile]); setSelectedId(profile.id); setProfileDialog(false); setNotice("");
    } catch { setProfileError(t("Ses profili kaydedilemedi.")); }
    finally { setSaving(false); }
  };
  const removeProfile = async (profile: VoiceProfile) => {
    if (!window.confirm(t("Bu ses profilini silmek istiyor musun?"))) return;
    try { await deleteVoice(profile.id); setProfiles(current => current.filter(item => item.id !== profile.id)); if (selectedId === profile.id) setSelectedId(profiles.find(item => item.id !== profile.id)?.id || ""); }
    catch { setNotice(t("Ses profili silinemedi.")); }
  };

  React.useEffect(() => {
    if (!isActive) workspace.current?.querySelectorAll("audio").forEach(audio => audio.pause());
  }, [isActive]);

  const voicePicker = <div className="audio-voice-picker"><div className="audio-field-heading"><label htmlFor="audio-voice">{t("Ses profili")}</label><button type="button" onClick={openProfile}><Icon name="plus" size={13}/>{t("Kendi sesini ekle")}</button></div><select id="audio-voice" value={selectedId} onChange={event => setSelectedId(event.target.value)}><option value="">{t("Ses profili seç")}</option>{profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select></div>;

  return <div className="audio-workspace" ref={workspace}>
    {sidebarHost && createPortal(<section className="sidebar-model audio-sidebar-status"><div className="sidebar-model-heading"><span className="sidebar-model-symbol"><Icon name="audio" size={18}/></span><div><strong>{t("Ses stüdyosu")}</strong><small>{engine}</small></div></div><div className="audio-engine-state"><span/>{engineReady ? busy ? t("Üretiliyor") : t("Hazır") : t("Motor kurulumu bekleniyor")}</div><div className="audio-download-summary"><span>{t("Model dosyaları")}</span><strong>{pack ? `${pack.present} / ${pack.total}` : "—"}</strong></div>{pack && <><div className="audio-download-track" aria-hidden="true"><i style={{ width: `${pack.present / Math.max(pack.total, 1) * 100}%` }}/></div><small>{pack.present === pack.total ? t("Dosyalar mevcut") : pack.partial ? t("Dosyalar indiriliyor") : t("Dosya hazırlığı sürüyor")} · {formatBytes(pack.bytes)}</small></>}</section>, sidebarHost)}
    <div className="audio-workspace-heading"><div><h2>{t("Kelimelerine ses ver.")}</h2><p>{t("Sesini kaydet, metin okut veya bir repliği dönüştür.")}</p></div><span className="audio-local-label"><Icon name="shield" size={14}/>{tr.localOnly}</span></div>
    <div className="audio-workspace-tabs" role="group" aria-label={t("Ses çalışma modu")}>{([{ id: "tts", label: t("Metni Seslendir"), icon: "mic" }, { id: "conversion", label: t("Ses Dönüştür"), icon: "audio" }, { id: "voices", label: t("Seslerim"), icon: "layers" }] as const).map(item => <button key={item.id} type="button" aria-pressed={tab === item.id} onClick={() => setTab(item.id)}><Icon name={item.icon} size={17}/>{item.label}{item.id === "voices" && <span>{profiles.length}</span>}</button>)}</div>
    {notice && <p className="audio-notice" role="alert">{localizeMessage(notice)}</p>}
    {tab === "voices" ? <section className="audio-library"><div className="audio-library-heading"><div><h3>{t("Yerel ses kütüphanen")}</h3><p>{t("Ses kayıtları bu tarayıcıda saklanır.")}</p></div><button type="button" className="primary-button" onClick={openProfile}><Icon name="plus" size={16}/>{t("Kendi sesini ekle")}</button></div>{profiles.length ? <div className="audio-profile-grid">{profiles.map(profile => <article key={profile.id} className={`audio-profile-card${selectedId === profile.id ? " selected" : ""}`}><div className="audio-profile-card-heading"><span><Icon name="mic" size={20}/></span><h3>{profile.name}</h3><button type="button" onClick={() => void removeProfile(profile)} aria-label={t("Ses profilini sil")}><Icon name="trash" size={16}/></button></div><p>{profile.transcript || profile.filename}</p><button className="secondary-button" type="button" aria-pressed={selectedId === profile.id} onClick={() => setSelectedId(profile.id)}>{selectedId === profile.id ? t("Seçili") : t("Seç ve dinle")}</button>{selectedId === profile.id && <AudioPreview audio={profile.audio} name={profile.filename}/>}</article>)}</div> : <div className="audio-library-empty"><span><Icon name="mic" size={31}/></span><h3>{t("İlk sesini ekle.")}</h3><p>{t("Temiz bir kayıt yükle, adını ver ve sonraki çalışmalarında tekrar kullan.")}</p><button className="secondary-button" type="button" onClick={openProfile}><Icon name="plus" size={16}/>{t("Yeni ses profili")}</button></div>}</section> : <div className="audio-studio-grid">
      <section className="panel audio-controls"><div className="audio-controls-heading"><span>{engine}</span><h3>{tab === "tts" ? t("Ne söylemesini istersin?") : t("Sesi değiştir, anı koru.")}</h3></div>
        {tab === "tts" ? <><div className="audio-segment" role="group" aria-label={t("Ses seçimi")}><button type="button" aria-pressed={voiceMode === "clone"} onClick={() => setVoiceMode("clone")}>{t("Kendi sesim")}</button><button type="button" aria-pressed={voiceMode === "design"} onClick={() => setVoiceMode("design")}>{t("Karakter tasarla")}</button></div>{voiceMode === "clone" ? voicePicker : <label className="audio-field">{t("Ses tarifi")}<textarea rows={3} maxLength={1000} value={design} onChange={event => setDesign(event.target.value)} placeholder={t("Yaş, ses tonu ve karakter özelliklerini anlat…")}/></label>}<label className="audio-field">{t("Okunacak metin")}<textarea className="audio-script" rows={8} maxLength={8000} value={text} onChange={event => setText(event.target.value)} placeholder={t("Kelimelerini buraya yaz…")}/></label><div className="audio-settings-row"><label>{t("Konuşma dili")}<select value={language} onChange={event => setLanguage(event.target.value)}>{[...LANGS.filter(item => item.code !== 'bn' && item.code !== 'ur'), {code:'ja', name:'日本語'}, {code:'de', name:'Deutsch'}].map(item => <option key={item.code} value={item.code}>{item.name}</option>)}</select></label><label>{t("Söyleyiş")}<select value={style} onChange={event => setStyle(event.target.value)}>{[['natural',t("Doğal")],['calm',t("Sakin")],['energetic',t("Enerjik")],['dramatic',t("Dramatik")]].map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select></label></div></> : <><div className="audio-segment" role="group" aria-label={t("Dönüşüm türü")}><button type="button" aria-pressed={conversion === "speech"} onClick={() => setConversion("speech")}><Icon name="mic" size={15}/>{t("Replik")}</button><button type="button" aria-pressed={conversion === "singing"} onClick={() => setConversion("singing")}><Icon name="music" size={15}/>{t("Şarkı")}</button></div><div className="audio-field"><span>{t("Dönüştürülecek kayıt")}</span><AudioUpload file={source} onChange={file => selectFile(file, "source")} video/>{source && <button className="audio-clear-source" type="button" onClick={() => setSource(null)}>{t("Kaydı kaldır")}</button>}</div>{voicePicker}<div className="audio-preserve-note"><Icon name={conversion === "singing" ? "music" : "activity"} size={18}/><p>{conversion === "singing" ? t("Melodi ve sözler kaynak kayıttan alınır.") : t("Repliğin sözleri ve oyunculuğu korunmaya çalışılır.")}</p></div><p className="audio-caption">{t("Ses dönüşümü kaydın dilini değiştirmez.")}</p></>}
        <div className="audio-generate-area"><button type="button" className="primary-button" disabled={!engineReady || !jobsReady || busy || (tab === "tts" ? !text.trim() || (voiceMode === "clone" && !selected) : !source || !selected)} title={engineReady ? "" : t("Motor kurulumu bekleniyor")} onClick={() => void generate()}><Icon name={tab === "tts" ? "mic" : "audio"} size={18}/>{busy && tab === "tts" ? t("Üretiliyor") : tab === "tts" ? t("Ses üret") : t("Sesi dönüştür")}</button><p>{engineReady ? t("Model üretim sırasında yüklenir") : t("Ses motoru kurulumu tamamlanınca üretim açılacak.")}</p>{activeJob && <div className="audio-active-job" role="status"><progress aria-label={t("Üretiliyor")}/><span>{labels[activeJob.status] || activeJob.status}</span><button type="button" disabled={activeJob.status === "CANCELLING"} onClick={() => void cancel()}>{t("İptal et")}</button></div>}</div>
      </section>
      <section className="audio-output"><div className="audio-output-toolbar"><h3>{t("Dinleme alanı")}</h3><span>{status?.engine_available && tab === "tts" ? t("Hazır") : t("Motor kurulumu bekleniyor")}</span></div>{result ? <div className="audio-result"><span className="audio-result-icon"><Icon name="audio" size={35}/></span><h3>{t("Sonuç")}</h3>{resultAudio ? <AudioPreview audio={resultAudio} name={result.filename}/> : <p>{tr.loading}</p>}<div className="audio-result-meta"><span>{formatNumber(result.seconds)} {t("sn")} · {formatNumber(result.sample_rate / 1000)} kHz · {formatBytes(result.bytes)}</span><a href={result.url} download={result.filename}><Icon name="arrow-down" size={15}/>{t("Sesi indir")}</a></div></div> : <div className="audio-output-empty"><span className="audio-empty-mark"><Icon name="audio" size={43}/></span><h3>{t("Sesin burada hayat bulacak.")}</h3><p>{t("Üretilen sesi burada dinleyeceksin.")}</p><div className="audio-flow"><span><Icon name="file" size={14}/>{tab === "tts" ? t("Metin") : t("Kaynak kayıt")}</span><Icon name="arrow-right" size={13}/><span><Icon name="mic" size={14}/>{t("Ses profili")}</span><Icon name="arrow-right" size={13}/><span><Icon name="audio" size={14}/>{t("Sonuç")}</span></div></div>}<div className="audio-input-list">{tab === "conversion" && source && <div><h4>{t("Kaynak kayıt")}</h4><AudioPreview audio={source} name={source.name}/></div>}{selected && (tab === "conversion" || voiceMode === "clone") && <div><h4>{t("Referans sesini dinle")}</h4><AudioPreview audio={selected.audio} name={selected.filename}/></div>}</div><div className="audio-output-footer"><Icon name="hard-drive" size={14}/><span>{pack ? `${pack.present} / ${pack.total}` : "—"} {t("Model dosyaları")} · {pack ? formatBytes(pack.bytes) : t("Durum alınamadı")}</span></div></section>
    </div>}
    {jobs.length > 0 && <details className="audio-history"><summary>{t("Ses geçmişi")}<span>{jobs.length}</span><Icon name="chevron-down" size={15}/></summary><div>{jobs.map(job => <article key={job.id}><div><strong>{job.text}</strong><small>{formatDate(job.created_at, true)}</small>{job.error && <p className="error-text">{localizeMessage(job.error)}</p>}</div><span>{labels[job.status] || job.status}</span>{job.result && <button type="button" onClick={() => { setResult(job.result!); setTab("tts"); }}>{t("Göster")}</button>}</article>)}{historyCursor && <button type="button" className="secondary-button" disabled={loadingHistory} onClick={() => void loadMoreHistory()}>{loadingHistory ? tr.loading : t("Daha fazla yükle")}</button>}</div></details>}
    <dialog ref={dialog} className="audio-profile-dialog" aria-labelledby="audio-profile-title" onCancel={event => { event.preventDefault(); if (!saving) setProfileDialog(false); }} onClose={() => setProfileDialog(false)}><form onSubmit={event => void createProfile(event)}><header><div><span>{t("Seslerim")}</span><h2 id="audio-profile-title">{t("Yeni ses profili")}</h2></div><button type="button" aria-label={t("Paneli kapat")} disabled={saving} onClick={() => setProfileDialog(false)}><Icon name="x" size={20}/></button></header><AudioUpload file={reference} onChange={file => selectFile(file, "reference")}/><p className="audio-caption">{t("Referans kaydın ilk 30 saniyesi kullanılır.")}</p><label className="audio-field">{t("Ses adı")}<input required maxLength={80} value={name} onChange={event => setName(event.target.value)}/></label><label className="audio-field">{t("Kaydın metni")}<span className="audio-caption">{tr.optional}</span><textarea rows={3} maxLength={4000} value={transcript} onChange={event => setTranscript(event.target.value)}/></label>{profileError && <p className="audio-notice" role="alert">{localizeMessage(profileError)}</p>}<footer><span>{t("Ses kayıtları bu tarayıcıda saklanır.")}</span><button type="submit" className="primary-button" disabled={saving || !reference || !name.trim()}>{saving ? tr.saving : t("Profili kaydet")}</button></footer></form></dialog>
  </div>;
}
