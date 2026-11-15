import React from "react";
import { t, tr } from "../i18n";
import { Icon, type IconName } from "./Icon";
import { LanguageMenu } from "./LanguageMenu";
import { SidebarModel } from "./SidebarModel";
import { StatusPill } from "./ui/Primitives";
import { formatBytes, type GemmaState } from "../lib/shared";

type NavPage = "assistant" | "code" | "image" | "audio" | "models";
export type NavItem = { pageKey: NavPage; label: string; icon: IconName };

type SidebarProps = {
  onOpenPreferences: () => void;
  navigation: NavItem[];
  currentPage: NavPage;
  onNavigate: (page: NavPage) => void;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
  modelId: string;
  models: GemmaState[];
  status: GemmaState;
  modelDisabled: boolean;
  modelBusy: boolean;
  modelNotice: string;
  onModelChange: (id: string) => void;
  onModelStart: () => void;
  onModelStop: () => void;
  gpuUsed: number | null | undefined;
  gpuTotal: number | null | undefined;
};

/** Navigational chrome never unmounts page workspaces: it only changes their visibility. */
export function AppSidebar(props: SidebarProps) {
  const { navigation, currentPage, onNavigate, collapsed, onToggleCollapsed, mobileOpen, onCloseMobile } = props;
  const gpuFraction = props.gpuUsed != null && props.gpuTotal ? Math.min(1, Math.max(0, props.gpuUsed / props.gpuTotal)) : null;
  const firstNav = React.useRef<HTMLButtonElement>(null);
  React.useEffect(() => {
    if (!mobileOpen || !window.matchMedia("(max-width: 800px)").matches) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    firstNav.current?.focus();
    return () => { document.body.style.overflow = previousOverflow; };
  }, [mobileOpen]);
  const link = (item: NavItem) => <button
    key={item.pageKey}
    ref={item.pageKey === "assistant" ? firstNav : undefined}
    type="button"
    className={`nav-item${item.pageKey === currentPage ? " active" : ""}`}
    aria-current={item.pageKey === currentPage ? "page" : undefined}
    aria-label={item.label}
    title={collapsed ? item.label : undefined}
    onClick={() => { onNavigate(item.pageKey); onCloseMobile(); }}
  >
    <span className="nav-icon"><Icon name={item.icon} size={19} /></span>
    <span className="nav-label">{item.label}</span>
  </button>;

  return <>
    <button type="button" className={`sidebar-scrim${mobileOpen ? " sidebar-scrim--visible" : ""}`} onClick={onCloseMobile} aria-label={t("Menüyü kapat")} tabIndex={mobileOpen ? 0 : -1}/>
    <aside className={`sidebar${collapsed ? " sidebar--collapsed" : ""}${mobileOpen ? " sidebar--mobile-open" : ""}`} aria-label={tr.mainMenu}>
      <div className="sidebar-header">
        <div className="brand" aria-label="Local AI Workstation">
          <span className="brand-mark"><Icon name="sparkles" size={23} /></span>
          <span className="brand-copy"><strong>Local AI</strong><small>WORKSTATION</small></span>
        </div>
        <button className="sidebar-collapse-toggle" type="button" onClick={onToggleCollapsed} title={collapsed ? t("Menüyü genişlet") : t("Menüyü daralt")} aria-label={collapsed ? t("Menüyü genişlet") : t("Menüyü daralt")} aria-expanded={!collapsed}>
          <Icon name={collapsed ? "panel-left-open" : "panel-left-close"} size={19}/>
        </button>
        <button className="sidebar-mobile-close" type="button" onClick={onCloseMobile} aria-label={t("Menüyü kapat")}><Icon name="x" size={20}/></button>
      </div>
      <div className="sidebar-navigation">
        <div className="sidebar-group">
          <span className="sidebar-group-label">{tr.workspace}</span>
          <nav aria-label={tr.workspace}>{navigation.filter(item => item.pageKey !== "models").map(link)}</nav>
        </div>
        <div className="sidebar-group sidebar-group-management">
          <span className="sidebar-group-label">{tr.systemStatus}</span>
          <nav aria-label={tr.systemStatus}>{navigation.filter(item => item.pageKey === "models").map(link)}</nav>
        </div>
      </div>
      <div className="sidebar-utilities">
        <div hidden={currentPage === "image" || currentPage === "audio"}><SidebarModel
          modelId={props.modelId} models={props.models} status={props.status}
          disabled={props.modelDisabled}
          busy={props.modelBusy} notice={props.modelNotice}
          onChange={props.onModelChange} onStart={props.onModelStart} onStop={props.onModelStop}
        /></div>
        <div id="sidebar-audio-controls" hidden={currentPage !== "audio"} />
        <div id="sidebar-image-controls" hidden={currentPage !== "image"} />
        <div className="sidebar-bottom">
          {gpuFraction !== null && <div className="vram-card">
            <div className="vram-row"><span><Icon name="cpu" size={15} /> {tr.gpuMemory}</span><span>{formatBytes(props.gpuUsed)} / {formatBytes(props.gpuTotal)}</span></div>
            <div className="vram-bar" role="progressbar" aria-label={tr.gpuMemory} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(gpuFraction * 100)}><i style={{transform:`scaleX(${gpuFraction})`}} /></div>
          </div>}
          <div className="sidebar-foot"><Icon name="shield" size={16} /><span>{tr.localOnly}</span><span className="local-dot" /></div>
        </div>
      </div>
      <button type="button" className="sidebar-preferences" onClick={props.onOpenPreferences} aria-label={t("Sistem ve Tercihler")} title={t("Sistem ve Tercihler")}><Icon name="settings" size={19}/><span>{t("Sistem ve Tercihler")}</span></button>
    </aside>
  </>;
}

export function AppHeader({ title, isOffline, hasHardware, onLanguageChange, onOpenMobile }: {
  title: string;
  isOffline: boolean;
  hasHardware: boolean;
  onLanguageChange: () => void;
  onOpenMobile: () => void;
}) {
  React.useEffect(() => { document.title = `${title} · ${tr.appName}`; }, [title, tr.appName]);
  return <header className="topbar">
    <div className="topbar-heading">
      <div className="topbar-title-row">
        <button type="button" className="mobile-menu-toggle" aria-label={t("Ana menüyü aç")} onClick={onOpenMobile}><Icon name="menu" size={21} /></button>
        <div>
          <div className="topbar-breadcrumb"><span>{tr.workspace}</span><Icon name="chevron-right" size={13} /><span>{title}</span></div>
          <h1>{title}</h1>
        </div>
      </div>
    </div>
    <div className="topbar-actions">
      <StatusPill tone={isOffline ? "danger" : !hasHardware ? "warning" : "success"} role="status" className="topbar-backend">
        {isOffline ? tr.backendOffline : hasHardware ? tr.backendConnected : tr.loading}
      </StatusPill>
      <LanguageMenu onChange={onLanguageChange} />
    </div>
  </header>;
}
