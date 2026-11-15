import { Icon } from "./Icon";
import { ActionButton } from "./ui/Primitives";
import { t, localizeMessage, tr } from "../i18n";
import { gemmaStateLabel, startBlockedReason, type GemmaState } from "../lib/shared";

type Props = {
  modelId: string;
  models: GemmaState[];
  status: GemmaState;
  disabled: boolean;
  busy: boolean;
  notice: string;
  onChange: (id: string) => void;
  onStart: () => void;
  onStop: () => void;
};

/** Sidebar is the single location for LLM selection and lifecycle controls. */
export function SidebarModel({ modelId, models, status, disabled, busy, notice, onChange, onStart, onStop }: Props) {
  const running = status.state === "RUNNING" && status.managed;
  const pending = status.state === "ACQUIRING";
  const blocked = startBlockedReason(status);
  const choices = models.some(item => item.model_id === modelId)
    ? models
    : [...models, { model_id: modelId, model: modelId, state: "UNKNOWN" }];
  return <section className="sidebar-model" aria-label={t("Yerel model kontrolü")}>
    <div className="sidebar-model-heading"><span className="sidebar-model-symbol"><Icon name="models" size={18} /></span><div><strong>{t("AI Modeli")}</strong><small>{t("YEREL MODEL KONTROLÜ")}</small></div></div>
    <label className="sidebar-model-select" htmlFor="sidebar-llm-model">{t("Model seçimi")}<span className="sidebar-model-select-wrap"><select id="sidebar-llm-model" value={modelId} disabled={disabled || models.length === 0}
        onChange={event => onChange(event.target.value)}>
        {choices.map(item => <option key={item.model_id} value={item.model_id}>{item.model ?? item.model_id}</option>)}
      </select><Icon name="chevron-down" size={15} /></span>
    </label>
    <div className="sidebar-model-state" role="status"><span className={`sidebar-model-dot${running ? " running" : pending ? " pending" : ""}`} /><span>{gemmaStateLabel(status.state)}</span></div>

    {blocked && <p className="sidebar-model-note blocked" title={localizeMessage(blocked)}>{localizeMessage(blocked)}</p>}
    {notice && <p className="sidebar-model-note sidebar-model-notice" role="status">{localizeMessage(notice)}</p>}
    {running ? <ActionButton variant="secondary" icon="bolt" type="button" className="sidebar-model-button sidebar-model-stop" disabled={disabled} onClick={onStop}>{tr.stopGemma}</ActionButton>
      : <ActionButton variant="primary" icon="bolt" type="button" className="sidebar-model-button" disabled={disabled || !status.start_allowed || status.state !== "IDLE"} onClick={onStart}>{busy ? tr.gemmaStarting : tr.loadGemma}</ActionButton>}
  </section>;
}
