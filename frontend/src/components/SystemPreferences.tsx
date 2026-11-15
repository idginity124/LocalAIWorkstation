import { t, localizeMessage } from "../i18n";
import React from "react";
import { Icon } from "./Icon";
import { Diagnostics } from "./Diagnostics";
import { formatBytes } from "../lib/shared";

export type Settings = { theme: "dark" | "light" | "system"; telemetry_refresh_seconds: 2 | 5 | 10 };
export type Hardware = {
  os: string; kernel: string; desktop_session: string; gpu_state: string; gpu_owner?: string | null; gpu_reason?: string;
  memory: { total_bytes: number | null; available_bytes: number | null; swap_total_bytes: number | null; swap_free_bytes: number | null };
  gpus: Array<{ device: string; name: string | null; vram_used_bytes: number | null; vram_total_bytes: number | null; temperature_millic: string | null; gpu_busy_percent: string | null }>;
};
type Props = {
  open: boolean; onClose: () => void; settings: Settings; settingsReady: boolean; settingsError: boolean;
  hardware: Hardware | null; hardwareError: boolean; saving: boolean; message: string;
  onChange: <K extends keyof Settings>(key: K, value: Settings[K]) => Promise<void>;
};

function Resource({ label, used, total }: { label: string; used: number | null | undefined; total: number | null | undefined }) {
  const fraction = used != null && total != null && total > 0 ? Math.min(1, Math.max(0, used / total)) : null;
  return <div className="preferences-resource"><div><strong>{label}</strong><span>{formatBytes(used)} <small>/ {formatBytes(total)}</small></span></div><div className="preferences-resource-track" aria-hidden="true"><i style={{ width: `${(fraction ?? 0) * 100}%` }}/></div></div>;
}

export function SystemPreferences(props: Props) {
  const { open, onClose, settings, settingsReady, settingsError, hardware, hardwareError, saving, message, onChange } = props;
  const dialog = React.useRef<HTMLDialogElement>(null);
  React.useEffect(() => {
    const element = dialog.current;
    if (open && !element?.open) element?.showModal();
    else if (!open && element?.open) element.close();
  }, [open]);
  const gpu = hardware?.gpus[0];
  const memory = hardware?.memory;
  const ramUsed = memory?.total_bytes != null && memory.available_bytes != null ? Math.max(0, memory.total_bytes - memory.available_bytes) : null;
  const temperature = gpu?.temperature_millic != null && Number.isFinite(Number(gpu.temperature_millic)) ? `${(Number(gpu.temperature_millic) / 1000).toFixed(0)} °C` : t("Ölçülmüyor");
  const resourceStates: Record<string, string> = {
    IDLE: t("Boşta"), QUEUED: t("Sırada"), ACQUIRING: t("Hazırlanıyor"), RUNNING: t("Çalışıyor"),
    RELEASING: t("Bellek boşaltılıyor"), VERIFYING: t("Kontrol ediliyor"), CLEANUP: t("Temizleniyor"),
    RECOVERY_REQUIRED: t("Kaynak kontrolü gerekli"), UNKNOWN: t("Bilinmiyor"),
  };
  return <dialog ref={dialog} className="preferences-dialog" aria-labelledby="preferences-title" onCancel={event => { event.preventDefault(); onClose(); }} onClose={onClose} onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="preferences-content">
      <header className="preferences-header"><span className="preferences-heading-icon"><Icon name="settings" size={21}/></span><div><h2 id="preferences-title">{t("Sistem ve Tercihler")}</h2><p>{t("Çalışma alanınızı kendinize göre ayarlayın.")}</p></div><button type="button" className="preferences-close" onClick={onClose} aria-label={t("Paneli kapat")} autoFocus><Icon name="x" size={20}/></button></header>
      <div className="preferences-body">
        <section className="preferences-section" aria-labelledby="appearance-title"><h3 id="appearance-title">{t("Görünüm")}</h3><div className="preferences-theme" role="group" aria-label={t("Tema")}>{([['light', t("Açık")], ['dark', t("Koyu")], ['system', t("Sistem")]] as const).map(([value, label]) => <button key={value} type="button" aria-pressed={settings.theme === value} disabled={saving || !settingsReady || settingsError} onClick={() => void onChange("theme", value)}><span aria-hidden="true" className={`preferences-theme-preview preview-${value}`}><i/><i/><i/></span><span>{label}</span></button>)}</div><p className="preferences-save-state" role="status">{settingsError ? t("Tercihler yüklenemedi. Sayfayı yenileyerek tekrar deneyin.") : saving ? t("Kaydediliyor…") : (message ? localizeMessage(message) : "") || t("Değişiklikler otomatik kaydedilir.")}</p></section>
        <section className="preferences-section" aria-labelledby="resources-title"><div className="preferences-section-heading"><h3 id="resources-title">{t("Kaynaklar")}</h3><span>{t("Canlı ·")}{" "}{settings.telemetry_refresh_seconds} {" "}{t("sn")}</span></div>
          {hardwareError ? <p className="preferences-warning">{t("Sistem verilerine ulaşılamıyor.")}</p> : !hardware ? <p className="muted">{t("Kaynak bilgileri alınıyor…")}</p> : <><Resource label={t("RAM kullanımı")} used={ramUsed} total={memory?.total_bytes}/><Resource label={t("GPU belleği")} used={gpu?.vram_used_bytes} total={gpu?.vram_total_bytes}/><div className="preferences-gpu-facts"><span>{t("GPU sıcaklığı")}<strong>{temperature}</strong></span><span>{t("GPU kullanımı")}<strong>{gpu?.gpu_busy_percent != null ? `${gpu.gpu_busy_percent}%` : t("Ölçülmüyor")}</strong></span></div></>}
        </section>
        <section className="preferences-section preferences-advanced" aria-labelledby="advanced-title"><h3 id="advanced-title">{t("Gelişmiş")}</h3>
          <details><summary>{t("Yenileme sıklığı")}<Icon name="chevron-down" size={15}/></summary><div className="preferences-detail-content"><label className="preferences-refresh"><span>{t("Kaynak bilgileri")}<small>{t("Daha seyrek yenilemek sistem sorgularını azaltır.")}</small></span><select aria-label={t("Kaynak yenileme sıklığı")} value={settings.telemetry_refresh_seconds} disabled={saving || !settingsReady || settingsError} onChange={event => void onChange("telemetry_refresh_seconds", Number(event.target.value) as Settings["telemetry_refresh_seconds"])}>{([2, 5, 10] as const).map(value => <option key={value} value={value}>{value} {" "}{t("saniye")}</option>)}</select></label></div></details>
          <details><summary>{t("Donanım ayrıntıları")}<Icon name="chevron-down" size={15}/></summary><div className="preferences-detail-content">{hardware && !hardwareError ? <dl className="preferences-hardware"><div><dt>{t("İşletim sistemi")}</dt><dd>{hardware.os}</dd></div><div><dt>{t("Kernel")}</dt><dd>{hardware.kernel}</dd></div><div><dt>{t("Masaüstü")}</dt><dd>{hardware.desktop_session}</dd></div><div><dt>GPU</dt><dd>{gpu?.name || t("Model adı okunamadı")}</dd></div><div><dt>{t("Kullanılabilir swap")}</dt><dd>{formatBytes(memory?.swap_free_bytes)} / {formatBytes(memory?.swap_total_bytes)}</dd></div><div><dt>{t("GPU kaynak durumu")}</dt><dd>{hardware.gpu_owner || (resourceStates[hardware.gpu_state] ?? t("Bilinmiyor"))}{hardware.gpu_reason && <small>{localizeMessage(hardware.gpu_reason)}</small>}</dd></div></dl> : <p className="muted">{t("Donanım bilgilerine ulaşılamıyor.")}</p>}</div></details>
          <details><summary>{t("Servis günlükleri")}<Icon name="chevron-down" size={15}/></summary><div className="preferences-detail-content">{open && <Diagnostics/>}</div></details>
        </section>
      </div>
    </div>
  </dialog>;
}
