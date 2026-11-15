import { t, localizeMessage } from "../i18n";
import React from 'react';
import { responseJson } from '../lib/shared';
export function Diagnostics() {
  const [logs, setLogs] = React.useState<Array<{name: string; path: string; text: string}>>([]);
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const refresh = async () => {
    setBusy(true); setError('');
    try { const data = await responseJson(await fetch('/api/v1/diagnostics')); setLogs(data.logs as typeof logs); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("Günlük okunamadı.")); }
    finally { setBusy(false); }
  };
  return <section className="panel diagnostics"><div className="panel-head"><h2>{t("Servis günlükleri")}</h2><button className="secondary-button" disabled={busy} onClick={() => void refresh()}>{busy ? t("Okunuyor…") : t("Günlükleri getir")}</button></div><p className="muted">{t("Model başlatma ve üretim hatalarının ayrıntılarını buradan inceleyebilirsiniz.")}</p>{error && <p className="error-text">{localizeMessage(error)}</p>}{logs.map(log => <details key={log.name}><summary>{log.name}</summary><small>{log.path}</small><pre>{log.text}</pre></details>)}</section>;
}
