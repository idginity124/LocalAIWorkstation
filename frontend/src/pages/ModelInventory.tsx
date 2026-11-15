import React from "react";
import { t, localizeMessage, tr } from "../i18n";
import { Icon } from "../components/Icon";
import { responseJson, formatBytes } from "../lib/shared";

type ModelAsset = { actual_bytes?: number | null; filename: string; path: string; present: boolean; expected_size_label: string; hash_verified: boolean | null; source: string };
type LocalModel = { id: string; name: string; format: string; license: string; status: "missing" | "files_present_hash_not_checked" | "hash_verified"; assets: ModelAsset[]; warning: string };
type Runtime = { models: Array<{ model_id: string; state: string; managed: boolean }>; image: { comfy_running: boolean } };
type Filter = "all" | "chat" | "image";
const imageModel = (model: LocalModel) => ["z-image-turbo", "flux2-klein"].includes(model.id);
const purpose = (model: LocalModel) => model.id === "flux2-klein" ? t("Görsel düzenleme") : imageModel(model) ? t("Görsel üretimi") : t("Sohbet ve kod");
const diskSize = (model: LocalModel) => model.assets.reduce((total, asset) => total + (asset.present ? asset.actual_bytes ?? 0 : 0), 0);

export function ModelInventory({ active = true }: { active?: boolean }) {
  const [models, setModels] = React.useState<LocalModel[] | null>(null);
  const [runtime, setRuntime] = React.useState<Runtime | null>(null);
  const [message, setMessage] = React.useState("");
  const [refreshing, setRefreshing] = React.useState(false);
  const [filter, setFilter] = React.useState<Filter>("all");
  const [revision, setRevision] = React.useState(0);

  React.useEffect(() => {
    if (!active) return;
    let live = true;
    setRefreshing(true);
    void fetch("/api/v1/models", { headers: { Accept: "application/json" } })
      .then(responseJson)
      .then(value => {
        if (!Array.isArray(value.models)) throw new Error(tr.invalidResponse);
        if (live) { setModels(value.models as LocalModel[]); setMessage(""); }
      })
      .catch(reason => { if (live) setMessage(reason instanceof Error ? reason.message : tr.modelsUnavailable); })
      .finally(() => { if (live) setRefreshing(false); });
    return () => { live = false; };
  }, [active, revision]);

  React.useEffect(() => {
    if (!active) return;
    let live = true;
    let timer: number;
    const refresh = async () => {
      try {
        const value = await responseJson(await fetch("/api/v1/runtime"));
        if (live) setRuntime(value as unknown as Runtime);
      } catch { if (live) setRuntime(null); }
      finally { if (live) timer = window.setTimeout(refresh, 5000); }
    };
    void refresh();
    return () => { live = false; window.clearTimeout(timer); };
  }, [active, revision]);

  if (!models) return <section className="panel"><p className="muted" role="status">{message ? localizeMessage(message) : tr.loadingModels}</p>{message && <button type="button" className="secondary-button" onClick={() => setRevision(value => value + 1)}>{t("Tekrar dene")}</button>}</section>;
  const uniqueAssets = new Map(models.flatMap(model => model.assets).filter(asset => asset.present).map(asset => [asset.path, asset]));
  const totalBytes = [...uniqueAssets.values()].reduce((total, asset) => total + (asset.actual_bytes ?? 0), 0);
  const visible = models.filter(model => filter === "all" || (filter === "image") === imageModel(model));
  const complete = models.filter(model => model.status !== "missing").length;

  return <section className="model-inventory inventory-v2" aria-label={t("Yerel model envanteri")}>
    <div className="inventory-heading"><div><h2>{t("Model kütüphanesi")}</h2><p>{t("Cihazınızdaki sohbet ve görsel modelleri.")}</p></div><button type="button" className="secondary-button" disabled={refreshing} onClick={() => setRevision(value => value + 1)}><Icon name="activity" size={15}/>{refreshing ? t("Yenileniyor…") : t("Yenile")}</button></div>
    <div className="inventory-summary">
      <div><span className="inventory-summary-icon"><Icon name="models" size={20}/></span><span><strong>{models.length}</strong><small>{t("Kayıtlı model")}</small></span></div>
      <div><span className="inventory-summary-icon"><Icon name="folder" size={20}/></span><span><strong>{complete}<em> / {models.length}</em></strong><small>{t("Dosyaları tam")}</small></span></div>
      <div><span className="inventory-summary-icon"><Icon name="hard-drive" size={20}/></span><span><strong>{formatBytes(totalBytes)}</strong><small>{t("Katalogdaki dosyalar · ortak dosyalar bir kez sayılır")}</small></span></div>
    </div>
    <div className="inventory-filter-row"><div className="inventory-filters" role="group" aria-label={t("Model türü")}>{([['all', t("Tümü")], ['chat', t("Sohbet")], ['image', t("Görsel")]] as const).map(([key, label]) => <button type="button" key={key} aria-pressed={filter === key} onClick={() => setFilter(key)}>{label}<span>{models.filter(model => key === "all" || (key === "image") === imageModel(model)).length}</span></button>)}</div><span className="inventory-results" role="status">{visible.length} {" "}{t("model")}</span></div>
    {message && <p className="notice" role="alert">{localizeMessage(message)}</p>}
    <div className="inventory-cards">{visible.map(model => {
      const visual = imageModel(model);
      const liveModel = runtime?.models.find(item => item.model_id === (model.id === "gemma-4-12b-it-q4_0" ? "gemma-4-12b" : model.id));
      const running = liveModel?.state === "RUNNING" && liveModel.managed;
      const runtimeLabel = !runtime ? t("Durum alınamadı") : visual ? (runtime.image.comfy_running ? t("Görsel servisi açık") : t("Görsel servisi kapalı")) : running ? t("Model çalışıyor") : liveModel?.state === "ACQUIRING" ? t("Model yükleniyor") : liveModel?.state === "IDLE" ? t("Model yüklü değil") : t("Model durumu bilinmiyor");
      return <article className="panel model-card" key={model.id}>
        <div className="inventory-card-heading"><span className={`inventory-model-icon${visual ? " visual" : ""}`}><Icon name={visual ? "image" : "chat"} size={23}/></span><div><span className="inventory-purpose">{purpose(model)}</span><h3>{model.name}</h3></div></div>
        <div className="inventory-card-facts"><div><span>{t("Diskteki boyut")}</span><strong>{formatBytes(diskSize(model))}</strong></div><div><span>{t("Model dosyaları")}</span><strong className={model.status === "missing" ? "inventory-missing" : "inventory-present"}>{model.status === "missing" ? t("Eksik dosya var") : t("Dosyalar mevcut")}</strong></div></div>
        <div className="inventory-runtime"><span className={`inventory-status-dot${running || (visual && runtime?.image.comfy_running) ? " running" : ""}`}/>{runtimeLabel}{visual && <span className="inventory-runtime-hint">{t("Model üretim sırasında yüklenir")}</span>}</div>
        <details className="inventory-details"><summary>{t("Ayrıntılar")}<Icon name="chevron-down" size={15}/></summary><div className="inventory-details-body">
          <dl><div><dt>{t("Biçim")}</dt><dd>{t(model.format)}</dd></div><div><dt>{t("Lisans")}</dt><dd>{t(model.license)}</dd></div><div><dt>{t("Doğrulama")}</dt><dd>{model.status === "hash_verified" ? t("Dosya hash’leri doğrulandı.") : t("Dosya içeriği hash ile doğrulanmadı.")}</dd></div>{model.warning && <div><dt>{t("Not")}</dt><dd>{t(model.warning)}</dd></div>}</dl>
          <div className="asset-list">{model.assets.map(asset => <div className="asset-row" key={asset.path}><div><strong>{asset.filename}</strong><small><code>{asset.path}</code></small><small>{asset.actual_bytes != null ? formatBytes(asset.actual_bytes) : tr.unavailable} · {asset.present ? t("Dosya mevcut") : t("Dosya eksik")}</small>{model.id === "flux2-klein" && asset.filename === "qwen_3_4b_fp8_mixed.safetensors" && <small>{t("Z-Image ile ortak kullanılır.")}</small>}</div>{asset.source && <a href={asset.source} target="_blank" rel="noopener noreferrer">{t("Kaynak")}<span className="sr-only">: {asset.filename}</span></a>}</div>)}</div>
        </div></details>
      </article>;
    })}</div>
    {visible.length === 0 && <div className="panel inventory-empty"><Icon name="models" size={26}/><p>{t("Bu kategoride kayıtlı model yok.")}</p></div>}
  </section>;
}
