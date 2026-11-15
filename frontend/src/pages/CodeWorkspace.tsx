import React from "react";
import { t, formatNumber, localizeMessage, tr } from "../i18n";
import { Icon } from "../components/Icon";
import { AutoGrowTextarea } from "../components/ui/AutoGrowTextarea";
import { responseJson, sendJson, streamConversation, ChatStreamError, MessageTranscript, ChatCompletionNotice, copyText, type GemmaState, type Conversation, type ChatMessage } from "../lib/shared";
type Project = { id: string; name: string; root_path: string };
type ProjectEntry = { name: string; path: string; kind: "directory" | "file" };
type EditProposal = { id: string; path: string; diff: string; creates_file: boolean };
function clampPanelWidth(stored: string | null, fallback: number, min: number, max: number): number {
  const value = stored == null ? fallback : Number(stored);
  return Number.isFinite(value) && value >= min && value <= max ? value : Math.min(max, Math.max(min, Number.isFinite(value) ? value : fallback));
}
export function CodeWorkspace({ isActive, modelId, model, modelSwitchRevision, onModelChange, onActivityChange, onRefreshModels }: {
  isActive: boolean; modelId: string; model: GemmaState; modelSwitchRevision: number;
  onModelChange: (modelId: string) => void;
  onActivityChange: (active: boolean) => void; onRefreshModels: () => Promise<void>;
}) {
  const [projects, setProjects] = React.useState<Project[]>([]);
  const [active, setActive] = React.useState<Project | null>(null);
  const [rootPath, setRootPath] = React.useState("");
  const [folderName, setFolderName] = React.useState("");
  const [entries, setEntries] = React.useState<ProjectEntry[]>([]);
  const [directory, setDirectory] = React.useState(".");
  const [filePath, setFilePath] = React.useState("");
  const [content, setContent] = React.useState("");
  const [proposal, setProposal] = React.useState<EditProposal | null>(null);
  const [overwriteConfirmed, setOverwriteConfirmed] = React.useState(false);
  const [conversations, setConversations] = React.useState<Conversation[]>([]);
  const [conversationId, setConversationId] = React.useState("");
  const [conversationTitle, setConversationTitle] = React.useState("");
  const [messages, setMessages] = React.useState<ChatMessage[]>([]);
  const [question, setQuestion] = React.useState("");
  const [asking, setAsking] = React.useState(false);
  const [pendingUser, setPendingUser] = React.useState("");
  const [partialAnswer, setPartialAnswer] = React.useState<string | undefined>(undefined);
  const [omitted, setOmitted] = React.useState(0);
  React.useEffect(() => { setOmitted(0); }, [conversationId]);
  const [lastSpeed, setLastSpeed] = React.useState<number | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [message, setMessage] = React.useState("");
  const [fileSearch, setFileSearch] = React.useState("");
  const [explorerWidth, setExplorerWidth] = React.useState(() => clampPanelWidth(localStorage.getItem("code-explorer-width"), 250, 230, 360));
  // Upgrade old narrow layouts once; keep any wider user-customized setting.
  const [assistantWidth, setAssistantWidth] = React.useState(() => {
    const latest = localStorage.getItem("code-assistant-width-v22");
    if (latest !== null) return clampPanelWidth(latest, 510, 470, 650);
    const legacy = localStorage.getItem("code-assistant-width");
    return legacy === null || Number(legacy) <= 460 ? 510 : clampPanelWidth(legacy, 510, 470, 650);
  });
  const [editorScroll, setEditorScroll] = React.useState(0);
  const codeGridRef = React.useRef<HTMLElement>(null);
  const previousRevision = React.useRef(modelSwitchRevision);
  React.useEffect(() => {
    if (previousRevision.current === modelSwitchRevision) return;
    previousRevision.current = modelSwitchRevision;
    if (isActive) { setConversationId(""); setMessages([]); setConversationTitle(""); setLastSpeed(null); setOmitted(0); }
  }, [modelSwitchRevision, isActive]);
  React.useEffect(() => { localStorage.setItem("code-explorer-width", String(explorerWidth)); }, [explorerWidth]);
  React.useEffect(() => { localStorage.setItem("code-assistant-width-v22", String(assistantWidth)); }, [assistantWidth]);
  const startResize = (edge: "explorer" | "assistant") => (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || !codeGridRef.current) return;
    const grid = codeGridRef.current;
    const box = grid.getBoundingClientRect();
    const handle = event.currentTarget;
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    handle.setPointerCapture(event.pointerId);
    document.body.style.cursor = "col-resize"; document.body.style.userSelect = "none";
    const move = (next: PointerEvent) => {
      // Never allow a resize to swallow the code editor or the adjacent pane.
      const minimumEditor = 380;
      const separators = 16;
      if (edge === "explorer") {
        // In the two-row layout the assistant does not consume horizontal space.
        const available = box.width < 1200 ? 360 : Math.min(360, box.width - assistantWidth - minimumEditor - separators);
        setExplorerWidth(Math.max(230, Math.min(available, next.clientX - box.left)));
      } else {
        const available = Math.min(650, box.width - explorerWidth - minimumEditor - separators);
        setAssistantWidth(Math.max(470, Math.min(available, box.right - next.clientX)));
      }
    };
    const finish = () => {
      document.body.style.cursor = previousCursor; document.body.style.userSelect = previousUserSelect;
      handle.removeEventListener("pointermove", move); handle.removeEventListener("pointerup", finish);
      handle.removeEventListener("pointercancel", finish);
      if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
    };
    handle.addEventListener("pointermove", move); handle.addEventListener("pointerup", finish);
    handle.addEventListener("pointercancel", finish);
  };
  const filteredEntries = entries.filter(entry => entry.name.toLocaleLowerCase("tr").includes(fileSearch.toLocaleLowerCase("tr")));
  const quickFiles = entries.filter(entry => entry.kind === "file" && /\.(md|txt|json|ya?ml|[jt]sx?|py|rs|go|dart|sh|css|html)$/i.test(entry.name)).slice(0, 4);
  const codeLineCount = content.split("\n").length;

  const loadProjects = React.useCallback(async () => {
    const result = await responseJson(await fetch("/api/v1/projects"));
    setProjects(result.projects as Project[]);
  }, []);

  React.useEffect(() => { void loadProjects().catch(reason => setMessage(reason instanceof Error ? reason.message : tr.requestFailed)); }, [loadProjects]);
  React.useEffect(() => { if (!active && projects[0]) setActive(projects[0]); }, [active, projects]);
  const loadConversations = React.useCallback(async () => {
    const result = await responseJson(await fetch("/api/v1/conversations?kind=code"));
    setConversations(result.conversations as Conversation[]);
  }, []);
  React.useEffect(() => { void loadConversations().catch(reason => setMessage(reason instanceof Error ? reason.message : tr.requestFailed)); }, [loadConversations]);
  React.useEffect(() => {
    if (asking) return;
    if (!conversationId) { setMessages([]); setConversationTitle(""); return; }
    let live = true;
    void fetch(`/api/v1/conversations/${encodeURIComponent(conversationId)}`).then(responseJson).then(result => {
      if (!live) return;
      const conversation = result.conversation as Conversation;
      if (conversation.kind !== "code") throw new Error(tr.invalidResponse);
      setConversationTitle(conversation.title); if (isActive) onModelChange(conversation.model_id);
      setMessages(result.messages as ChatMessage[]);
    }).catch(reason => { if (live) setMessage(reason instanceof Error ? reason.message : tr.requestFailed); });
    return () => { live = false; };
  }, [conversationId, asking, isActive, onModelChange]);
  React.useEffect(() => { onActivityChange(asking); }, [asking, onActivityChange]);
  React.useEffect(() => {
    if (!active) { setEntries([]); return; }
    let live = true;
    void fetch(`/api/v1/projects/${encodeURIComponent(active.id)}/tree?path=${encodeURIComponent(directory)}`)
      .then(responseJson).then(result => { if (live) setEntries(result.entries as ProjectEntry[]); })
      .catch(reason => { if (live) setMessage(reason instanceof Error ? reason.message : tr.requestFailed); });
    return () => { live = false; };
  }, [active, directory]);

  const register = async () => {
    setBusy(true); setMessage("");
    try {
      const created = await sendJson("/api/v1/projects", "POST", { path: rootPath, ...(folderName ? { name: folderName } : {}) }) as unknown as Project;
      setActive(created); setDirectory("."); setFilePath(""); setContent(""); setProposal(null);
      await loadProjects(); setMessage(tr.projectAdded);
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : tr.requestFailed); }
    finally { setBusy(false); }
  };

  const pickFolder = async () => {
    setBusy(true); setMessage("");
    try {
      const result = await sendJson("/api/v1/projects/pick", "POST", {});
      if (result.cancelled === true) { setMessage(tr.folderPickCancelled); return; }
      const chosen = result.project as Project | undefined;
      if (!chosen) throw new Error(tr.invalidResponse);
      setRootPath(chosen.root_path); setFolderName(chosen.name); setActive(chosen);
      setDirectory("."); setFilePath(""); setContent(""); setProposal(null);
      await loadProjects(); setMessage(result.already_registered ? tr.projectAlreadyAdded : tr.projectAdded);
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : tr.requestFailed); }
    finally { setBusy(false); }
  };

  const openFile = async (path: string) => {
    if (!active) return;
    setBusy(true); setMessage(""); setProposal(null);
    try {
      const result = await responseJson(await fetch(`/api/v1/projects/${encodeURIComponent(active.id)}/file?path=${encodeURIComponent(path)}`));
      setFilePath(path); setContent(String(result.content));
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : tr.requestFailed); }
    finally { setBusy(false); }
  };

  const previewDiff = async () => {
    if (!active || !filePath) return;
    setBusy(true); setMessage(""); setOverwriteConfirmed(false);
    try {
      const result = await sendJson(`/api/v1/projects/${encodeURIComponent(active.id)}/proposals`, "POST", { path: filePath, content }) as unknown as EditProposal;
      setProposal(result); setMessage(tr.diffReady);
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : tr.requestFailed); }
    finally { setBusy(false); }
  };

  const applyDiff = async () => {
    if (!proposal) return;
    setBusy(true); setMessage("");
    try {
      await sendJson(`/api/v1/proposals/${encodeURIComponent(proposal.id)}/apply`, "POST", {
        approved: true,
        ...(proposal.creates_file ? {} : { overwrite_approved: overwriteConfirmed }),
      });
      setProposal(null); setMessage(tr.editApplied);
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : tr.requestFailed); }
    finally { setBusy(false); }
  };

  const cancelResponse = async () => {
    setBusy(true);
    try { await sendJson(`/api/v1/llm/${encodeURIComponent(modelId)}/cancel`, "POST", {}); }
    catch (reason) { setMessage(reason instanceof Error ? reason.message : tr.requestFailed); }
    finally { setBusy(false); }
  };
  const askModel = async (continuation = false) => {
    if ((!continuation && !question.trim()) || model.state !== "RUNNING" || !model.managed || asking || (continuation && (!conversationId || messages.at(-1)?.finish_reason !== "length"))) return;
    setAsking(true); setMessage("");
    try {
      let selectedConversation = conversationId;
      if (!selectedConversation) {
        const created = await sendJson("/api/v1/conversations", "POST", { title: tr.newConversation, auto_title: true, kind: "code", model_id: modelId }) as unknown as Conversation;
        selectedConversation = created.id; setConversationId(created.id); setConversationTitle(created.title);
        await loadConversations();
      }
      setPendingUser(continuation ? "" : question); setPartialAnswer("");
      const result = await streamConversation(selectedConversation, continuation ? { continue: true } : {
        content: question,
        ...(active && filePath ? { project_id: active.id, context_path: filePath, context_content: content } : {}),
      }, fragment => setPartialAnswer(current => (current ?? "") + fragment));
      setMessages(result.messages); setLastSpeed(result.tokens_per_second); setOmitted(result.omitted_messages);
      setConversationTitle(result.conversation.title);
      if (!continuation) setQuestion(""); await loadConversations();
    } catch (reason) {
      if (reason instanceof ChatStreamError && reason.code === "cancelled") setMessage(tr.responseCancelled);
      else setMessage(reason instanceof Error ? reason.message : tr.requestFailed);
      await onRefreshModels();
    } finally { setAsking(false); setPendingUser(""); setPartialAnswer(undefined); }
  };

  const newConversation = async () => {
    try {
      const created = await sendJson("/api/v1/conversations", "POST", { title: tr.newConversation, auto_title: true, kind: "code", model_id: modelId }) as unknown as Conversation;
      setConversations(current => [created, ...current]); setConversationId(created.id);
      setConversationTitle(created.title); setMessages([]); setQuestion(""); setMessage("");
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : tr.requestFailed); }
  };

  const renameConversation = async () => {
    if (!conversationId) return;
    try {
      const renamed = await sendJson(`/api/v1/conversations/${encodeURIComponent(conversationId)}`, "PATCH", { title: conversationTitle }) as unknown as Conversation;
      setConversationTitle(renamed.title); await loadConversations(); setMessage(tr.conversationRenamed);
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : tr.requestFailed); }
  };

  const deleteConversation = async () => {
    if (!conversationId || !window.confirm(tr.confirmDeleteConversation)) return;
    try {
      await sendJson(`/api/v1/conversations/${encodeURIComponent(conversationId)}`, "DELETE", {});
      const remaining = conversations.filter(item => item.id !== conversationId);
      setConversations(remaining); setConversationId(remaining[0]?.id ?? "");
      setMessages([]); setConversationTitle(""); setMessage(tr.conversationDeleted);
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : tr.requestFailed); }
  };

  return <div className="code-workspace code-workspace-v2">
    <section className="panel project-panel code-toolbar" aria-label={t("Proje araçları")}>
      <span className="code-toolbar-title"><Icon name="folder" size={16} /> {" "}{t("Çalışma alanı")}</span>
      {active && <div className="code-toolbar-pick"><button className="secondary-button" type="button" disabled={busy} onClick={() => void pickFolder()}>{tr.chooseFolder}</button></div>}
      <details className="code-manual"><summary>{tr.folderPath}</summary><p className="small-note">{tr.folderPathHelp}</p>
      <div className="project-add"><label>{tr.folderPath}<span className="path-picker"><input value={rootPath} onChange={event => setRootPath(event.target.value)} placeholder="/home/kullanici/projem" autoComplete="off" /><button className="secondary-button" type="button" disabled={busy} onClick={() => void pickFolder()}>{tr.chooseFolder}</button></span></label><label>{tr.projectName}<input value={folderName} onChange={event => setFolderName(event.target.value)} placeholder={tr.optional} maxLength={120} /></label><button className="primary-button" type="button" disabled={busy || !rootPath} onClick={() => void register()}>{tr.addFolder}</button></div></details>
      {projects.length > 0 && <label className="project-select-label">{tr.selectedProject}<select value={active?.id ?? ""} onChange={event => { setActive(projects.find(project => project.id === event.target.value) ?? null); setDirectory("."); setFilePath(""); setContent(""); setProposal(null); }}><option value="">{tr.chooseProject}</option>{projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>}

    </section>
    {active && <section className="code-grid" ref={codeGridRef} style={{ "--explorer-width": `${explorerWidth}px`, "--assistant-width": `${assistantWidth}px` } as React.CSSProperties}>
      <article className="panel file-panel"><div className="panel-head"><div><span className="eyebrow">{active.name}</span><h2><Icon name="folder" size={17}/> {" "}{t("Dosyalar")}{" "}<span className="code-file-count">{filteredEntries.length}</span></h2></div></div>
        <label className="code-file-search"><Icon name="search" size={16}/><input aria-label="Dosya ara" placeholder={t("Bu klasörde ara...")} value={fileSearch} onChange={event => setFileSearch(event.target.value)}/></label>
        <div className="file-breadcrumb"><Icon name="folder" size={13}/><code title={directory}>{directory === "." ? active.name : directory}</code>{directory !== "." && <button type="button" className="text-button" onClick={() => { setDirectory(directory.includes("/") ? directory.slice(0, directory.lastIndexOf("/")) : "."); setFileSearch(""); }}>{tr.parentFolder}</button>}</div>
        <ul className="file-list">{filteredEntries.map(entry => <li key={entry.path}><button className={entry.path === filePath ? "selected" : ""} title={entry.path} aria-current={entry.path === filePath ? "true" : undefined} type="button" onClick={() => entry.kind === "directory" ? (setDirectory(entry.path), setFileSearch("")) : void openFile(entry.path)}><Icon name={entry.kind === "directory" ? "folder" : "file"} size={16}/><span className="file-entry-label">{entry.name}</span>{entry.kind === "directory" && <Icon name="chevron-right" size={14}/>}</button></li>)}{filteredEntries.length === 0 && <li className="muted">{fileSearch ? t("Eşleşen dosya bulunamadı.") : tr.emptyFolder}</li>}</ul>
      </article>
      <div className="code-resizer code-resizer-left" role="separator" aria-orientation="vertical" aria-label={t("Dosya gezgini genişliği")} aria-valuemin={230} aria-valuemax={360} aria-valuenow={explorerWidth} title={t("Sürükleyerek ayarlayın · Çift tıklayarak sıfırlayın")} tabIndex={0} onDoubleClick={() => setExplorerWidth(250)} onPointerDown={startResize("explorer")} onKeyDown={event => { if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); setExplorerWidth(value => Math.max(230, Math.min(360, value + (event.key === "ArrowRight" ? 20 : -20)))); } }} />
      <article className="panel editor-panel"><div className="panel-head"><div><span className="eyebrow">{filePath ? tr.fileReview : t("EDİTÖR")}</span><h2>{filePath ? <><Icon name="file" size={16}/> {filePath}</> : t("Kod editörü")}</h2></div><span className="badge muted-badge">{tr.localOnly}</span></div>
        {filePath ? <><div className="code-editor-frame"><pre className="code-line-numbers" aria-hidden="true" style={{ transform: `translateY(-${editorScroll}px)` }}>{Array.from({length: codeLineCount}, (_, index) => index + 1).join("\n")}</pre><textarea className="code-editor" aria-label={tr.fileContents} value={content} onScroll={event => setEditorScroll(event.currentTarget.scrollTop)} onChange={event => { setContent(event.target.value); setProposal(null); }} spellCheck={false} /></div>
          <div className="code-editor-footer"><span>{codeLineCount} {" "}{t("satır · Değişiklikler önce önizlenir")}</span><button className="primary-button" type="button" disabled={busy} onClick={() => void previewDiff()}>{tr.previewDiff}</button></div>
        </> : <div className="code-editor-empty"><div className="code-editor-empty-icon"><Icon name="code" size={27}/></div><span className="empty-overline">{active.name}</span><h3>{t("Kodunuza odaklanın.")}</h3><p>{t("Soldan bir dosya açın. İnceleyin, düzenleyin ve sağdaki asistana sorularınızı sorun.")}</p><div className="code-empty-steps"><span><b>01</b> {" "}{t("Dosyayı aç")}</span><span><b>02</b> {" "}{t("Birlikte geliştir")}</span><span><b>03</b> {" "}{t("Farkı incele")}</span></div>{quickFiles.length > 0 && <div className="code-quick-files" aria-label={t("Hızlı dosya aç")}><strong>{t("Hızlı aç")}</strong><div>{quickFiles.map(item => <button type="button" key={item.path} disabled={busy} onClick={() => void openFile(item.path)} title={item.path}><Icon name="file" size={15} />{item.name}</button>)}</div></div>}</div>}
        {proposal && <div className="diff-review"><div className="panel-head"><div><span className="eyebrow">{tr.reviewBeforeApply}</span><h3>{proposal.path}</h3></div></div><pre className="diff-content">{proposal.diff || tr.noChanges}</pre>
          {!proposal.creates_file && <label className="confirm-overwrite"><input type="checkbox" checked={overwriteConfirmed} onChange={event => setOverwriteConfirmed(event.target.checked)} />{tr.confirmOverwrite}</label>}
          <button className="primary-button" type="button" disabled={busy || (!proposal.creates_file && !overwriteConfirmed)} onClick={() => void applyDiff()}>{tr.applyApprovedDiff}</button>
        </div>}
        </article>
      <div className="code-resizer code-resizer-right" role="separator" aria-orientation="vertical" aria-label={t("Asistan paneli genişliği")} aria-valuemin={470} aria-valuemax={650} aria-valuenow={assistantWidth} title={t("Sürükleyerek ayarlayın · Çift tıklayarak sıfırlayın")} tabIndex={0} onDoubleClick={() => setAssistantWidth(510)} onPointerDown={startResize("assistant")} onKeyDown={event => { if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); setAssistantWidth(value => Math.max(470, Math.min(650, value + (event.key === "ArrowLeft" ? 20 : -20)))); } }} />
      <article className="panel chat-panel"><div className="panel-head"><h2><Icon name="sparkles" size={18}/> {" "}{t("AI Kod Asistanı")}</h2><span className={`code-chat-status${model.state === "RUNNING" && model.managed ? " is-ready" : ""}`}><i aria-hidden="true" />{model.state === "RUNNING" && model.managed ? t("Hazır") : t("Kapalı")}</span></div><div className="gemma-chat">{filePath && <div className="code-context-chip" title={filePath}><Icon name="file" size={14}/> <span>{t("Dosya bağlamı:")}{" "}{filePath}</span></div>}<div className="conversation-toolbar"><label>{tr.conversationHistory}<select value={conversationId} disabled={asking} onChange={event => setConversationId(event.target.value)}><option value="">{tr.noConversationSelected}</option>{conversations.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label><button type="button" className="secondary-button" disabled={asking} onClick={() => void newConversation()}>{tr.newConversation}</button></div>
          {conversationId && <div className="conversation-edit"><input aria-label={tr.conversationTitle} value={conversationTitle} onChange={event => setConversationTitle(event.target.value)} maxLength={120} disabled={asking} /><button type="button" className="text-button" disabled={asking} onClick={() => void renameConversation()}>{tr.renameConversation}</button><button type="button" className="text-button danger-text" disabled={asking} onClick={() => void deleteConversation()}>{tr.deleteConversation}</button></div>}
          <MessageTranscript messages={messages} pendingUser={pendingUser || undefined} partialAnswer={partialAnswer} assistantLabel={model.model ?? "Yerel AI"} onCopy={value => void copyText(value, setMessage)} emptyState={<div className="code-chat-empty"><Icon name="sparkles" size={24}/><h3>{t("Birlikte geliştirelim")}</h3><p>{filePath ? t("Açık dosya sorunuza bağlam olarak eklenir. Nereden başlayalım?") : t("Bir dosya açın veya projeniz hakkında bir soru sorun.")}</p><div className="code-chat-actions">{filePath && <button type="button" onClick={() => setQuestion(t("Bu dosyanın işleyişini, önemli sınıf ve fonksiyonlarını açıklar mısın?"))}><Icon name="file" size={16}/><span>{t("Dosyayı açıkla")}<small>{t("Yapıyı ve işleyişi anlamlandır")}</small></span><Icon name="chevron-right" size={14}/></button>}{filePath && <button type="button" onClick={() => setQuestion(t("Bu dosyadaki olası hataları, güvenlik ve performans sorunlarını incele."))}><Icon name="search" size={16}/><span>{t("Hataları incele")}<small>{t("Olası sorunları birlikte bulalım")}</small></span><Icon name="chevron-right" size={14}/></button>}<button type="button" onClick={() => setQuestion(t("Bu projeyi geliştirmek için en değerli üç önerin nedir?"))}><Icon name="sparkles" size={16}/><span>{t("Geliştirme öner")}<small>{t("Proje için sonraki adımları belirle")}</small></span><Icon name="chevron-right" size={14}/></button></div></div>} />
          <ChatCompletionNotice messages={messages} busy={asking || !(model.state === "RUNNING" && !!model.managed)} omitted={omitted} onContinue={() => void askModel(true)} />
          <label className="sr-only" htmlFor="gemma-question">{t("Seçili modele sor")}</label><div className="code-chat-composer"><AutoGrowTextarea id="gemma-question" value={question} onChange={event => setQuestion(event.target.value)} onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void askModel(); } }} placeholder={t("Kod hakkında sorun, hata ayıklayın, değişiklik isteyin…")} rows={2} maxHeight={146} disabled={asking} />
          <div className="composer-bottom"><span className="composer-footnote">{model.state !== "RUNNING" || !model.managed ? t("Modeli sol menüden başlatın") : t("Enter gönder · Shift+Enter yeni satır")}{lastSpeed != null && <span className="composer-speed"> · {formatNumber(lastSpeed)} {tr.tokensPerSecond}</span>}</span>
          <div className="editor-actions">{asking && <button className="secondary-button" type="button" disabled={busy} title={tr.stopResponse} onClick={() => void cancelResponse()}>{tr.stopResponse}</button>}<button className="primary-button" type="button" disabled={asking || model.state !== "RUNNING" || !model.managed || !question.trim()} onClick={() => void askModel()}>{asking ? tr.gemmaThinking : t("Gönder")}<Icon name="arrow-up" size={16}/></button></div></div>
          </div>
        </div>
      </article>
    </section>}
    {!active && <section className="panel code-empty"><span className="code-empty-icon" aria-hidden="true">⌘</span><h2>{tr.chooseProject}</h2><p>{tr.addProjectFirst}</p><button className="primary-button" type="button" disabled={busy} onClick={() => void pickFolder()}>{tr.chooseFolder}</button></section>}
    {message && <p className="workspace-message" role="status">{localizeMessage(message)}</p>}
  </div>;
}
