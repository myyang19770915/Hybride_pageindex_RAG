"""A/B-compare two or more eval result files side by side.

Each `eval.run_eval` run writes a labelled result JSON. Point this at several of
them to see which config wins on each metric — the workflow for "I changed a
setting, did it actually help?".

Usage (from repo root):
    PYTHONPATH=backend python -m eval.compare eval/results/eval-baseline-*.json \
        eval/results/eval-dense-*.json
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

# metric key -> (display name, higher_is_better)
_METRICS = [
    ("doc_hit_rate", "Doc hit rate", True, "pct"),
    ("page_hit_rate", "Page hit rate", True, "pct"),
    ("mrr", "MRR", True, "num"),
    ("answered_rate", "Answered rate", True, "pct"),
    ("faithful_rate", "Faithful rate", True, "pct"),
    ("mean_latency_ms", "Mean latency", False, "ms"),
]


def _load(paths: list[str]) -> list[dict]:
    expanded: list[str] = []
    for p in paths:
        hits = glob.glob(p)
        expanded.extend(hits or [p])
    runs = []
    for path in expanded:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data["_path"] = path
        runs.append(data)
    return runs


def _fmt(value: object, kind: str) -> str:
    if value is None:
        return "  -  "
    if kind == "pct":
        return f"{float(value):6.1%}"
    if kind == "ms":
        return f"{float(value):6.0f}ms"
    return f"{float(value):6.3f}"


def _winner(values: list[float | None], higher_is_better: bool) -> int | None:
    present = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(present) < 2:
        return None
    chooser = max if higher_is_better else min
    best = chooser(present, key=lambda iv: iv[1])
    # No winner if everyone tied.
    if all(abs(v - best[1]) < 1e-9 for _, v in present):
        return None
    return best[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare eval result files.")
    parser.add_argument("results", nargs="+", help="result JSON files (globs allowed)")
    args = parser.parse_args()

    runs = _load(args.results)
    if len(runs) < 2:
        raise SystemExit("Need at least 2 result files to compare.")

    labels = [r.get("label", Path(r["_path"]).stem) for r in runs]
    col = max(12, max(len(label) for label in labels) + 1)

    print("\nA/B COMPARISON")
    print(f"  items: {[r['config'].get('n') for r in runs]}  (compare only like-sized runs)\n")
    for i, r in enumerate(runs):
        print(f"  [{labels[i]}] settings={r.get('settings')}")
    print()

    header = "Metric".ljust(16) + "".join(label.rjust(col) for label in labels) + "   winner"
    print(header)
    print("-" * len(header))

    for key, name, higher, kind in _METRICS:
        values = [r["metrics"].get(key) for r in runs]
        if all(v is None for v in values):
            continue
        cells = "".join(_fmt(v, kind).rjust(col) for v in values)
        win = _winner([None if v is None else float(v) for v in values], higher)
        win_label = labels[win] if win is not None else "tie"
        print(name.ljust(16) + cells + f"   {win_label}")

    print()


if __name__ == "__main__":
    main()
