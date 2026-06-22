# RAG Evaluation Harness

Measures retrieval and answer quality so changes to retrieval strategy, rerank,
BM25 weights, chunking, or the synthesis prompt can be judged by numbers instead
of vibes.

## What it measures

Per question (black-box against the real pipeline):

- **Document hit rate** — was the ground-truth document cited at all?
- **Page hit rate** — did a citation actually cover the ground-truth page?
- **MRR** — 1/rank of the first page-correct citation (rewards ranking the right page first).
- **Answered rate** — `answered` vs `insufficient` / `clarify` / `error`.
- **Faithful rate** (optional `--judge`) — LLM grades whether the answer is supported by the source.
- **Mean latency**.

## Workflow

Run from the repo root with the live `.env` (`USE_DATABASE=true`, `USE_QDRANT=true`,
LM Studio reachable). The corpus must already be ingested.

### 1. Generate a golden set from the corpus

```bash
PYTHONPATH=backend python -m eval.generate_golden --per-doc 3
```

For each completed document this samples pages and asks the LLM to write a
question answerable only from that page; the page is the ground truth. Output:
`backend/eval/golden_set.jsonl`.

**Review it.** Auto-generated questions are a starting point. Open the JSONL,
delete weak/ambiguous questions, fix answers, add your own hand-written cases.
The golden set is an asset you grow over time — the 👍/👎 feedback feature can
feed it later.

### 2. Run the eval

```bash
PYTHONPATH=backend python -m eval.run_eval --label baseline
PYTHONPATH=backend python -m eval.run_eval --judge            # + faithfulness
```

Prints a summary and writes per-item results to
`backend/eval/results/eval-<label>-<ts>.json`.

### 3. A/B test a setting change

This is the point of the harness: change a knob, re-run, see if it helped. Every
run snapshots the effective settings, and `--set KEY=VAL` overrides a setting for
that run without editing `.env` (so no restart needed):

```bash
PYTHONPATH=backend python -m eval.run_eval --label baseline
PYTHONPATH=backend python -m eval.run_eval --label no-rerank --set RETRIEVAL_RERANK=false
PYTHONPATH=backend python -m eval.run_eval --label dense     --set RETRIEVAL_STRATEGY=dense
PYTHONPATH=backend python -m eval.run_eval --label bm25-tuned --set BM25_K1=1.2 --set BM25_B=0.6

# side-by-side, with a winner per metric:
PYTHONPATH=backend python -m eval.compare eval/results/eval-baseline-*.json eval/results/eval-no-rerank-*.json
```

`--strategy` / `--top-k` are per-request overrides (no env needed). For changes
that need re-ingestion (e.g. `LLM_TOC_SUMMARY`, embedding model), change `.env`,
re-ingest, then run with a fresh `--label`. The result file records which settings
were active, so comparisons stay honest.

## Files

| File | Role |
|------|------|
| `generate_golden.py` | LLM-generate Q&A from corpus pages → `golden_set.jsonl` |
| `run_eval.py` | Run golden set through `RetrievalService`, score, aggregate |
| `metrics.py` | Pure scoring functions (unit-tested in `tests/test_eval_metrics.py`) |
| `llm_client.py` | Shared OpenAI-compatible chat helper (LM Studio) |
| `golden_set.jsonl` | The labelled questions (commit it; it's your test asset) |
| `results/` | Timestamped run outputs |

## Notes

- `golden_set.jsonl` is generated from page text, so ground-truth pages are exact.
  The demo document (`doc_demo_txc`) only has synthetic pages 16-17.
- Metric math has no `app.*` dependency, so `tests/test_eval_metrics.py` runs in the
  hermetic unit suite. The runner needs the live stack.
