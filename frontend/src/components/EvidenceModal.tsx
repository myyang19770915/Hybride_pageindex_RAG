import { ChevronLeft, ChevronRight, FileText, Loader2, X } from "lucide-react";
import { useEffect, useState } from "react";

import { PageEvidence, api } from "../api/client";

type Props = {
  documentId: string;
  fileName: string;
  startPage: number;
  endPage: number;
  answer: string;
  query: string;
  onClose: () => void;
  onOpenDocument?: (documentId: string, start: number, end: number) => void;
};

export function EvidenceModal({
  documentId,
  fileName,
  startPage,
  endPage,
  answer,
  query,
  onClose,
  onOpenDocument
}: Props) {
  const [page, setPage] = useState(startPage);
  const [evidence, setEvidence] = useState<PageEvidence | null>(null);
  const [loading, setLoading] = useState(true);
  const [imageError, setImageError] = useState(false);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setImageError(false);
    setEvidence(null);
    api
      .pageEvidence(documentId, page, { answer, query })
      .then((result) => active && setEvidence(result))
      .catch(() => active && setEvidence(null))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [documentId, page, answer, query]);

  const matchedCount = evidence?.blocks.filter((b) => b.matched).length ?? 0;
  const visibleBlocks = (evidence?.blocks ?? []).filter((b) => showAll || b.matched);

  return (
    <div className="evidence-backdrop" onClick={onClose}>
      <div className="evidence-modal" onClick={(e) => e.stopPropagation()}>
        <header className="evidence-header">
          <div className="evidence-title">
            <strong>{fileName}</strong>
            <span>第 {page} 頁 · 引用範圍 {startPage}-{endPage}</span>
          </div>
          <div className="evidence-actions">
            <label className="evidence-toggle">
              <input
                type="checkbox"
                checked={showAll}
                onChange={(e) => setShowAll(e.target.checked)}
              />
              顯示所有區塊
            </label>
            {onOpenDocument && (
              <button
                className="evidence-open-doc"
                onClick={() => {
                  onOpenDocument(documentId, startPage, endPage);
                  onClose();
                }}
                type="button"
              >
                <FileText size={14} /> 檢視全文
              </button>
            )}
            <button className="evidence-close" onClick={onClose} type="button" aria-label="關閉">
              <X size={18} />
            </button>
          </div>
        </header>

        <div className="evidence-stage">
          {loading && (
            <div className="evidence-loading">
              <Loader2 className="spin" size={20} /> 載入頁面…
            </div>
          )}
          {!loading && imageError && (
            <div className="evidence-empty">此文件無法產生頁面影像（可能是示範文件或無原始 PDF）。</div>
          )}
          {!loading && !imageError && (
            <div className="evidence-canvas">
              <img
                src={api.documentPageImageUrl(documentId, page)}
                alt={`第 ${page} 頁`}
                onError={() => setImageError(true)}
              />
              {visibleBlocks.map((block) => (
                <div
                  key={block.index}
                  className={`evidence-box${block.matched ? " evidence-box--matched" : ""}`}
                  style={{
                    left: `${block.bbox[0] * 100}%`,
                    top: `${block.bbox[1] * 100}%`,
                    width: `${(block.bbox[2] - block.bbox[0]) * 100}%`,
                    height: `${(block.bbox[3] - block.bbox[1]) * 100}%`
                  }}
                  title={block.text}
                />
              ))}
            </div>
          )}
        </div>

        <footer className="evidence-footer">
          <button
            className="evidence-page-btn"
            disabled={page <= startPage}
            onClick={() => setPage((p) => Math.max(startPage, p - 1))}
            type="button"
          >
            <ChevronLeft size={16} /> 上一頁
          </button>
          <span className="evidence-status">
            {evidence?.has_regions === false
              ? "此文件無區塊座標資料，僅顯示頁面影像"
              : `框出 ${matchedCount} 個答案來源區塊`}
          </span>
          <button
            className="evidence-page-btn"
            disabled={page >= endPage}
            onClick={() => setPage((p) => Math.min(endPage, p + 1))}
            type="button"
          >
            下一頁 <ChevronRight size={16} />
          </button>
        </footer>
      </div>
    </div>
  );
}
