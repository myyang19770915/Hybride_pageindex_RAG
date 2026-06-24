"""Run the golden set through the retrieval pipeline and report metrics.

Calls RetrievalService in-process (no uvicorn needed) against whatever stores
the live .env points at, so this measures the real stack: hybrid retrieval,
rerank, Qdrant, BM25, LLM synthesis. Reports document hit rate, page hit rate,
MRR, answered rate, and latency. With --judge, an LLM grades whether each answer
is faithful to the ground-truth source.

A/B testing: every run snapshots the effective retrieval settings and writes a
labelled result file. Override settings inline with --set (no .env edit needed),
then diff runs with `eval.compare`:

    PYTHONPATH=backend python -m eval.run_eval --label baseline
    PYTHONPATH=backend python -m eval.run_eval --label no-rerank --set RETRIEVAL_RERANK=false
    PYTHONPATH=backend python -m eval.run_eval --label dense --set RETRIEVAL_STRATEGY=dense
    PYTHONPATH=backend python -m eval.compare eval/results/eval-baseline-*.json \
        eval/results/eval-no-rerank-*.json
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings
from app.schemas.query import QueryRequest, RetrievalStrategy

from eval.llm_client import chat_json
from eval.metrics import (
    Aggregate,
    GoldenItem,
    Outcome,
    RetrievedCitation,
    aggregate,
    score_citations,
)

_DEFAULT_GOLDEN = Path(__file__).resolve().parent / "golden_set.jsonl"
_RESULTS_DIR = Path(__file__).resolve().parent / "results"

_JUDGE_SYSTEM = (
    "你是 RAG 答案評審。根據『標準答案』與『來源原文片段』，判斷『系統答案』是否"
    "忠實正確（資訊有來源支持、與標準答案一致、未捏造）。只輸出 JSON："
    '{"faithful": true/false, "reason": "..."}'
)


def load_golden(path: Path) -> list[GoldenItem]:
    items: list[GoldenItem] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            items.append(
                GoldenItem(
                    id=raw["id"],
                    query=raw["query"],
                    document_id=raw["document_id"],
                    file_name=raw.get("file_name", ""),
                    page_number=int(raw["page_number"]),
                    expected_answer=raw.get("expected_answer", ""),
                    source_excerpt=raw.get("source_excerpt", ""),
                )
            )
    return items


def settings_snapshot() -> dict[str, object]:
    """The retrieval knobs that affect eval results, captured for A/B provenance."""
    s = get_settings()
    rerank = s.rerank_provider
    if rerank == "cohere":
        rerank = f"cohere:{s.cohere_rerank_model}"
    return {
        "retrieval_strategy": s.retrieval_strategy,
        "rerank": rerank,
        "node_hits": s.retrieval_node_hits,
        "bm25_k1": s.bm25_k1,
        "bm25_b": s.bm25_b,
        "model_id": s.model_id,
        "embedding_model": s.embedding_model,
    }


def _judge(item: GoldenItem, answer: str) -> bool | None:
    verdict = chat_json(
        _JUDGE_SYSTEM,
        f"問題：{item.query}\n標準答案：{item.expected_answer}\n"
        f"來源原文：{item.source_excerpt}\n系統答案：{answer}",
        max_tokens=512,
    )
    if not verdict or "faithful" not in verdict:
        return None
    return bool(verdict["faithful"])


def _mark(outcome: Outcome) -> str:
    if outcome.page_hit:
        return "OK "
    return "DOC" if outcome.doc_hit else "MISS"


def evaluate(
    items: list[GoldenItem], top_k: int, strategy: RetrievalStrategy | None, judge: bool
) -> list[Outcome]:
    # Imported lazily so settings overrides (--set) land before the stack reads them.
    from app.services.retrieval import RetrievalService

    service = RetrievalService()
    outcomes: list[Outcome] = []

    for n, item in enumerate(items, start=1):
        request = QueryRequest(query=item.query, top_k=top_k, strategy=strategy)
        started = time.monotonic()
        try:
            # Skip LLM synthesis unless we need the answer for the faithfulness judge:
            # page/doc-hit and MRR depend only on retrieval + citations. ~10x faster.
            response = service.answer(request, synthesize=judge)
            latency_ms = (time.monotonic() - started) * 1000
            citations = [
                RetrievedCitation(c.document_id, c.start_page, c.end_page)
                for c in response.citations
            ]
            doc_hit, page_hit, rank = score_citations(item, citations)
            outcome = Outcome(
                item=item,
                status=response.status,
                answer=response.answer,
                citations=citations,
                latency_ms=latency_ms,
                doc_hit=doc_hit,
                page_hit=page_hit,
                rank=rank,
            )
            if judge and response.answer:
                outcome.faithful = _judge(item, response.answer)
        except Exception as exc:  # one bad item must not abort the run
            latency_ms = (time.monotonic() - started) * 1000
            outcome = Outcome(
                item=item, status=f"error:{type(exc).__name__}", answer=str(exc)[:200],
                citations=[], latency_ms=latency_ms,
            )
        print(
            f"[{n:>3}/{len(items)}] {_mark(outcome)} rank={outcome.rank} "
            f"{outcome.item.file_name} p{item.page_number}: {item.query[:46]}"
        )
        outcomes.append(outcome)

    return outcomes


def _print_report(agg: Aggregate, label: str, top_k: int, settings: dict[str, object]) -> None:
    print("\n" + "=" * 56)
    print(f"RAG EVAL  [{label}]  (n={agg.n}, top_k={top_k})")
    print(f"  settings: {settings}")
    print("=" * 56)
    print(f"  Document hit rate : {agg.doc_hit_rate:6.1%}")
    print(f"  Page hit rate     : {agg.page_hit_rate:6.1%}")
    print(f"  MRR (page-level)  : {agg.mrr:6.3f}")
    print(f"  Answered rate     : {agg.answered_rate:6.1%}")
    if agg.faithful_rate is not None:
        print(f"  Faithful rate     : {agg.faithful_rate:6.1%}  (LLM judge)")
    print(f"  Mean latency      : {agg.mean_latency_ms:6.0f} ms")
    print(f"  Status breakdown  : {agg.per_status}")
    print("=" * 56)


def _apply_overrides(pairs: list[str]) -> None:
    """--set KEY=VAL → env var, then drop the settings cache so it takes effect."""
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--set expects KEY=VALUE, got: {pair}")
        key, value = pair.split("=", 1)
        os.environ[key.strip()] = value.strip()
    if pairs:
        get_settings.cache_clear()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RAG eval over the golden set.")
    parser.add_argument("--golden", type=Path, default=_DEFAULT_GOLDEN)
    parser.add_argument("--label", type=str, default="run", help="name this run (for A/B compare)")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--strategy", choices=[s.value for s in RetrievalStrategy], default=None)
    parser.add_argument(
        "--set", dest="overrides", action="append", default=[], metavar="KEY=VAL",
        help="override a setting for this run, e.g. --set RETRIEVAL_RERANK=false (repeatable)",
    )
    parser.add_argument("--limit", type=int, default=0, help="evaluate only the first N items")
    parser.add_argument("--judge", action="store_true", help="LLM-judge answer faithfulness")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    if not args.golden.exists():
        raise SystemExit(f"Golden set not found: {args.golden}. Run eval.generate_golden first.")

    _apply_overrides(args.overrides)

    items = load_golden(args.golden)
    if args.limit:
        items = items[: args.limit]
    if not items:
        raise SystemExit("Golden set is empty.")

    strategy = RetrievalStrategy(args.strategy) if args.strategy else None
    settings = settings_snapshot()
    if strategy is not None:
        settings["retrieval_strategy"] = f"{strategy.value} (per-request)"

    outcomes = evaluate(items, args.top_k, strategy, args.judge)
    agg = aggregate(outcomes)
    _print_report(agg, args.label, args.top_k, settings)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe_label = "".join(c if c.isalnum() or c in "-_" else "-" for c in args.label)
    out = args.out or (_RESULTS_DIR / f"eval-{safe_label}-{stamp}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "label": args.label,
        "timestamp": stamp,
        "config": {"top_k": args.top_k, "strategy": args.strategy, "judge": args.judge, "n": agg.n},
        "settings": settings,
        "metrics": {
            "doc_hit_rate": agg.doc_hit_rate,
            "page_hit_rate": agg.page_hit_rate,
            "mrr": agg.mrr,
            "answered_rate": agg.answered_rate,
            "faithful_rate": agg.faithful_rate,
            "mean_latency_ms": agg.mean_latency_ms,
            "per_status": agg.per_status,
        },
        "items": [
            {
                "id": o.item.id,
                "query": o.item.query,
                "document_id": o.item.document_id,
                "page_number": o.item.page_number,
                "doc_hit": o.doc_hit,
                "page_hit": o.page_hit,
                "rank": o.rank,
                "status": o.status,
                "faithful": o.faithful,
                "latency_ms": round(o.latency_ms),
                "citations": [[c.document_id, c.start_page, c.end_page] for c in o.citations],
            }
            for o in outcomes
        ],
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote per-item results to {out}")


if __name__ == "__main__":
    main()
