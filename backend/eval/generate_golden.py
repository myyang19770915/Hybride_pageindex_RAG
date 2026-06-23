"""Generate a golden Q&A set from the live corpus.

For each completed document we sample pages with enough text and ask the LLM to
write one specific question answerable *only* from that page. The page becomes
the ground-truth source for retrieval scoring. Output is JSONL — one GoldenItem
per line — which you should skim and hand-correct: auto-generated questions are
a starting point, not gospel.

Usage (from repo root, live .env with USE_DATABASE/USE_QDRANT=true):
    PYTHONPATH=backend python -m eval.generate_golden --per-doc 3
    PYTHONPATH=backend python -m eval.generate_golden --docs doc_07963f3ea45b --per-doc 5 --append
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.schemas.documents import IngestionStatus
from app.services.documents import DocumentService

from eval.llm_client import chat_json

_DEFAULT_OUT = Path(__file__).resolve().parent / "golden_set.jsonl"

_SYSTEM = (
    "你是知識庫測試集出題者。根據使用者提供的『單一頁面原文』，產生 {n} 個可以"
    "『只靠這頁內容』回答的繁體中文問題與精簡標準答案。要求：\n"
    "1. 每題都要具體、提到頁面中的關鍵名詞或數據，像真實使用者會問的問題；彼此不重複。\n"
    "2. 問題本身不可出現『這頁/本頁/以上/根據上文』等指涉，要能獨立成立。\n"
    "3. 答案精簡（一兩句），且確實出自該頁原文。\n"
    '4. 只輸出 JSON：{{"items": [{{"question": "...", "answer": "..."}}]}}，不要其他文字。'
)


def _sample_indices(count: int, k: int) -> list[int]:
    """Evenly spread k indices across [0, count) without random (keeps runs reproducible)."""
    if count <= k:
        return list(range(count))
    step = count / k
    return sorted({int(i * step) for i in range(k)})


def _iter_golden(
    service: DocumentService,
    doc_ids: list[str] | None,
    per_doc: int,
    min_chars: int,
    per_page: int,
):
    docs = service.list_documents(latest_only=True)
    docs = [d for d in docs if d.status == IngestionStatus.completed]
    if doc_ids:
        wanted = set(doc_ids)
        docs = [d for d in docs if d.document_id in wanted]

    system = _SYSTEM.format(n=per_page)
    for doc in docs:
        pages = [
            p
            for p in service.list_pages(doc.document_id)
            if len((p.page_content or "").strip()) >= min_chars
        ]
        if not pages:
            print(f"  [skip] {doc.file_name}: no pages with >= {min_chars} chars")
            continue
        chosen = [pages[i] for i in _sample_indices(len(pages), per_doc)]
        for page in chosen:
            excerpt = page.page_content.strip()
            result = chat_json(system, excerpt[:4000], max_tokens=256 + 256 * per_page)
            items = (result or {}).get("items") or []
            usable = [it for it in items if isinstance(it, dict) and it.get("question")]
            if not usable:
                print(f"  [skip] {doc.file_name} p{page.page_number}: no usable question")
                continue
            for idx, it in enumerate(usable[:per_page], start=1):
                yield {
                    "id": f"{doc.document_id}-p{page.page_number}-q{idx}",
                    "query": str(it["question"]).strip(),
                    "document_id": doc.document_id,
                    "file_name": doc.file_name,
                    "page_number": page.page_number,
                    "expected_answer": str(it.get("answer", "")).strip(),
                    "source_excerpt": excerpt[:500],
                }
            print(f"  [ok]   {doc.file_name} p{page.page_number}: {len(usable[:per_page])} q")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a golden Q&A set from the corpus.")
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    parser.add_argument("--per-doc", type=int, default=3, help="pages sampled per document")
    parser.add_argument("--questions-per-page", type=int, default=1, help="questions per page")
    parser.add_argument("--docs", type=str, default="", help="comma-separated document_ids")
    parser.add_argument("--min-chars", type=int, default=200, help="skip pages under this length")
    parser.add_argument("--append", action="store_true", help="append instead of overwrite")
    args = parser.parse_args()

    doc_ids = [d.strip() for d in args.docs.split(",") if d.strip()] or None
    service = DocumentService()

    items = list(
        _iter_golden(service, doc_ids, args.per_doc, args.min_chars, args.questions_per_page)
    )
    if not items:
        print("No golden items generated. Is the corpus ingested and the LLM reachable?")
        return

    args.out.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if args.append else "w"
    with args.out.open(mode, encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")

    verb = "appended" if args.append else "overwrote"
    print(f"\nWrote {len(items)} golden items to {args.out} ({verb}).")
    print("Review and hand-correct before treating these as ground truth.")


if __name__ == "__main__":
    main()
