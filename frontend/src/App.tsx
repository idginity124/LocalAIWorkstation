import React from "react";
import { t, tr } from "./i18n";
import { SystemPreferences, type Settings, type Hardware } from "./components/SystemPreferences";
import { type IconName } from "./components/Icon";
import { ChatWorkspace } from "./pages/ChatWorkspace";
import { ImageWorkspace } from "./pages/ImageWorkspace";
import { CodeWorkspace } from "./pages/CodeWorkspace";
import { AudioWorkspace } from "./pages/AudioWorkspace";
import { ModelInventory } from "./pages/ModelInventory";
import { responseJson, sendJson, type GemmaState } from "./lib/shared";
import { AppHeader, AppSidebar } from "./components/AppChrome";
type Page = "assistant" | "code" | "image" | "audio" | "models";

export function App() {
  const [page, setPage] = React.useState<Page>(() => { const page = localStorage.getItem("workstation-page"); return ["assistant", "code", "image", "audio", "models"].includes(page ?? "") ? page as Page : "assistant"; });
  const [visited, setVisited] = React.useState<Set<Page>>(() => new Set([page]));
  const [sidebarCollapsed, setSidebarCollapsed] = React.useState(() => {
    try { return localStorage.getItem("workstation-sidebar-collapsed") === "true"; } catch { return false; }
  });
  const [mobileSidebarOpen, setMobileSidebarOpen] = React.useState(false);
  const closeMobileSidebar = React.useCallback(() => {
    setMobileSidebarOpen(false);
    if (window.matchMedia("(max-width: 800px)").matches) {
      window.requestAnimationFrame(() => document.querySelector<HTMLButtonElement>(".mobile-menu-toggle")?.focus());
    }
  }, []);
  React.useEffect(() => {
    try { localStorage.setItem("workstation-sidebar-collapsed", String(sidebarCollapsed)); } catch { /* optional UI preference */ }
  }, [sidebarCollapsed]);
  React.useEffect(() => {
    if (!mobileSidebarOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape") closeMobileSidebar(); };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [mobileSidebarOpen, closeMobileSidebar]);
  React.useEffect(() => { localStorage.setItem("workstation-page", page); setVisited(current => new Set([...current, page])); }, [page]);
  const [hardware, setHardware] = React.useState<Hardware | null>(null);
  const [settings, setSettings] = React.useState<Settings>({ theme: "dark", telemetry_refresh_seconds: 5 });
  const [error, setError] = React.useState(false);
  const [preferencesOpen, setPreferencesOpen] = React.useState(false);
  const [settingsReady, setSettingsReady] = React.useState(false);
  const [settingsError, setSettingsError] = React.useState(false);
  const [, refreshLanguage] = React.useReducer((count: number) => count + 1, 0);
  const [saving, setSaving] = React.useState(false);
  const [message, setMessage] = React.useState("");
  const [selectedModelId, setSelectedModelId] = React.useState(() => {
    try { return window.localStorage.getItem("workstation-selected-model") || "gemma-4-12b"; }
    catch { return "gemma-4-12b"; }
  });
  const [modelSwitchRevision, setModelSwitchRevision] = React.useState(0);
  const [llmModels, setLlmModels] = React.useState<GemmaState[]>([]);
  const [modelFetchError, setModelFetchError] = React.useState(false);
  const [modelBusy, setModelBusy] = React.useState(false);
  const [modelNotice, setModelNotice] = React.useState("");
  const [assistantAsking, setAssistantAsking] = React.useState(false);
  const [codeAsking, setCodeAsking] = React.useState(false);
  const modelRequestActive = assistantAsking || codeAsking;
  const activeModelId = selectedModelId;
  const activeModel = llmModels.find(model => model.model_id === activeModelId) ?? { state: modelFetchError ? "UNAVAILABLE" : "UNKNOWN", model_id: activeModelId };

  const refreshModels = React.useCallback(async () => {
    try {
      const result = await responseJson(await fetch("/api/v1/llm/models"));
      const models = Array.isArray(result.models) ? result.models as GemmaState[] : [];
      setLlmModels(models);
      setModelFetchError(false);
    } catch { setModelFetchError(true); }
  }, []);
  React.useEffect(() => {
    void refreshModels();
    const timer = window.setInterval(() => void refreshModels(), 5000);
    return () => window.clearInterval(timer);
  }, [refreshModels]);
  React.useEffect(() => {
    try { window.localStorage.setItem("workstation-selected-model", selectedModelId); }
    catch { /* Persisting a UI preference is optional. */ }
  }, [selectedModelId]);
  React.useEffect(() => {
    if (llmModels.length && !llmModels.some(model => model.model_id === selectedModelId)) {
      setSelectedModelId(llmModels[0].model_id ?? "gemma-4-12b");
    }
  }, [llmModels, selectedModelId]);
  const chooseSidebarModel = (modelId: string) => {
    if (modelBusy || modelRequestActive || modelId === selectedModelId) return;
    if (!llmModels.some(model => model.model_id === modelId)) return;
    setSelectedModelId(modelId);
    setModelSwitchRevision(current => current + 1);
    setModelNotice("");
  };
  const changeSidebarModelRuntime = async (action: "start" | "stop") => {
    if (modelBusy || modelRequestActive) return;
    setModelBusy(true); setModelNotice("");
    try {
      await sendJson(`/api/v1/llm/${encodeURIComponent(activeModelId)}/${action}`, "POST", {});
      setModelNotice(action === "start" ? tr.gemmaReady : tr.gemmaStopped);
    } catch (reason) {
      setModelNotice(reason instanceof Error ? reason.message : tr.requestFailed);
    } finally {
      await refreshModels();
      setModelBusy(false);
    }
  };

  React.useEffect(() => {
    let live = true;
    void fetch("/api/v1/settings", { headers: { Accept: "application/json" } })
      .then(responseJson).then(value => { if (live) { setSettings(value as unknown as Settings); setSettingsError(false); setSettingsReady(true); } })
      .catch(() => { if (live) setSettingsError(true); });
    return () => { live = false; };
  }, []);

  React.useEffect(() => {
    document.documentElement.dataset.theme = settings.theme;
    try { window.localStorage.setItem("ai-workstation-theme", settings.theme); } catch { /* SQLite remains the source of truth. */ }
  }, [settings.theme]);

  React.useEffect(() => {
    let live = true;
    const refresh = async () => {
      try {
        const response = await fetch("/api/v1/hardware", { headers: { Accept: "application/json" } });
        if (!response.ok) throw new Error("backend error");
        const data = await response.json() as Hardware;
        if (live) { setHardware(data); setError(false); }
      } catch { if (live) setError(true); }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), settings.telemetry_refresh_seconds * 1000);
    return () => { live = false; window.clearInterval(timer); };
  }, [settings.telemetry_refresh_seconds]);

  const saveSetting = async <K extends keyof Settings>(key: K, value: Settings[K]) => {
    if (saving || !settingsReady) return;
    const previous = settings;
    setSettings(current => ({ ...current, [key]: value }));
    setSaving(true); setMessage("");
    try {
      const saved = await sendJson(`/api/v1/settings/${key}`, "PUT", { value });
      setSettings(saved as unknown as Settings);
      setMessage(t("Kaydedildi"));
    } catch (reason) {
      setSettings(previous);
      setMessage(reason instanceof Error ? reason.message : tr.requestFailed);
    } finally { setSaving(false); }
  };

  const gpu = hardware?.gpus[0];

  const navigation: Array<{pageKey: Page; label: string; icon: IconName}> = [
    {pageKey: "assistant", label: tr.navigation[1], icon: "chat"},
    {pageKey: "image", label: tr.navigation[3], icon: "image"},
    {pageKey: "audio", label: t("Ses"), icon: "audio"},
    {pageKey: "code", label: tr.navigation[2], icon: "code"},
    {pageKey: "models", label: tr.modelManagement, icon: "models"},
  ];
  const pageTitle = page === "assistant" ? tr.navigation[1] : page === "code" ? tr.navigation[2] : page === "image" ? tr.navigation[3] : page === "audio" ? t("Ses") : tr.modelManagement;

  return <div className={`shell${sidebarCollapsed ? " shell--compact" : ""}`}>
    <a className="skip-link" href="#main-content">{t("İçeriğe geç")}</a>
    <AppSidebar
      onOpenPreferences={() => { setMobileSidebarOpen(false); setPreferencesOpen(true); }}
      navigation={navigation}
      currentPage={page}
      onNavigate={setPage}
      collapsed={sidebarCollapsed}
      onToggleCollapsed={() => setSidebarCollapsed(value => !value)}
      mobileOpen={mobileSidebarOpen}
      onCloseMobile={closeMobileSidebar}
      modelId={activeModelId}
      models={llmModels}
      status={activeModel}
      modelDisabled={modelBusy || modelRequestActive}
      modelBusy={modelBusy}
      modelNotice={modelNotice}
      onModelChange={chooseSidebarModel}
      onModelStart={() => void changeSidebarModelRuntime("start")}
      onModelStop={() => void changeSidebarModelRuntime("stop")}
      gpuUsed={gpu?.vram_used_bytes}
      gpuTotal={gpu?.vram_total_bytes}
    />
    <main className="main" id="main-content" tabIndex={-1}>
      <AppHeader
        title={pageTitle}
        isOffline={error}
        hasHardware={Boolean(hardware)}
        onLanguageChange={refreshLanguage}
        onOpenMobile={() => setMobileSidebarOpen(true)}
      />
      {error && <section className="notice error-panel"><strong>{tr.backendOffline}</strong><p>{tr.backendHelp}</p></section>}
      {visited.has("assistant") && <div className="workspace-page" hidden={page !== "assistant"}><ChatWorkspace isActive={page === "assistant"} modelId={selectedModelId} model={activeModel} onModelChange={setSelectedModelId} modelSwitchRevision={modelSwitchRevision} onActivityChange={setAssistantAsking} onRefreshModels={refreshModels} /></div>}
      {visited.has("code") && <div className="workspace-page" hidden={page !== "code"}><CodeWorkspace isActive={page === "code"} modelId={selectedModelId} model={activeModel} modelSwitchRevision={modelSwitchRevision} onModelChange={setSelectedModelId} onActivityChange={setCodeAsking} onRefreshModels={refreshModels} /></div>}
      {visited.has("image") && <div className="workspace-page" hidden={page !== "image"}><ImageWorkspace /></div>}
      {visited.has("audio") && <div className="workspace-page" hidden={page !== "audio"}><AudioWorkspace isActive={page === "audio"}/></div>}
      {visited.has("models") && <div className="workspace-page" hidden={page !== "models"}><ModelInventory active={page === "models"} /></div>}
    </main>
    <SystemPreferences open={preferencesOpen} onClose={() => setPreferencesOpen(false)} settings={settings} settingsReady={settingsReady} settingsError={settingsError} hardware={hardware} hardwareError={error} saving={saving} message={message} onChange={saveSetting} />
  </div>;
}
