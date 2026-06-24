import { BarChart3, CheckCircle2, Loader2, Play, XCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { EvalConfig, EvalRunResult, GoldenItem, api } from "../api/client";

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

function pct(value: number): string {
  return `${(value * 100).toFixed(0)}%`;
}

export function EvalPanel() {
  const [golden, setGolden] = useState<GoldenItem[]>([]);
  const [form, setForm] = useState<Form>(DEFAULT_FORM);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<EvalRunResult | null>(null);

  useEffect(() => {
    api.evalGolden().then(setGolden).catch(() => setGolden([]));
  }, []);

  function set<K extends keyof Form>(key: K, value: Form[K]) {
    setForm((current) => ({ ...current, [key]: value }));
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
