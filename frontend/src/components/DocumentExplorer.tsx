import { ChevronRight, FileText, History, ListTree } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { DocumentDetail, DocumentListItem, DocumentPage, TocNode, api } from "../api/client";

type Props = {
  documentId: string;
  highlight?: { start: number; end: number } | null;
  onSelectDocument?: (documentId: string) => void;
};

function TocTree({
  nodes,
  onSelect
}: {
  nodes: TocNode[];
  onSelect: (page: number) => void;
}) {
  return (
    <ul className="toc-tree">
      {nodes.map((node) => (
        <li key={node.node_id}>
          <button className="toc-node" onClick={() => onSelect(node.start_page)} type="button">
            <ChevronRight size={14} />
            <span className="toc-heading">{node.heading}</span>
            <span className="toc-pages">
              p.{node.start_page}-{node.end_page}
            </span>
          </button>
          {node.summary && <p className="toc-summary">{node.summary}</p>}
          {node.children?.length > 0 && <TocTree nodes={node.children} onSelect={onSelect} />}
        </li>
      ))}
    </ul>
  );
}

export function DocumentExplorer({ documentId, highlight, onSelectDocument }: Props) {
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [pages, setPages] = useState<DocumentPage[]>([]);
  const [versions, setVersions] = useState<DocumentListItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const pageRefs = useRef<Record<number, HTMLElement | null>>({});

  useEffect(() => {
    let active = true;
    setError(null);
    Promise.all([
      api.documentDetail(documentId),
      api.documentPages(documentId),
      api.documentVersions(documentId).catch(() => [] as DocumentListItem[])
    ])
      .then(([detailResult, pagesResult, versionsResult]) => {
        if (!active) {
          return;
        }
        setDetail(detailResult);
        setPages(pagesResult);
        setVersions(versionsResult);
      })
      .catch((err) => active && setError(err.message));
    return () => {
      active = false;
    };
  }, [documentId]);

  const highlighted = useMemo(() => {
    if (!highlight) {
      return new Set<number>();
    }
    const set = new Set<number>();
    for (let page = highlight.start; page <= highlight.end; page += 1) {
      set.add(page);
    }
    return set;
  }, [highlight]);

  useEffect(() => {
    if (highlight) {
      pageRefs.current[highlight.start]?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [highlight, pages]);

  function scrollToPage(pageNumber: number) {
    pageRefs.current[pageNumber]?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  if (error) {
    return <div className="explorer-empty">無法載入文件：{error}</div>;
  }

  if (!detail) {
    return <div className="explorer-empty">載入文件中…</div>;
  }

  return (
    <div className="document-explorer">
      <header className="explorer-header">
        <div>
          <h2>
            <FileText size={18} /> {detail.file_name}
          </h2>
          <span>
            {detail.version} · {detail.total_pages} 頁 · {detail.status}
            {detail.owner ? ` · ${detail.owner}` : ""}
          </span>
        </div>
        {versions.length > 1 && (
          <label className="version-picker">
            <History size={14} />
            <select
              value={detail.document_id}
              onChange={(event) => onSelectDocument?.(event.target.value)}
            >
              {versions.map((version) => (
                <option key={version.document_id} value={version.document_id}>
                  {version.version}
                  {version.is_latest ? " (最新)" : ""}
                </option>
              ))}
            </select>
          </label>
        )}
      </header>

      <div className="explorer-body">
        <aside className="explorer-toc">
          <h3>
            <ListTree size={15} /> 目錄
          </h3>
          {detail.toc.length > 0 ? (
            <TocTree nodes={detail.toc} onSelect={scrollToPage} />
          ) : (
            <p className="toc-summary">此文件沒有解析出目錄結構。</p>
          )}
        </aside>

        <section className="explorer-pages">
          {pages.map((page) => (
            <article
              className={`page-card${highlighted.has(page.page_number) ? " page-card--cited" : ""}`}
              id={`page-${page.page_number}`}
              key={page.page_number}
              ref={(element) => {
                pageRefs.current[page.page_number] = element;
              }}
            >
              <div className="page-card-header">
                <span>第 {page.page_number} 頁</span>
                {highlighted.has(page.page_number) && <span className="page-tag">引用來源</span>}
              </div>
              <pre className="page-content">{page.page_content}</pre>
            </article>
          ))}
          {pages.length === 0 && <div className="explorer-empty">尚無逐頁內文。</div>}
        </section>
      </div>
    </div>
  );
}
