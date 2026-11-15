import React from "react";
import { t, formatNumber, tr } from "../i18n";
export function formatBytes(value: number | null | undefined): string {
  if (value == null) return tr.unavailable;
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let amount = value; let index = 0;
  while (amount >= 1024 && index < units.length - 1) { amount /= 1024; index += 1; }
  return `${formatNumber(amount)} ${units[index]}`;
}

export function gemmaStateLabel(value: string): string {
  const labels: Record<string, string> = {
    IDLE: tr.gemmaIdle, ACQUIRING: tr.gemmaLoading, RUNNING: tr.gemmaRunning,
    UNKNOWN: tr.gemmaUnknown, UNAVAILABLE: tr.gemmaUnavailable,
  };
  return labels[value] ?? tr.gemmaUnknown;
}

export function startBlockedReason(g: { state: string; start_allowed?: boolean; reason?: string }): string {
  if (g.state === "UNAVAILABLE") return t("Backend'e ulaşılamıyor veya model listesi alınamadı.");
  if (g.state === "ACQUIRING") return t("Model yükleniyor, birkaç saniye bekleyin…");
  if (g.state === "UNKNOWN") return g.reason ?? t("Bu portta başka bir servis çalışıyor.");
  if (g.state === "IDLE" && !g.start_allowed) return g.reason ?? t("Başlatma şu an izinli değil.");
  return "";
}

export class HttpError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

export async function responseJson(response: Response): Promise<Record<string, unknown>> {
  if (!response.ok) {
    let detail = "";
    try {
      const errorBody: unknown = await response.json();
      if (typeof errorBody === "object" && errorBody !== null && !Array.isArray(errorBody)) {
        const serverDetail = (errorBody as Record<string, unknown>).detail;
        if (typeof serverDetail === "string") detail = serverDetail;
      }
    } catch { /* Keep a generic safe message for non-JSON errors. */ }
    if (detail) throw new HttpError(detail, response.status);
    throw new HttpError(`${tr.requestFailed} (${response.status})`, response.status);
  }
  let body: unknown;
  try { body = await response.json(); }
  catch { throw new Error(tr.invalidResponse); }
  if (typeof body !== "object" || body === null || Array.isArray(body)) throw new Error(tr.invalidResponse);
  return body as Record<string, unknown>;
}

export async function sendJson(url: string, method: "POST" | "PUT" | "PATCH" | "DELETE", value: Record<string, unknown>) {
  const session = await responseJson(await fetch("/api/v1/session", { headers: { Accept: "application/json" } }));
  if (typeof session.csrf_token !== "string") throw new Error(tr.invalidResponse);
  return responseJson(await fetch(url, {
    method,
    headers: { "Content-Type": "application/json", "X-CSRF-Token": session.csrf_token },
    body: JSON.stringify(value),
  }));
}

export type Conversation = { id: string; title: string; kind: "assistant" | "code"; model_id: string; created_at: string; updated_at: string };
export type ChatMessage = { id: string; role: "user" | "assistant"; content: string; created_at: string; finish_reason?: "stop" | "length" };
export type StreamDone = { conversation: Conversation; messages: ChatMessage[]; tokens_per_second: number | null; omitted_messages: number };
export type StreamErrorCode = "cancelled" | "unavailable" | "internal";
export class ChatStreamError extends Error {
  constructor(message: string, readonly code: StreamErrorCode) { super(message); }
}

export async function streamConversation(
  conversationId: string,
  value: Record<string, unknown>,
  onDelta: (text: string) => void,
): Promise<StreamDone> {
  const session = await responseJson(await fetch("/api/v1/session", { headers: { Accept: "application/json" } }));
  if (typeof session.csrf_token !== "string") throw new Error(tr.invalidResponse);
  const response = await fetch(`/api/v1/conversations/${encodeURIComponent(conversationId)}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream", "X-CSRF-Token": session.csrf_token },
    body: JSON.stringify(value),
  });
  if (!response.ok) { await responseJson(response); throw new Error(tr.requestFailed); }
  if (!response.body) throw new Error(tr.invalidResponse);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed: StreamDone | null = null;
  const dispatch = (line: string) => {
    if (!line.startsWith("data:")) return;
    let event: Record<string, unknown>;
    try { event = JSON.parse(line.slice(5).trim()) as Record<string, unknown>; }
    catch { throw new Error(tr.invalidResponse); }
    if (event.type === "delta" && typeof event.text === "string") onDelta(event.text);
    else if (event.type === "error") {
      const code = event.code === "cancelled" || event.code === "unavailable" ? event.code : "internal";
      throw new ChatStreamError(typeof event.message === "string" ? event.message : tr.streamInterrupted, code);
    } else if (event.type === "done" && Array.isArray(event.messages) && typeof event.conversation === "object" && event.conversation !== null) {
      completed = { conversation: event.conversation as Conversation, messages: event.messages as ChatMessage[],
        tokens_per_second: typeof event.tokens_per_second === "number" ? event.tokens_per_second : null,
        omitted_messages: typeof event.omitted_messages === "number" ? event.omitted_messages : 0 };
    }
  };
  try {
    while (true) {
      const { value: chunk, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(chunk, { stream: true });
      const lines = buffer.split("\n"); buffer = lines.pop() ?? "";
      for (const line of lines) dispatch(line.replace(/\r$/, ""));
    }
    buffer += decoder.decode();
    if (buffer) dispatch(buffer.replace(/\r$/, ""));
  } finally {
    try { await reader.cancel(); } catch { /* The server may have already closed the stream. */ }
    reader.releaseLock();
  }
  if (!completed) throw new ChatStreamError(tr.streamInterrupted, "internal");
  return completed;
}

export function InlineMarkdown({ text }: { text: string }) {
  const pattern = /(`[^`]+`|\*\*.+?\*\*|\*[^*]+\*|\[[^\]]+\]\(https?:\/\/[^\s)]+\))/g;
  const pieces = text.split(pattern).filter(piece => piece !== "");
  return <>{pieces.map((piece, index) => {
    if (piece.startsWith("`") && piece.endsWith("`")) return <code key={index}>{piece.slice(1, -1)}</code>;
    if (piece.startsWith("**") && piece.endsWith("**")) return <strong key={index}>{piece.slice(2, -2)}</strong>;
    if (piece.startsWith("*") && piece.endsWith("*")) return <em key={index}>{piece.slice(1, -1)}</em>;
    const link = piece.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);
    if (link) return <a key={index} href={link[2]} target="_blank" rel="noopener noreferrer">{link[1]}</a>;
    return <React.Fragment key={index}>{piece}</React.Fragment>;
  })}</>;
}

export function MarkdownContent({ text }: { text: string }) {
  const lines = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
  const blocks: React.ReactNode[] = [];
  let index = 0;
  while (index < lines.length) {
    if (!lines[index].trim()) { index += 1; continue; }
    const fence = lines[index].match(/^\s*```([^\s`]*)\s*$/);
    if (fence) {
      const language = fence[1]; index += 1; const code: string[] = [];
      while (index < lines.length && !/^\s*```\s*$/.test(lines[index])) code.push(lines[index++]);
      if (index < lines.length) index += 1;
      blocks.push(<pre className="markdown-code" key={`code-${blocks.length}`}><code data-language={language || undefined}>{code.join("\n")}</code></pre>);
      continue;
    }
    const heading = lines[index].match(/^\s{0,3}(#{1,6})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length; const content = <InlineMarkdown text={heading[2]} />;
      blocks.push(React.createElement(`h${level}`, { key: `h-${blocks.length}` }, content)); index += 1; continue;
    }
    const listMatch = lines[index].match(/^\s*(?:[-*+]\s+|\d+[.)]\s+)/);
    if (listMatch) {
      const ordered = /^\s*\d+[.)]\s+/.test(lines[index]); const items: React.ReactNode[] = [];
      while (index < lines.length) {
        const item = lines[index].match(/^\s*(?:[-*+]\s+|\d+[.)]\s+)(.*)$/);
        if (!item) break;
        items.push(<li key={items.length}><InlineMarkdown text={item[1]} /></li>); index += 1;
      }
      blocks.push(ordered ? <ol key={`list-${blocks.length}`}>{items}</ol> : <ul key={`list-${blocks.length}`}>{items}</ul>); continue;
    }
    const paragraph: string[] = [];
    while (index < lines.length && lines[index].trim() && !/^\s*```/.test(lines[index]) && !/^\s{0,3}#{1,6}\s+/.test(lines[index]) && !/^\s*(?:[-*+]\s+|\d+[.)]\s+)/.test(lines[index])) paragraph.push(lines[index++]);
    blocks.push(<p key={`p-${blocks.length}`}>{paragraph.map((line, i) => <React.Fragment key={i}>{i > 0 && <br />}<InlineMarkdown text={line} /></React.Fragment>)}</p>);
  }
  return <div className="markdown-content">{blocks}</div>;
}

export function MessageTranscript({ messages, pendingUser, partialAnswer, onCopy, assistantLabel, emptyState }: {
  messages: ChatMessage[]; pendingUser?: string; partialAnswer?: string; onCopy: (text: string) => void; assistantLabel?: string; emptyState?: React.ReactNode;
}) {
  const visible = [...messages, ...(pendingUser ? [{ id: "pending-user", role: "user" as const, content: pendingUser, created_at: "" }] : []),
    ...(partialAnswer !== undefined ? [{ id: "pending-assistant", role: "assistant" as const, content: partialAnswer, created_at: "" }] : [])];
  const listRef = React.useRef<HTMLDivElement>(null);
  const stickToBottom = React.useRef(true);
  const lastLength = visible.length ? visible[visible.length - 1].content.length : 0;
  React.useEffect(() => {
    const node = listRef.current;
    if (node && stickToBottom.current) node.scrollTop = node.scrollHeight;
  }, [visible.length, lastLength]);
  return <div className="conversation-messages" aria-live="polite" ref={listRef} onScroll={event => {
    const node = event.currentTarget;
    stickToBottom.current = node.scrollHeight - node.scrollTop - node.clientHeight < 80;
  }}>{visible.length === 0 && (emptyState ?? <p className="empty-chat">{tr.emptyChat}</p>)}{visible.map(item => <article className={`chat-message ${item.role}`} key={item.id}>
    <div className="chat-message-head"><strong>{item.role === "user" ? tr.you : assistantLabel ?? tr.gemmaAnswer}</strong><button type="button" className="text-button copy-message" onClick={() => onCopy(item.content)}>{tr.copyMessage}</button></div>
    {item.id === "pending-assistant" && item.content === "" ? <span className="typing-dots" role="status" aria-label={tr.gemmaThinking}><i /><i /><i /></span> : <MarkdownContent text={item.content} />}
  </article>)}</div>;
}

export function ChatCompletionNotice({ messages, busy, omitted, onContinue }: {
  messages: ChatMessage[]; busy: boolean; omitted: number; onContinue: () => void;
}) {
  const truncated = messages.at(-1)?.finish_reason === "length";
  if (!truncated && !omitted) return null;
  return <div className="chat-completion-notice" role="status">
    {omitted > 0 && <p>{t("Sohbet geçmişi saklanır; model bağlama sığan son mesajları kullanır.")}</p>}
    {truncated && <div><span>{t("Yanıt uzunluk sınırına ulaştı.")}</span><button type="button" className="secondary-button" disabled={busy} onClick={onContinue}>{t("Devam ettir")}</button></div>}
  </div>;
}

export async function copyText(text: string, setMessage: React.Dispatch<React.SetStateAction<string>>) {
  try { await navigator.clipboard.writeText(text); setMessage(tr.messageCopied); }
  catch { setMessage(tr.copyFailed); }
}


export type GemmaState = { state: string; model_id?: string; managed?: boolean; active_request?: boolean; runtime_available?: boolean; model_files_available?: boolean; start_allowed?: boolean; model?: string; device?: string; context_size?: number; available_ram_bytes?: number | null; reason?: string };
