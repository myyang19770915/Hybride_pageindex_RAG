import {
  AlertCircle,
  BarChart3,
  CheckCircle2,
  FileSearch,
  FlaskConical,
  HelpCircle,
  Loader2,
  MessageSquare,
  Plus,
  RefreshCw,
  Send,
  Trash2,
  UploadCloud,
  X
} from "lucide-react";
import {
  ChangeEvent,
  KeyboardEvent as ReactKeyboardEvent,
  MouseEvent as ReactMouseEvent,
  useEffect,
  useRef,
  useState
} from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  AnswerStatus,
  DocumentListItem,
  IngestionJobResponse,
  QueryResponse,
  SessionSummary,
  TraceEvent,
  api
} from "./api/client";
import { DocumentExplorer } from "./components/DocumentExplorer";
import { EvalPanel } from "./components/EvalPanel";
import { EvidenceModal } from "./components/EvidenceModal";
import { MineruPlayground } from "./components/MineruPlayground";
import { TraceTimeline } from "./components/TraceTimeline";

type Evidence = { start: number; end: number } | null;
type Citation = QueryResponse["citations"][number];
type EvidenceTarget = {
  documentId: string;
  fileName: string;
  start: number;
  end: number;
  answer: string;
  query: string;
};

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  reasoning: string;
  trace: TraceEvent[];
  citations: Citation[];
  status?: AnswerStatus;
  clarifyingQuestion?: string | null;
  streaming: boolean;
};

const SESSION_KEY = "hybride_chat_session";

function newSessionId(): string {
  return crypto.randomUUID();
}

function loadSessionId(): string {
  const existing = localStorage.getItem(SESSION_KEY);
  if (existing) return existing;
  const created = newSessionId();
  localStorage.setItem(SESSION_KEY, created);
  return created;
}

/** Strip the leading answerability marker so it never shows in the bubble. */
function stripMarker(text: string): string {
  return text.replace(/^【(?:需要澄清|資料不足)】\s*/, "");
}

const STATUS_LABEL: Record<string, string> = {
  queued: "已排入佇列",
  processing: "解析中",
  completed: "完成",
  failed: "失敗",
  deleted: "已刪除"
};

const INGEST_STEPS = ["排入佇列", "MinerU 解析", "建立索引"];

/** Index of the active step (everything before it is done); -1 on failure. */
function ingestStep(status: string): number {
  if (status === "processing") return 1;
  if (status === "completed") return INGEST_STEPS.length;
  if (status === "failed") return -1;
  return 0;
}

function ingestPercent(status: string): number {
  if (status === "processing") return 66;
  if (status === "completed" || status === "failed") return 100;
  return 18;
}

function isIngesting(status: string): boolean {
  return status === "queued" || status === "processing";
}

function ingestHint(status: string): string {
  if (isIngesting(status)) return "處理中…";
  if (status === "completed") return "已完成";
  return "已停止";
}

function statusIcon(status: string) {
  if (status === "completed") return <CheckCircle2 size={16} />;
  if (status === "failed") return <AlertCircle size={16} />;
  return <Loader2 className="spin" size={16} />;
}

function stepStatusClass(index: number, activeStep: number): string {
  if (index < activeStep) return "is-done";
  if (index === activeStep) return "is-active";
  return "";
}

function MarkdownText({ text }: Readonly<{ text: string }>) {
  return (
    <div className="markdown">
      <Markdown remarkPlugins={[remarkGfm]}>{text}</Markdown>
    </div>
  );
}

function MessageBody({ msg }: Readonly<{ msg: ChatMessage }>) {
  if (msg.status === "need_clarification") {
    return (
      <div className="clarify-box">
        <span className="clarify-label">
          <HelpCircle size={15} /> 需要更多資訊
        </span>
        <MarkdownText text={msg.clarifyingQuestion || stripMarker(msg.content)} />
        <span className="clarify-hint">請補充上述資訊後再次送出問題。</span>
      </div>
    );
  }
  if (msg.status === "insufficient") {
    return (
      <div className="clarify-box clarify-box--insufficient">
        <span className="clarify-label">
          <AlertCircle size={15} /> 查無足夠資料
        </span>
        <MarkdownText text={stripMarker(msg.content)} />
      </div>
    );
  }
  return (
    <div className="msg-text">
      <MarkdownText text={stripMarker(msg.content)} />
      {msg.streaming && <span className="stream-cursor" />}
    </div>
  );
}

export function App() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const threadEndRef = useRef<HTMLDivElement>(null);
  const [health, setHealth] = useState("checking");
  const [documents, setDocuments] = useState<DocumentListItem[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [sessionId, setSessionId] = useState<string>(loadSessionId);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [uploadJob, setUploadJob] = useState<IngestionJobResponse | null>(null);
  const [uploading, setUploading] = useState(false);
  const [processingJob, setProcessingJob] = useState(false);
  const [explorerDocId, setExplorerDocId] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<Evidence>(null);
  const [evidenceTarget, setEvidenceTarget] = useState<EvidenceTarget | null>(null);
  const [view, setView] = useState<"chat" | "mineru" | "eval">("chat");
  const pollAttempts = useRef(0);

  function openDocument(documentId: string, highlight: Evidence = null) {
    setView("chat");
    setExplorerDocId(documentId);
    setEvidence(highlight);
  }

  function openEvidence(citation: Citation, message: ChatMessage) {
    // The cited answer is this assistant message; the query is the user turn
    // that preceded it (best signal for which page regions were used).
    const index = messages.findIndex((m) => m.id === message.id);
    const priorUser = messages.slice(0, index).reverse().find((m) => m.role === "user");
    setEvidenceTarget({
      documentId: citation.document_id,
      fileName: citation.file_name,
      start: citation.start_page,
      end: citation.end_page,
      answer: message.content,
      query: priorUser?.content ?? ""
    });
  }

  async function removeDocument(event: ReactMouseEvent, document: DocumentListItem) {
    event.stopPropagation();
    if (!window.confirm(`確定要刪除《${document.file_name}》？\n將一併清除 PostgreSQL、Qdrant 向量與來源檔。`)) {
      return;
    }
    await api.deleteDocument(document.document_id);
    if (explorerDocId === document.document_id) {
      setExplorerDocId(null);
    }
    await refresh();
  }

  async function refresh() {
    const [healthResult, documentsResult] = await Promise.all([api.health(), api.documents()]);
    setHealth(`${healthResult.status} · ${healthResult.environment}`);
    setDocuments(documentsResult);
  }

  useEffect(() => {
    refresh().catch((error) => setHealth(error.message));
    void refreshSessions();
  }, []);

  // Poll the active ingestion job so the upload card and document library reflect
  // live progress (queued -> processing -> completed) without a manual refresh.
  useEffect(() => {
    if (!uploadJob || !isIngesting(uploadJob.status) || pollAttempts.current > 300) {
      return;
    }
    const { job_id, status } = uploadJob;
    let cancelled = false;
    const timer = setTimeout(async () => {
      pollAttempts.current += 1;
      try {
        const fresh = await api.job(job_id);
        if (cancelled) {
          return;
        }
        if (fresh.status !== status) {
          setDocuments(await api.documents());
        }
        setUploadJob(fresh);
      } catch {
        // Transient error: re-trigger the effect to retry while still ingesting.
        if (!cancelled) {
          setUploadJob((current) => (current ? { ...current } : current));
        }
      }
    }, 1800);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [uploadJob]);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  function updateMessage(id: string, updater: (message: ChatMessage) => ChatMessage) {
    setMessages((current) => current.map((message) => (message.id === id ? updater(message) : message)));
  }

  async function refreshSessions() {
    try {
      setSessions(await api.listSessions());
    } catch {
      // sessions list is best-effort; ignore transient failures
    }
  }

  function startNewChat() {
    const fresh = newSessionId();
    localStorage.setItem(SESSION_KEY, fresh);
    setSessionId(fresh);
    setMessages([]);
  }

  async function loadSession(id: string) {
    localStorage.setItem(SESSION_KEY, id);
    setSessionId(id);
    setExplorerDocId(null);
    try {
      const history = await api.sessionMessages(id);
      setMessages(
        history.map((message, index) => ({
          id: `${id}-${index}`,
          role: message.role,
          content: message.content,
          reasoning: "",
          trace: [],
          citations: [],
          streaming: false
        }))
      );
    } catch {
      setMessages([]);
    }
  }

  async function removeSession(event: ReactMouseEvent, id: string) {
    event.stopPropagation();
    await api.deleteSession(id);
    if (id === sessionId) {
      startNewChat();
    }
    await refreshSessions();
  }

  async function send() {
    const text = input.trim();
    if (!text || sending) {
      return;
    }
    const userId = newSessionId();
    const assistantId = newSessionId();
    setMessages((current) => [
      ...current,
      { id: userId, role: "user", content: text, reasoning: "", trace: [], citations: [], streaming: false },
      { id: assistantId, role: "assistant", content: "", reasoning: "", trace: [], citations: [], streaming: true }
    ]);
    setInput("");
    setSending(true);
    try {
      const result = await api.queryStream({
        query: text,
        sessionId,
        onToken: (delta) =>
          updateMessage(assistantId, (m) => ({ ...m, content: m.content + delta })),
        onReasoning: (delta) =>
          updateMessage(assistantId, (m) => ({ ...m, reasoning: m.reasoning + delta })),
        onTrace: (traceEvent) =>
          updateMessage(assistantId, (m) => ({ ...m, trace: [...m.trace, traceEvent] }))
      });
      updateMessage(assistantId, (m) => ({
        ...m,
        content: result.answer || m.content,
        status: result.status,
        clarifyingQuestion: result.clarifying_question,
        citations: result.citations,
        trace: result.trace?.length ? result.trace : m.trace,
        streaming: false
      }));
      void refreshSessions();
    } catch (error) {
      updateMessage(assistantId, (m) => ({
        ...m,
        content: `發生錯誤：${error}`,
        status: "insufficient",
        streaming: false
      }));
    } finally {
      setSending(false);
    }
  }

  function onInputKeyDown(event: ReactKeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void send();
    }
  }

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    setUploading(true);
    pollAttempts.current = 0;
    try {
      const job = await api.uploadDocument(file);
      setUploadJob(job);
      await refresh();
    } finally {
      setUploading(false);
      event.target.value = "";
    }
  }

  async function processLatestJob() {
    if (!uploadJob) {
      return;
    }
    setProcessingJob(true);
    try {
      const job = await api.processJob(uploadJob.job_id);
      setUploadJob(job);
      await refresh();
    } finally {
      setProcessingJob(false);
    }
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <FileSearch size={24} />
          <div>
            <h1>Hybride RAG</h1>
            <span>{health}</span>
          </div>
        </div>

        <input
          accept="application/pdf,.pdf"
          className="file-input"
          onChange={upload}
          ref={fileInputRef}
          type="file"
        />
        <button
          className="primary-button"
          disabled={uploading}
          onClick={() => fileInputRef.current?.click()}
          type="button"
        >
          <UploadCloud size={18} />
          {uploading ? "上傳中" : "上傳文件"}
        </button>

        <div className="nav-tabs">
          <button
            className={`nav-tab${view === "chat" ? " nav-tab--active" : ""}`}
            onClick={() => setView("chat")}
            type="button"
          >
            <MessageSquare size={15} /> 對話
          </button>
          <button
            className={`nav-tab${view === "mineru" ? " nav-tab--active" : ""}`}
            onClick={() => {
              setView("mineru");
              setExplorerDocId(null);
            }}
            type="button"
          >
            <FlaskConical size={15} /> MinerU 測試
          </button>
          <button
            className={`nav-tab${view === "eval" ? " nav-tab--active" : ""}`}
            onClick={() => {
              setView("eval");
              setExplorerDocId(null);
            }}
            type="button"
          >
            <BarChart3 size={15} /> 評估
          </button>
        </div>
        {uploadJob && (
          <div className={`ingest-card ingest-card--${uploadJob.status}`}>
            <div className="ingest-head">
              <span className="ingest-status">
                {statusIcon(uploadJob.status)}
                {STATUS_LABEL[uploadJob.status] ?? uploadJob.status}
              </span>
              <span className="ingest-hint">{ingestHint(uploadJob.status)}</span>
            </div>

            <div className="progress-track">
              <div
                className={`progress-bar progress-bar--${uploadJob.status}${
                  isIngesting(uploadJob.status) ? " progress-bar--active" : ""
                }`}
                style={{ width: `${ingestPercent(uploadJob.status)}%` }}
              />
            </div>

            <ol className="ingest-steps">
              {INGEST_STEPS.map((label, index) => (
                <li className={stepStatusClass(index, ingestStep(uploadJob.status))} key={label}>
                  {label}
                </li>
              ))}
            </ol>

            <p className="ingest-message">{uploadJob.message}</p>

            {uploadJob.status === "queued" && (
              <button
                className="secondary-button"
                disabled={processingJob}
                onClick={processLatestJob}
                type="button"
              >
                {processingJob ? "解析中…" : "立即解析"}
              </button>
            )}
          </div>
        )}

        <section className="panel">
          <div className="panel-title">
            <h2>文件庫</h2>
            <button aria-label="重新整理文件" className="icon-button" onClick={refresh} type="button">
              <RefreshCw size={16} />
            </button>
          </div>
          <div className="document-list">
            {documents.map((document) => (
              <div
                className={`document-row${
                  explorerDocId === document.document_id ? " document-row--active" : ""
                }`}
                key={document.document_id}
              >
                <button
                  className="document-open"
                  onClick={() => openDocument(document.document_id)}
                  type="button"
                >
                  <strong>
                    {document.file_name}
                    {document.is_latest === false && <span className="version-badge">舊版</span>}
                  </strong>
                  <span className="document-meta">
                    <span className={`doc-status doc-status--${document.status}`}>
                      {isIngesting(document.status) && <Loader2 className="spin" size={11} />}
                      {STATUS_LABEL[document.status] ?? document.status}
                    </span>
                    <span className="doc-sub">
                      {document.total_pages} 頁 · {document.version}
                    </span>
                  </span>
                </button>
                {document.document_id !== "doc_demo_txc" && (
                  <button
                    aria-label={`刪除 ${document.file_name}`}
                    className="doc-delete"
                    onClick={(event) => removeDocument(event, document)}
                    title="刪除文件（含 PostgreSQL 與 Qdrant 向量）"
                    type="button"
                  >
                    <Trash2 size={15} />
                  </button>
                )}
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-title">
            <h2>歷史對話</h2>
            <button className="icon-button" onClick={startNewChat} title="新對話" type="button">
              <Plus size={16} />
            </button>
          </div>
          <div className="session-list">
            {sessions.length === 0 && <span className="session-empty">尚無歷史對話</span>}
            {sessions.map((session) => (
              <div
                className={`session-row${session.session_id === sessionId ? " session-row--active" : ""}`}
                key={session.session_id}
              >
                <button
                  className="session-open"
                  onClick={() => loadSession(session.session_id)}
                  type="button"
                >
                  <MessageSquare size={14} />
                  <span className="session-title">{session.title}</span>
                </button>
                <button
                  aria-label="刪除對話"
                  className="doc-delete"
                  onClick={(event) => removeSession(event, session.session_id)}
                  title="刪除對話"
                  type="button"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        </section>
      </aside>

      <section className="workspace">
        {view === "eval" ? (
          <EvalPanel />
        ) : view === "mineru" ? (
          <MineruPlayground />
        ) : explorerDocId ? (
          <section className="explorer-shell">
            <button
              className="secondary-button explorer-close"
              onClick={() => setExplorerDocId(null)}
              type="button"
            >
              <X size={14} /> 關閉文件
            </button>
            <DocumentExplorer
              documentId={explorerDocId}
              highlight={evidence}
              onSelectDocument={(id) => openDocument(id, evidence)}
            />
          </section>
        ) : (
          <section className="chat">
            <div className="chat-header">
              <h2>對話</h2>
              <button className="secondary-button" onClick={startNewChat} type="button">
                <Plus size={15} /> 新對話
              </button>
            </div>

            <div className="chat-thread">
              {messages.length === 0 && (
                <div className="chat-empty">
                  問我任何關於知識庫文件的問題。Agent 會混合檢索、查資料庫取頁原文，再帶頁碼回答；
                  資訊不足時會反問你。
                </div>
              )}
              {messages.map((message) => (
                <div className={`chat-msg chat-msg--${message.role}`} key={message.id}>
                  <div className="chat-bubble">
                    {message.role === "assistant" &&
                      (message.trace.length > 0 || message.reasoning) && (
                        <details className="process-box" open={message.streaming}>
                          <summary>思考過程{message.trace.length > 0 ? `（${message.trace.length} 步）` : ""}</summary>
                          {message.trace.length > 0 && (
                            <TraceTimeline events={message.trace} loading={message.streaming} />
                          )}
                          {message.reasoning && (
                            <div className="reasoning-block">
                              <span className="reasoning-label">模型推理</span>
                              <p className="reasoning-text">{message.reasoning}</p>
                            </div>
                          )}
                        </details>
                      )}
                    {message.role === "assistant" ? (
                      <MessageBody msg={message} />
                    ) : (
                      <p className="msg-text">{message.content}</p>
                    )}
                    {message.citations.map((citation) => (
                      <button
                        className="citation"
                        key={`${citation.document_id}-${citation.start_page}`}
                        onClick={() => openEvidence(citation, message)}
                        type="button"
                      >
                        {citation.file_name} · 第 {citation.start_page}-{citation.end_page} 頁
                      </button>
                    ))}
                  </div>
                </div>
              ))}
              <div ref={threadEndRef} />
            </div>

            <form
              className="chat-input"
              onSubmit={(event) => {
                event.preventDefault();
                void send();
              }}
            >
              <textarea
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={onInputKeyDown}
                placeholder="輸入問題，Enter 送出、Shift+Enter 換行…"
                value={input}
              />
              <button className="send-button" disabled={sending || !input.trim()} type="submit">
                <Send size={18} />
                {sending ? "推理中" : "送出"}
              </button>
            </form>
          </section>
        )}
      </section>

      {evidenceTarget && (
        <EvidenceModal
          documentId={evidenceTarget.documentId}
          fileName={evidenceTarget.fileName}
          startPage={evidenceTarget.start}
          endPage={evidenceTarget.end}
          answer={evidenceTarget.answer}
          query={evidenceTarget.query}
          onClose={() => setEvidenceTarget(null)}
          onOpenDocument={(documentId, start, end) =>
            openDocument(documentId, { start, end })
          }
        />
      )}
    </main>
  );
}
