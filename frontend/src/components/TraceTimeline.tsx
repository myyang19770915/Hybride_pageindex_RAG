import {
  BookOpen,
  CheckCircle2,
  Combine,
  Compass,
  FileText,
  Loader2,
  PenLine,
  ScrollText,
  Search,
  SlidersHorizontal,
  Type
} from "lucide-react";
import { ReactNode } from "react";

import { TraceEvent } from "../api/client";

const STAGE_META: Record<string, { icon: ReactNode; label: string }> = {
  router: { icon: <Compass size={16} />, label: "規劃檢索策略" },
  qdrant_hybrid: { icon: <Combine size={16} />, label: "Qdrant 混合檢索（向量 + BM25）" },
  dense_search: { icon: <Search size={16} />, label: "向量語義檢索候選文件" },
  sparse_search: { icon: <Type size={16} />, label: "BM25 關鍵字檢索" },
  fusion: { icon: <Combine size={16} />, label: "融合混合檢索結果 (RRF)" },
  coarse_search: { icon: <Search size={16} />, label: "彙整候選文件" },
  document_select: { icon: <FileText size={16} />, label: "鎖定最相關文件" },
  navigation: { icon: <BookOpen size={16} />, label: "翻閱章節目錄" },
  vector_node: { icon: <Search size={16} />, label: "向量比對最相關章節" },
  page_fetch: { icon: <ScrollText size={16} />, label: "閱讀頁面內容" },
  rerank: { icon: <SlidersHorizontal size={16} />, label: "重新排序最相關段落" },
  synthesis: { icon: <PenLine size={16} />, label: "綜合內容並生成回答" }
};

function pageRange(event: TraceEvent): string {
  if (event.start_page == null) {
    return "";
  }
  if (event.end_page == null || event.end_page === event.start_page) {
    return `第 ${event.start_page} 頁`;
  }
  return `第 ${event.start_page}-${event.end_page} 頁`;
}

/** Human, confidence-building narration for each pipeline stage. */
function narrate(event: TraceEvent): ReactNode {
  const name = event.document_name;
  const range = pageRange(event);
  const book = name ? <strong>《{name}》</strong> : null;

  switch (event.stage) {
    case "document_select":
      return <>鎖定文件 {book}</>;
    case "navigation":
      return <>正在翻閱 {book} {range} 的章節…</>;
    case "vector_node":
      return <>以向量比對鎖定 {book} {range} 的最相關章節…</>;
    case "page_fetch":
      return (
        <>
          正在翻閱 {book} {range}…
        </>
      );
    case "synthesis":
      return <>正在綜合 {book} 的內容，生成回答…</>;
    default:
      return STAGE_META[event.stage]?.label ?? event.message;
  }
}

type Props = {
  events: TraceEvent[];
  loading: boolean;
};

export function TraceTimeline({ events, loading }: Props) {
  if (events.length === 0) {
    return (
      <p className="trace-idle">送出問題後，這裡會即時顯示 Agent 的推理軌跡。</p>
    );
  }

  return (
    <ol className="trace-timeline">
      {events.map((event, index) => {
        const isLast = index === events.length - 1;
        const active = loading && isLast;
        const meta = STAGE_META[event.stage] ?? { icon: <Search size={16} />, label: event.stage };
        return (
          <li className={`trace-step${active ? " trace-step--active" : ""}`} key={`${event.stage}-${index}`}>
            <span className="trace-step-icon">
              {active ? <Loader2 className="spin" size={16} /> : meta.icon}
            </span>
            <div className="trace-step-body">
              <span className="trace-step-stage">{meta.label}</span>
              <span className="trace-step-text">{narrate(event)}</span>
            </div>
            <span className="trace-step-state">
              {active ? null : <CheckCircle2 size={15} />}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
