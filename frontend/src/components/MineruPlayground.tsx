import { FlaskConical, Loader2, UploadCloud } from "lucide-react";
import { useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { MineruParseParams, MineruParseResult, api } from "../api/client";

const BACKENDS = [
  "pipeline",
  "vlm-engine",
  "hybrid-engine",
  "vlm-http-client",
  "hybrid-http-client"
];
const METHODS = ["auto", "txt", "ocr"];
const LANGS = ["ch", "ch_server", "en", "korean", "japan", "arabic"];
const EFFORTS = ["medium", "high"];

const DEFAULT_PARAMS: MineruParseParams = {
  backend: "pipeline",
  parse_method: "auto",
  lang: "ch",
  formula_enable: true,
  table_enable: true,
  image_analysis: true,
  effort: "medium",
  start_page_id: 0,
  end_page_id: 99999
};

type Tab = "markdown" | "json" | "images";

export function MineruPlayground() {
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [params, setParams] = useState<MineruParseParams>(DEFAULT_PARAMS);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<MineruParseResult | null>(null);
  const [tab, setTab] = useState<Tab>("markdown");

  function set<K extends keyof MineruParseParams>(key: K, value: MineruParseParams[K]) {
    setParams((current) => ({ ...current, [key]: value }));
  }

  async function run() {
    if (!file || running) {
      return;
    }
    setRunning(true);
    setError(null);
    try {
      const parsed = await api.mineruParse(file, params);
      setResult(parsed);
      setTab("markdown");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }

  const images = result ? Object.entries(result.images) : [];

  return (
    <section className="mineru">
      <div className="mineru-header">
        <h2>
          <FlaskConical size={18} /> MinerU 解析測試
        </h2>
        <span className="mineru-hint">上傳 PDF，調整參數後解析，比較不同設定的結果。</span>
      </div>

      <div className="mineru-body">
        <form
          className="mineru-controls"
          onSubmit={(event) => {
            event.preventDefault();
            void run();
          }}
        >
          <input
            accept="application/pdf,.pdf,image/*"
            className="file-input"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            ref={fileRef}
            type="file"
          />
          <button
            className="secondary-button"
            onClick={() => fileRef.current?.click()}
            type="button"
          >
            <UploadCloud size={16} /> {file ? file.name : "選擇檔案"}
          </button>

          <label className="mineru-field">
            <span>backend</span>
            <select value={params.backend} onChange={(e) => set("backend", e.target.value)}>
              {BACKENDS.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
          </label>

          <label className="mineru-field">
            <span>method</span>
            <select
              value={params.parse_method}
              onChange={(e) => set("parse_method", e.target.value)}
            >
              {METHODS.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>

          <label className="mineru-field">
            <span>language</span>
            <select value={params.lang} onChange={(e) => set("lang", e.target.value)}>
              {LANGS.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
          </label>

          <label className="mineru-field">
            <span>effort (hybrid)</span>
            <select value={params.effort} onChange={(e) => set("effort", e.target.value)}>
              {EFFORTS.map((ef) => (
                <option key={ef} value={ef}>
                  {ef}
                </option>
              ))}
            </select>
          </label>

          <div className="mineru-row">
            <label className="mineru-field">
              <span>起始頁 (0-based)</span>
              <input
                min={0}
                onChange={(e) => set("start_page_id", Number(e.target.value))}
                type="number"
                value={params.start_page_id}
              />
            </label>
            <label className="mineru-field">
              <span>結束頁</span>
              <input
                min={0}
                onChange={(e) => set("end_page_id", Number(e.target.value))}
                type="number"
                value={params.end_page_id}
              />
            </label>
          </div>

          <label className="mineru-check">
            <input
              checked={params.formula_enable}
              onChange={(e) => set("formula_enable", e.target.checked)}
              type="checkbox"
            />
            公式辨識
          </label>
          <label className="mineru-check">
            <input
              checked={params.table_enable}
              onChange={(e) => set("table_enable", e.target.checked)}
              type="checkbox"
            />
            表格辨識
          </label>
          <label className="mineru-check">
            <input
              checked={params.image_analysis}
              onChange={(e) => set("image_analysis", e.target.checked)}
              type="checkbox"
            />
            影像/圖表分析 (vlm/hybrid)
          </label>

          {params.backend.endsWith("http-client") && (
            <label className="mineru-field">
              <span>server_url</span>
              <input
                onChange={(e) => set("server_url", e.target.value)}
                placeholder="http://127.0.0.1:30000"
                type="text"
                value={params.server_url ?? ""}
              />
            </label>
          )}

          <button className="primary-button" disabled={!file || running} type="submit">
            {running ? <Loader2 className="spin" size={16} /> : <FlaskConical size={16} />}
            {running ? "解析中…" : "解析"}
          </button>
          {running && <span className="mineru-note">首次或 vlm/hybrid 後端需載入模型，可能較久。</span>}
        </form>

        <div className="mineru-result">
          {error && <div className="clarify-box clarify-box--insufficient">{error}</div>}
          {!error && !result && <div className="chat-empty">解析結果會顯示在這裡。</div>}
          {result && (
            <>
              <div className="mineru-meta">
                backend: <strong>{result.backend}</strong> · MinerU {result.version} ·{" "}
                {result.elapsed_ms} ms · {images.length} 張圖
              </div>
              <div className="mineru-tabs">
                <button
                  className={tab === "markdown" ? "is-active" : ""}
                  onClick={() => setTab("markdown")}
                  type="button"
                >
                  Markdown
                </button>
                <button
                  className={tab === "json" ? "is-active" : ""}
                  onClick={() => setTab("json")}
                  type="button"
                >
                  content_list
                </button>
                <button
                  className={tab === "images" ? "is-active" : ""}
                  onClick={() => setTab("images")}
                  type="button"
                >
                  圖片 ({images.length})
                </button>
              </div>

              {tab === "markdown" && (
                <div className="markdown mineru-pane">
                  <Markdown remarkPlugins={[remarkGfm]}>{result.markdown}</Markdown>
                </div>
              )}
              {tab === "json" && (
                <pre className="mineru-pane mineru-json">
                  {JSON.stringify(result.content_list, null, 2)}
                </pre>
              )}
              {tab === "images" && (
                <div className="mineru-pane mineru-images">
                  {images.length === 0 && <span className="chat-empty">沒有擷取到圖片。</span>}
                  {images.map(([name, dataUri]) => (
                    <figure key={name}>
                      <img alt={name} src={dataUri} />
                      <figcaption>{name}</figcaption>
                    </figure>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
}
