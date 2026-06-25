import {
  BarChart3,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Loader2,
  Play,
  Sparkles,
  XCircle
} from "lucide-react";
import { useEffect, useState } from "react";

import {
  DocumentListItem,
  EvalConfig,
  EvalRunResult,
  GenerateConfig,
  GoldenItem,
  api
} from "../api/client";

const STRATEGIES = ["", "dense", "hybrid", "bm25"];
const RERANKERS = ["", "bm25", "cohere"];
const COHERE_MODELS = [
  "rerank-v3.5",
  "rerank-v4.0-pro",
  "rerank-multilingual-v3.0",
  "rerank-english-v3.0"
];

type Form = {
  strategy: string;
  rerank: string;
  cohereModel: string;
  nodeHits: string;
  topK: string;
  limit: string;
};

const DEFAULT_FORM: Form = {
  strategy: "",
  rerank: "",
  cohereModel: "rerank-v3.5",
  nodeHits: "",
  topK: "5",
  limit: ""
};

type GenForm = {
  perDoc: string;
  questionsPerPage: string;
  minChars: string;
  append: boolean;
};

const DEFAULT_GEN_FORM: GenForm = {
  perDoc: "3",
  questionsPerPage: "1",
  minChars: "200",
  append: true
};

function pct(value: number): string {
  return `${(value * 100).toFixed(0)}%`;
}

export function EvalPanel() {
  const [golden, setGolden] = useState<GoldenItem[]>([]);
  const [form, setForm] = useState<Form>(DEFAULT_FORM);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<EvalRunResult | null>(null);
  const [showGolden, setShowGolden] = useState(true);

  const [showGen, setShowGen] = useState(false);
  const [docs, setDocs] = useState<DocumentListItem[]>([]);
  const [selectedDocs, setSelectedDocs] = useState<Set<string>>(new Set());
  const [genForm, setGenForm] = useState<GenForm>(DEFAULT_GEN_FORM);
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const [genNote, setGenNote] = useState<string | null>(null);

  useEffect(() => {
    api.evalGolden().then(setGolden).catch(() => setGolden([]));
    api
      .documents(true)
      .then((all) => setDocs(all.filter((d) => d.status === "completed")))
      .catch(() => setDocs([]));
  }, []);

  function set<K extends keyof Form>(key: K, value: Form[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function setGen<K extends keyof GenForm>(key: K, value: GenForm[K]) {
    setGenForm((current) => ({ ...current, [key]: value }));
  }

  function toggleDoc(id: string) {
    setSelectedDocs((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  async function generate() {
    if (generating) {
      return;
    }
    setGenerating(true);
    setGenError(null);
    setGenNote(null);
    const config: GenerateConfig = {
      doc_ids: Array.from(selectedDocs),
      per_doc: Number(genForm.perDoc) || 3,
      questions_per_page: Number(genForm.questionsPerPage) || 1,
      min_chars: Number(genForm.minChars) || 0,
      append: genForm.append
    };
    try {
      const res = await api.evalGenerate(config);
      setGenNote(`新增 ${res.added} 題，題庫現共 ${res.total} 題。`);
      setGolden(await api.evalGolden());
      setShowGolden(true);
    } catch (err) {
      setGenError(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerating(false);
    }
  }

  async function run() {
    if (running) {
      return;
    }
    setRunning(true);
    setError(null);
    const config: EvalConfig = {
      top_k: Number(form.topK) || 5,
      strategy: form.strategy || undefined,
      rerank_provider: form.rerank || undefined,
      cohere_model: form.rerank === "cohere" ? form.cohereModel : undefined,
      node_hits: form.nodeHits ? Number(form.nodeHits) : undefined,
      limit: form.limit ? Number(form.limit) : 0
    };
    try {
      setResult(await api.evalRun(config));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }

  const m = result?.metrics;

  return (
    <section className="eval">
      <div className="eval-header">
        <h2>
          <BarChart3 size={18} /> RAG 評估
        </h2>
        <span className="eval-hint">
          用 {golden.length} 題 golden set 量測檢索品質。切換設定做 A/B（評估進行中會暫改全域設定）。
        </span>
      </div>

      <div className="eval-controls">
        <label>
          strategy
          <select value={form.strategy} onChange={(e) => set("strategy", e.target.value)}>
            {STRATEGIES.map((s) => (
              <option key={s || "default"} value={s}>
                {s || "（目前設定）"}
              </option>
            ))}
          </select>
        </label>
        <label>
          reranker
          <select value={form.rerank} onChange={(e) => set("rerank", e.target.value)}>
            {RERANKERS.map((r) => (
              <option key={r || "default"} value={r}>
                {r || "（目前設定）"}
              </option>
            ))}
          </select>
        </label>
        {form.rerank === "cohere" && (
          <label>
            cohere model
            <select value={form.cohereModel} onChange={(e) => set("cohereModel", e.target.value)}>
              {COHERE_MODELS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
        )}
        <label>
          node_hits
          <input
            type="number"
            min={1}
            placeholder="目前設定"
            value={form.nodeHits}
            onChange={(e) => set("nodeHits", e.target.value)}
          />
        </label>
        <label>
          top_k
          <input
            type="number"
            min={1}
            max={20}
            value={form.topK}
            onChange={(e) => set("topK", e.target.value)}
          />
        </label>
        <label>
          題數（0=全部）
          <input
            type="number"
            min={0}
            placeholder="0"
            value={form.limit}
            onChange={(e) => set("limit", e.target.value)}
          />
        </label>
        <button className="primary-button eval-run" disabled={running} onClick={run} type="button">
          {running ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
          {running ? "評估中…" : "執行評估"}
        </button>
      </div>

      {running && (
        <p className="eval-note">在 {golden.length} 題上跑檢索，可能需數十秒（cohere 每題一次 API 呼叫）。</p>
      )}
      {error && <div className="clarify-box clarify-box--insufficient">{error}</div>}

      <div className="eval-golden">
        <button
          className="eval-golden-toggle"
          onClick={() => setShowGen((v) => !v)}
          type="button"
        >
          {showGen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
          <Sparkles size={14} /> 製作 Golden 題庫（依文件用 LLM 出題）
        </button>
        {showGen && (
          <div className="eval-gen">
            <p className="eval-gen-hint">
              對選定文件的取樣頁面用 LLM 出題，該頁即為正解來源。建議事後人工校正。未選文件＝全部已完成文件。
            </p>
            <div className="eval-gen-docs">
              {docs.length === 0 ? (
                <span className="eval-gen-empty">尚無已完成的文件可出題。</span>
              ) : (
                docs.map((d) => (
                  <label key={d.document_id} className="eval-gen-doc">
                    <input
                      type="checkbox"
                      checked={selectedDocs.has(d.document_id)}
                      onChange={() => toggleDoc(d.document_id)}
                    />
                    <span className="eval-gen-doc-name">{d.file_name}</span>
                    <span className="eval-file"> {d.version} · {d.total_pages}頁</span>
                  </label>
                ))
              )}
            </div>
            <div className="eval-controls eval-gen-controls">
              <label>
                每文件取樣頁數
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={genForm.perDoc}
                  onChange={(e) => setGen("perDoc", e.target.value)}
                />
              </label>
              <label>
                每頁題數
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={genForm.questionsPerPage}
                  onChange={(e) => setGen("questionsPerPage", e.target.value)}
                />
              </label>
              <label>
                最小字數
                <input
                  type="number"
                  min={0}
                  max={5000}
                  value={genForm.minChars}
                  onChange={(e) => setGen("minChars", e.target.value)}
                />
              </label>
              <label className="eval-gen-append">
                <input
                  type="checkbox"
                  checked={genForm.append}
                  onChange={(e) => setGen("append", e.target.checked)}
                />
                附加到題庫（取消＝覆寫）
              </label>
              <button
                className="primary-button eval-run"
                disabled={generating || docs.length === 0}
                onClick={generate}
                type="button"
              >
                {generating ? <Loader2 className="spin" size={16} /> : <Sparkles size={16} />}
                {generating ? "出題中…" : "生成題目"}
              </button>
            </div>
            {generating && (
              <p className="eval-note">每取樣頁呼叫一次 LLM，依頁數可能需數十秒到數分鐘。</p>
            )}
            {genNote && <p className="eval-gen-ok">{genNote}</p>}
            {genError && <div className="clarify-box clarify-box--insufficient">{genError}</div>}
          </div>
        )}
      </div>

      <div className="eval-golden">
        <button
          className="eval-golden-toggle"
          onClick={() => setShowGolden((v) => !v)}
          type="button"
        >
          {showGolden ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
          目前 Golden 題庫（{golden.length} 題）
        </button>
        {showGolden && (
          <div className="eval-table-wrap">
            <table className="eval-table">
              <thead>
                <tr>
                  <th>檔案 · 頁</th>
                  <th>問題</th>
                  <th>預期答案</th>
                </tr>
              </thead>
              <tbody>
                {golden.map((g) => (
                  <tr key={g.id}>
                    <td className="eval-nowrap">
                      {g.file_name}
                      <span className="eval-file"> p{g.page_number}</span>
                    </td>
                    <td>{g.query}</td>
                    <td className="eval-expected">{g.expected_answer}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {m && result && (
        <>
          <div className="eval-metrics">
            <Metric label="Page hit" value={pct(m.page_hit_rate)} good />
            <Metric label="Doc hit" value={pct(m.doc_hit_rate)} />
            <Metric label="MRR" value={m.mrr.toFixed(3)} />
            <Metric label="Answered" value={pct(m.answered_rate)} />
            <Metric label="延遲/題" value={`${Math.round(m.mean_latency_ms)}ms`} />
            <Metric label="題數" value={String(result.n)} />
          </div>
          <div className="eval-settings">
            生效設定：strategy={String(result.settings.retrieval_strategy)} · rerank=
            {String(result.settings.rerank)} · node_hits={String(result.settings.node_hits)}
          </div>

          <div className="eval-table-wrap">
            <table className="eval-table">
              <thead>
                <tr>
                  <th></th>
                  <th>問題</th>
                  <th>正解頁</th>
                  <th>引用頁</th>
                  <th>rank</th>
                </tr>
              </thead>
              <tbody>
                {result.items.map((it) => (
                  <tr key={it.id} className={it.page_hit ? "" : "eval-miss"}>
                    <td>
                      {it.page_hit ? (
                        <CheckCircle2 className="eval-ok" size={16} />
                      ) : (
                        <XCircle className="eval-bad" size={16} />
                      )}
                    </td>
                    <td className="eval-q">
                      <span className="eval-file">{it.file_name}</span>
                      {it.query}
                    </td>
                    <td>{it.page_number}</td>
                    <td>{it.citations.map((c) => (c[1] === c[2] ? `${c[1]}` : `${c[1]}-${c[2]}`)).join(", ") || "—"}</td>
                    <td>{it.rank ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

function Metric({ label, value, good }: { label: string; value: string; good?: boolean }) {
  return (
    <div className={`eval-metric${good ? " eval-metric--primary" : ""}`}>
      <span className="eval-metric-value">{value}</span>
      <span className="eval-metric-label">{label}</span>
    </div>
  );
}
