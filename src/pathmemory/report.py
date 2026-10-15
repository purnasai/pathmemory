"""Summarize eval/recovery JSONL: per-mode totals and the paired per-task table.

    uv run python -m pathmemory.report results/v1/eval.jsonl
"""

import json
import sys
from collections import defaultdict

MODES = ["none", "flat", "graph"]


def load(path):
    rows = [json.loads(l) for l in open(path)]
    by = defaultdict(dict)
    for r in rows:
        by[r["task"]][r["mode"]] = r  # last run wins
    return by


def summarize(by):
    out = {}
    for m in MODES:
        rs = [t[m] for t in by.values() if m in t]
        if not rs:
            continue
        n = len(rs)
        out[m] = {
            "tasks": n,
            "success": sum(r["success"] for r in rs),
            "steps": round(sum(r["steps"] for r in rs) / n, 1),
            "llm_calls": round(sum(r["llm_steps"] for r in rs) / n, 1),
            "replayed": round(sum(r["replayed_steps"] for r in rs) / n, 1),
            "input_tokens": round(sum(r["input_tokens"] for r in rs) / n),
            "seconds": round(sum(r["seconds"] for r in rs) / n, 1),
            "recovered": sum(r.get("recovered", False) for r in rs),
        }
    return out


def main(path):
    by = load(path)
    s = summarize(by)
    print(f"{'mode':6} {'success':>9} {'steps':>6} {'LLM calls':>9} {'replayed':>8} {'in tokens':>9} {'sec':>6}")
    for m, v in s.items():
        print(f"{m:6} {v['success']:>4}/{v['tasks']:<4} {v['steps']:>6} {v['llm_calls']:>9} {v['replayed']:>8} "
              f"{v['input_tokens']:>9} {v['seconds']:>6}")
    print()
    print(f"{'task':11}" + "".join(f"{m:>18}" for m in MODES))
    for task, t in by.items():
        cells = []
        for m in MODES:
            r = t.get(m)
            cells.append(f"{'OK ' if r['success'] else 'X  '}{r['steps']:>2}st {r['llm_steps']:>2}llm" if r else "-")
        print(f"{task:11}" + "".join(f"{c:>18}" for c in cells))
    return s


if __name__ == "__main__":
    main(sys.argv[1])
