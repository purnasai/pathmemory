"""Summarize eval/recovery JSONL: per-mode totals and the paired per-task table.

    uv run python -m pathmemory.report results/v1/eval.jsonl --select first
    uv run python -m pathmemory.report results/v1/eval.jsonl --select latest
    uv run python -m pathmemory.report results/v1/eval.jsonl --select both

A JSONL file can hold several attempts of the same (task, mode) (a rerun appends). Which attempt is
reported is always an explicit choice, every attempt stays listed, and attempts whose task definition
differs (goal changed between runs) are flagged rather than pooled.
"""

import argparse
import gzip
import json
import pickle
from collections import defaultdict
from pathlib import Path

from pathmemory.config import settings

RESULTS = settings.root / "results"
MODES = ["none", "flat", "graph"]
POLICIES = ("first", "latest")


def load_rows(path) -> list[dict]:
    """Every observation in file order, annotated with its line and its attempt number within (task, mode)."""
    rows, seen = [], defaultdict(int)
    for line_no, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        r = json.loads(line)
        seen[(r["task"], r["mode"])] += 1
        rows.append({**r, "_line": line_no, "_attempt": seen[(r["task"], r["mode"])]})
    for r in rows:
        r["_attempts"] = seen[(r["task"], r["mode"])]
    return rows


def select(rows: list[dict], policy: str) -> dict:
    """{task: {mode: row}} with one attempt per (task, mode), chosen by policy ("first" or "latest")."""
    if policy not in POLICIES:
        raise ValueError(f"policy must be one of {POLICIES}, got {policy!r}")
    by = defaultdict(dict)
    for r in rows:
        if policy == "latest" or r["mode"] not in by[r["task"]]:
            by[r["task"]][r["mode"]] = r
    return dict(by)


def goal_of(row) -> str | None:
    """The goal the attempt actually ran with: recorded in the row (schema 2) or read from its run directory."""
    if row.get("goal"):
        return row["goal"]
    f = RESULTS / rel_run_dir(row["exp_dir"]) / "goal_object.pkl.gz"
    if not f.exists():
        return None
    goal = pickle.load(gzip.open(f))
    text = next((m.get("text", "") for m in goal or [] if m.get("type") == "text"), "")
    return text.split(" When you are done, send me")[0] or None


def rel_run_dir(exp_dir: str) -> str:
    """Saved rows hold absolute paths from wherever the run happened; keep the part under results/."""
    parts = Path(exp_dir).parts
    return str(Path(*parts[len(parts) - parts[::-1].index("results"):]))


def duplicates(rows: list[dict]) -> list[dict]:
    """Every (task, mode) with more than one attempt, all attempts listed, plus whether the task changed."""
    groups = defaultdict(list)
    for r in rows:
        groups[(r["task"], r["mode"])].append(r)
    out = []
    for (task, mode), rs in groups.items():
        if len(rs) < 2:
            continue
        attempts = [{"attempt": r["_attempt"], "line": r["_line"], "success": r["success"], "steps": r["steps"],
                     "task_sha": r.get("task_sha"), "goal": goal_of(r), "exp_dir": r["exp_dir"]} for r in rs]
        ids = {a["task_sha"] or a["goal"] for a in attempts}
        out.append({"task": task, "mode": mode, "attempts": attempts,
                    "same_definition": None if None in ids else len(ids) == 1})
    return out


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
            # browser steps whose action came from the base LLM (not model calls; see model_calls)
            "llm_steps": round(sum(r["llm_steps"] for r in rs) / n, 1),
            "replayed": round(sum(r["replayed_steps"] for r in rs) / n, 1),
            "input_tokens": round(sum(r["input_tokens"] for r in rs) / n),
            "seconds": round(sum(r["seconds"] for r in rs) / n, 1),
            "recovered": sum(r.get("recovered", False) for r in rs),
        }
        if all("model_calls" in r for r in rs):  # explicit counts exist only in schema-2 rows
            out[m]["model_calls"] = round(sum(r["model_calls"] for r in rs) / n, 1)
            out[m]["output_tokens"] = round(sum(r["output_tokens"] for r in rs) / n)
    return out


def print_table(by, policy):
    s = summarize(by)
    print(f"--- attempt selection: {policy} ---")
    print(f"{'mode':6} {'success':>9} {'steps':>6} {'LLM steps':>9} {'replayed':>8} {'model calls':>11} "
          f"{'in tokens':>9} {'sec':>6}")
    for m, v in s.items():
        calls = v.get("model_calls", "n/a")
        print(f"{m:6} {v['success']:>4}/{v['tasks']:<4} {v['steps']:>6} {v['llm_steps']:>9} {v['replayed']:>8} "
              f"{calls:>11} {v['input_tokens']:>9} {v['seconds']:>6}")
    print()
    print(f"{'task':11}" + "".join(f"{m:>18}" for m in MODES))
    for task, t in by.items():
        cells = []
        for m in MODES:
            r = t.get(m)
            cells.append(f"{'OK ' if r['success'] else 'X  '}{r['steps']:>2}st {r['llm_steps']:>2}llm" if r else "-")
        print(f"{task:11}" + "".join(f"{c:>18}" for c in cells))
    print()
    return s


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("path")
    p.add_argument("--select", required=True, choices=[*POLICIES, "both"],
                   help="which attempt to report when a (task, mode) was run more than once")
    a = p.parse_args(argv)
    rows = load_rows(a.path)
    dups = duplicates(rows)
    n_pairs = len({(r["task"], r["mode"]) for r in rows})
    print(f"{len(rows)} observations, {n_pairs} (task, mode) pairs, {len(dups)} pairs with more than one attempt\n")
    out = {}
    for policy in POLICIES if a.select == "both" else [a.select]:
        out[policy] = print_table(select(rows, policy), policy)
    if dups:
        print("--- repeated attempts (all observations kept) ---")
        for d in dups:
            same = {True: "same task definition", False: "TASK DEFINITION CHANGED between attempts",
                    None: "task definition not recorded"}[d["same_definition"]]
            print(f"{d['task']} / {d['mode']}: {same}")
            for x in d["attempts"]:
                print(f"   attempt {x['attempt']} (line {x['line']}): {'OK' if x['success'] else 'FAIL'} "
                      f"{x['steps']} steps  goal={x['goal']!r}")
    return out


if __name__ == "__main__":
    main()
