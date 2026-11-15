import React from "react";
import { t, formatNumber, localizeMessage, tr } from "../i18n";
import { Icon } from "../components/Icon";
import { AutoGrowTextarea } from "../components/ui/AutoGrowTextarea";
import { responseJson, sendJson, streamConversation, ChatStreamError, MessageTranscript, ChatCompletionNotice, copyText, type GemmaState, type Conversation, type ChatMessage } from "../lib/shared";
type ChatWorkspaceProps = {
  isActive: boolean;
  modelId: string;
  model: GemmaState;
  modelSwitchRevision: number;
  onModelChange: (modelId: string) => void;
  onActivityChange: (active: boolean) => void;
  onRefreshModels: () => Promise<void>;
};
export function ChatWorkspace({ isActive, modelId, model: gemma, modelSwitchRevision, onModelChange, onActivityChange, onRefreshModels }: ChatWorkspaceProps) {
  const [conversations, setConversations] = React.useState<Conversation[]>([]);
  const [conversationId, setConversationId] = React.useState(() => localStorage.getItem("workstation-conversation") || "");
  const [conversationTitle, setConversationTitle] = React.useState("");
  const [messages, setMessages] = React.useState<ChatMessage[]>([]);
  const [question, setQuestion] = React.useState(() => localStorage.getItem("workstation-draft") || "");
  React.useEffect(() => { localStorage.setItem("workstation-draft", question); }, [question]);
  React.useEffect(() => { localStorage.setItem("workstation-conversation", conversationId); }, [conversationId]);
  const [asking, setAsking] = React.useState(false);
  const [pendingUser, setPendingUser] = React.useState("");
  const [partialAnswer, setPartialAnswer] = React.useState<string | undefined>(undefined);
  const [omitted, setOmitted] = React.useState(0);
  React.useEffect(() => { setOmitted(0); }, [conversationId]);
  const [lastSpeed, setLastSpeed] = React.useState<number | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [message, setMessage] = React.useState("");
  const [historySearch, setHistorySearch] = React.useState("");
  const ready = gemma.state === "RUNNING" && !!gemma.managed;
  const visibleConversations = conversations.filter(item => item.title.toLocaleLowerCase("tr").includes(historySearch.toLocaleLowerCase("tr")));

  const loadConversations = React.useCallback(async () => {
    const result = await responseJson(await fetch("/api/v1/conversations?kind=assistant"));
    setConversations(result.conversations as Conversation[]);
  }, []);
  React.useEffect(() => { onActivityChange(asking); }, [asking, onActivityChange]);
  const previousRevision = React.useRef(modelSwitchRevision);
  React.useEffect(() => {
    if (previousRevision.current === modelSwitchRevision) return;
    previousRevision.current = modelSwitchRevision;
    if (isActive) { setConversationId(""); setMessages([]); setConversationTitle(""); setLastSpeed(null); setOmitted(0); }
  }, [modelSwitchRevision, isActive]);
  React.useEffect(() => { void loadConversations().catch(reason => setMessage(reason instanceof Error ? reason.message : tr.requestFailed)); }, [loadConversations]);
  React.useEffect(() => {
    if (asking) return;
    if (!conversationId) { setMessages([]); setConversationTitle(""); return; }
    let live = true;
    void fetch(`/api/v1/conversations/${encodeURIComponent(conversationId)}`).then(responseJson).then(result => {
      if (!live) return;
      const conversation = result.conversation as Conversation;
      if (conversation.kind !== "assistant") throw new Error(tr.invalidResponse);
      setConversationTitle(conversation.title); if (isActive) onModelChange(conversation.model_id); setMessages(result.messages as ChatMessage[]);
    }).catch(reason => { if (live) setMessage(reason instanceof Error ? reason.message : tr.requestFailed); });
    return () => { live = false; };
  }, [conversationId, asking, onModelChange, isActive]);

  const cancelResponse = async () => {
    setBusy(true);
    try { await sendJson(`/api/v1/llm/${encodeURIComponent(modelId)}/cancel`, "POST", {}); }
    catch (reason) { setMessage(reason instanceof Error ? reason.message : tr.requestFailed); }
    finally { setBusy(false); }
  };
  const createConversation = async () => {
    try {
      const created = await sendJson("/api/v1/conversations", "POST", { title: tr.newConversation, auto_title: true, kind: "assistant", model_id: modelId }) as unknown as Conversation;
      setConversations(current => [created, ...current]); setConversationId(created.id); setConversationTitle(created.title); setMessages([]); setQuestion(""); setLastSpeed(null); setOmitted(0); setMessage("");
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
      setConversations(remaining); setConversationId(remaining[0]?.id ?? ""); setMessages([]); setConversationTitle(""); setMessage(tr.conversationDeleted);
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : tr.requestFailed); }
  };
  const sendMessage = async (continuation = false) => {
    if ((!continuation && !question.trim()) || asking || !ready || (continuation && (!conversationId || messages.at(-1)?.finish_reason !== "length"))) return;
    setAsking(true); setMessage(""); setPendingUser(continuation ? "" : question); setPartialAnswer("");
    try {
      let selected = conversationId;
      if (!selected) {
        const created = await sendJson("/api/v1/conversations", "POST", { title: tr.newConversation, auto_title: true, kind: "assistant", model_id: modelId }) as unknown as Conversation;
        selected = created.id; setConversationId(created.id); setConversationTitle(created.title); await loadConversations();
      }
      const result = await streamConversation(selected, continuation ? { continue: true } : { content: question }, part => setPartialAnswer(current => (current ?? "") + part));
      setMessages(result.messages); setConversationTitle(result.conversation.title); setLastSpeed(result.tokens_per_second); setOmitted(result.omitted_messages); if (!continuation) setQuestion(""); await loadConversations();
    } catch (reason) {
      if (reason instanceof ChatStreamError && reason.code === "cancelled") setMessage(tr.responseCancelled);
      else setMessage(reason instanceof Error ? reason.message : tr.requestFailed);
      await onRefreshModels();
    } finally { setAsking(false); setPendingUser(""); setPartialAnswer(undefined); }
  };
  const enterToSend = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void sendMessage(); }
  };

  return <section className="assistant-chat-layout">
    <aside className="panel chat-history"><div className="panel-head"><h2>{tr.conversationHistory}</h2><span className="history-count">{conversations.length}</span></div>
      <button type="button" className="primary-button" disabled={asking || busy} onClick={() => void createConversation()}><Icon name="plus" size={17} /> {tr.newConversation}</button>
      <label className="history-search"><Icon name="search" size={16}/><input aria-label={t("Sohbet geçmişinde ara")} placeholder={t("Sohbetlerde ara...")} value={historySearch} onChange={event => setHistorySearch(event.target.value)}/></label>
      <nav aria-label={tr.conversationHistory}>{visibleConversations.map(item => <button type="button" key={item.id} disabled={asking || busy} title={item.title} aria-current={conversationId === item.id ? "page" : undefined} className={`history-item${conversationId === item.id ? " active" : ""}`} onClick={() => setConversationId(item.id)}><strong>{item.title}</strong><small>{item.model_id} · {item.updated_at.slice(0, 10)}</small></button>)}</nav>
      {conversations.length === 0 && <p className="muted">{t("İlk sohbetiniz burada görünecek.")}</p>}
      {conversations.length > 0 && visibleConversations.length === 0 && <p className="muted">{t("Eşleşen sohbet bulunamadı.")}</p>}
    </aside>
    <article className="panel assistant-conversation-panel">
      <div className="conversation-model-indicator"><span className="model-indicator-icon"><Icon name="sparkles" size={16} /></span><div className="model-indicator-copy"><strong>{conversationTitle || t("Yeni sohbet")}</strong><span>{gemma.model ?? modelId}</span></div><span className={`model-state-pill${ready ? " is-ready" : ""}`}><i aria-hidden="true" />{ready ? t("Çalışıyor") : t("Model kapalı")}</span></div>
      {conversationId && <details className="conversation-options"><summary>{conversationTitle || tr.newConversation} {" "}{t("· Sohbet seçenekleri")}</summary><div className="conversation-edit"><input aria-label={tr.conversationTitle} value={conversationTitle} onChange={event => setConversationTitle(event.target.value)} maxLength={120} disabled={asking} /><button type="button" className="text-button" disabled={asking} onClick={() => void renameConversation()}>{tr.renameConversation}</button><button type="button" className="text-button danger-text" disabled={asking} onClick={() => void deleteConversation()}>{tr.deleteConversation}</button></div></details>}
      <MessageTranscript messages={messages} pendingUser={pendingUser || undefined} partialAnswer={partialAnswer} assistantLabel={gemma.model} onCopy={value => void copyText(value, setMessage)} emptyState={<div className="welcome-chat"><div className="welcome-emblem"><Icon name="sparkles" size={36} /></div><span className="welcome-eyebrow">{tr.localOnly}</span><h2>{t("Bugün neyi keşfediyoruz?")}</h2><p>{tr.assistantIntro}</p><div className="welcome-prompts"><button type="button" onClick={() => setQuestion(t("Bana bugün öğrenebileceğim ilginç bir konu öner."))}><Icon name="sparkles" size={16} /> {" "}{t("Yeni bir şey keşfet")}</button><button type="button" onClick={() => setQuestion(t("Bir proje fikrimi adım adım planlamama yardım et."))}><Icon name="layers" size={16} /> {" "}{t("Bir proje planla")}</button><button type="button" onClick={() => setQuestion(t("Karmaşık bir konuyu basit örneklerle açıkla."))}><Icon name="chat" size={16} /> {" "}{t("Bir konuyu açıkla")}</button></div></div>} />
      <ChatCompletionNotice messages={messages} busy={asking || !ready} omitted={omitted} onContinue={() => void sendMessage(true)} />
      <div className="chat-composer"><label className="sr-only" htmlFor="assistant-question">{tr.assistantQuestion}</label>
        <AutoGrowTextarea id="assistant-question" value={question} onChange={event => setQuestion(event.target.value)} onKeyDown={enterToSend} placeholder={tr.assistantPlaceholder} rows={2} maxHeight={154} disabled={asking} />
        <div className="composer-bottom"><span className="composer-footnote">{!ready ? t("Önce sol menüden modeli yükleyin") : tr.shiftEnterHint}{lastSpeed != null && <span className="composer-speed"> · {formatNumber(lastSpeed)} {tr.tokensPerSecond}</span>}</span>
          <div className="editor-actions">{asking && <button className="secondary-button" type="button" disabled={busy} onClick={() => void cancelResponse()}>{tr.stopResponse}</button>}<button className="primary-button send-button" type="button" disabled={asking || !ready || !question.trim()} onClick={() => void sendMessage()} aria-label={asking ? tr.gemmaThinking : tr.sendMessage}>{asking ? tr.gemmaThinking : tr.sendMessage}<Icon name="arrow-up" size={17} /></button></div>
        </div>
      </div>
      {message && <p className="workspace-message" role="status">{localizeMessage(message)}</p>}
    </article>
  </section>;
}
