const API_BASE = "/api";

export type DocumentListItem = {
  document_id: string;
  file_name: string;
  version: string;
  total_pages: number;
  status: string;
  created_at: string;
  owner?: string | null;
  is_latest?: boolean;
};

export type TocNode = {
  node_id: string;
  heading: string;
  start_page: number;
  end_page: number;
  summary: string;
  children: TocNode[];
};

export type DocumentDetail = DocumentListItem & {
  toc: TocNode[];
  stored_path?: string | null;
};

export type DocumentPage = {
  document_id: string;
  page_number: number;
  page_content: string;
};

export type AnswerStatus = "answered" | "need_clarification" | "insufficient";

export type QueryResponse = {
  answer: string;
  mode: string;
  status?: AnswerStatus;
  clarifying_question?: string | null;
  citations: Array<{
    document_id: string;
    file_name: string;
    start_page: number;
    end_page: number;
  }>;
  trace: Array<{
    stage: string;
    message: string;
    document_id?: string;
    document_name?: string;
    start_page?: number;
    end_page?: number;
  }>;
};

export type TraceEvent = QueryResponse["trace"][number];

export type MineruParseParams = {
  backend: string;
  parse_method: string;
  lang: string;
  formula_enable: boolean;
  table_enable: boolean;
  image_analysis: boolean;
  effort: string;
  start_page_id: number;
  end_page_id: number;
  server_url?: string;
};

export type MineruParseResult = {
  backend?: string;
  version?: string;
  markdown: string;
  content_list: unknown[];
  images: Record<string, string>;
  elapsed_ms?: number;
};

export type MineruStatus = {
  base_url: string;
  managed: boolean;
  healthy: boolean;
};

export type SessionSummary = {
  session_id: string;
  title: string;
  updated_at?: number | null;
};

export type ChatMessageOut = {
  role: "user" | "assistant";
  content: string;
};

export type IngestionJobResponse = {
  job_id: string;
  document_id: string;
  status: string;
  message?: string;
};

export type GoldenItem = {
  id: string;
  query: string;
  file_name: string;
  page_number: number;
  expected_answer: string;
};

export type EvalConfig = {
  top_k?: number;
  strategy?: string | null;
  rerank_provider?: string | null;
  cohere_model?: string | null;
  node_hits?: number | null;
  limit?: number;
};

export type EvalItemResult = {
  id: string;
  query: string;
  document_id: string;
  file_name: string;
  page_number: number;
  doc_hit: boolean;
  page_hit: boolean;
  rank: number | null;
  status: string;
  citations: [string, number, number][];
};

export type EvalRunResult = {
  n: number;
  settings: Record<string, unknown>;
  metrics: {
    doc_hit_rate: number;
    page_hit_rate: number;
    mrr: number;
    answered_rate: number;
    mean_latency_ms: number;
    per_status: Record<string, number>;
  };
  items: EvalItemResult[];
};

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`GET ${path} failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    throw new Error(`POST ${path} failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function postForm<T>(path: string, body: FormData): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    body
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(`POST ${path} failed: ${response.status} ${message}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => getJson<{ status: string; app_name: string; environment: string }>("/health"),
  documents: (latestOnly = false) =>
    getJson<DocumentListItem[]>(`/documents${latestOnly ? "?latest_only=true" : ""}`),
  documentDetail: (documentId: string) =>
    getJson<DocumentDetail>(`/documents/${documentId}`),
  documentPages: (documentId: string) =>
    getJson<DocumentPage[]>(`/documents/${documentId}/pages`),
  documentVersions: (documentId: string) =>
    getJson<DocumentListItem[]>(`/documents/${documentId}/versions`),
  deleteDocument: async (documentId: string): Promise<IngestionJobResponse> => {
    const response = await fetch(`${API_BASE}/documents/${documentId}`, { method: "DELETE" });
    if (!response.ok) {
      throw new Error(`DELETE /documents/${documentId} failed: ${response.status}`);
    }
    return response.json() as Promise<IngestionJobResponse>;
  },
  uploadDocument: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return postForm<IngestionJobResponse>("/documents", body);
  },
  job: (jobId: string) => getJson<IngestionJobResponse>(`/documents/jobs/${jobId}`),
  processJob: (jobId: string) =>
    postJson<IngestionJobResponse>(`/documents/jobs/${jobId}/process`, {}),
  query: (query: string) => postJson<QueryResponse>("/query", { query, mode: "auto", top_k: 5 }),
  mineruStatus: () => getJson<MineruStatus>("/mineru/status"),
  mineruParse: (file: File, params: MineruParseParams): Promise<MineruParseResult> => {
    const body = new FormData();
    body.append("file", file);
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") {
        body.append(key, String(value));
      }
    });
    return postForm<MineruParseResult>("/mineru/parse", body);
  },
  listSessions: () => getJson<SessionSummary[]>("/chat/sessions"),
  sessionMessages: (sessionId: string) =>
    getJson<ChatMessageOut[]>(`/chat/sessions/${sessionId}/messages`),
  deleteSession: async (sessionId: string): Promise<void> => {
    const response = await fetch(`${API_BASE}/chat/sessions/${sessionId}`, { method: "DELETE" });
    if (!response.ok) {
      throw new Error(`DELETE /chat/sessions/${sessionId} failed: ${response.status}`);
    }
  },
  queryStream: async (options: {
    query: string;
    sessionId?: string;
    onToken?: (delta: string) => void;
    onReasoning?: (delta: string) => void;
    onTrace?: (event: TraceEvent) => void;
  }): Promise<QueryResponse> => {
    const { query, sessionId, onToken, onReasoning, onTrace } = options;
    const response = await fetch(`${API_BASE}/query/stream`, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, mode: "auto", top_k: 5, session_id: sessionId })
    });
    if (!response.ok || !response.body) {
      throw new Error(`POST /query/stream failed: ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finalResponse: QueryResponse | null = null;

    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop() ?? "";
      for (const chunk of chunks) {
        const event = chunk
          .split("\n")
          .find((line) => line.startsWith("event:"))
          ?.replace("event:", "")
          .trim();
        const dataLine = chunk.split("\n").find((line) => line.startsWith("data:"));
        if (!event || !dataLine) {
          continue;
        }
        const payload = JSON.parse(dataLine.replace("data:", "").trim());
        if (event === "token") {
          onToken?.((payload as { delta: string }).delta);
        }
        if (event === "reasoning") {
          onReasoning?.((payload as { delta: string }).delta);
        }
        if (event === "trace") {
          onTrace?.(payload as TraceEvent);
        }
        if (event === "final") {
          finalResponse = payload as QueryResponse;
        }
      }
    }

    if (!finalResponse) {
      throw new Error("Stream finished without a final answer.");
    }
    return finalResponse;
  },
  evalGolden: () => getJson<GoldenItem[]>("/eval/golden"),
  evalRun: (config: EvalConfig) => postJson<EvalRunResult>("/eval/run", config)
};
