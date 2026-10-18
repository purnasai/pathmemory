"""Four-mode comparison tables from eval JSONL files (one file per condition).

    uv run python -m pathmemory.compare normal=docs/evidence/v2/runs/normal.jsonl broken=... ablation=...

Every row of every file is used; rows are grouped by (condition, task definition, mode). "Replay reached goal"
means the memory's last route was replayed to its end with no failed check after it (from the event log); a
success without it is an LLM-fallback success, and is reported as such, not as a memory success.
"""

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

MODES = ["none", "flat", "flatreplay", "graph"]
METRICS = ["model_calls", "input_tokens", "output_tokens", "est_cost_usd", "steps", "replayed_steps", "seconds",
           "reset_seconds", "route_hops", "recoveries", "failed_edge_checks", "wrong_target_actions"]


def replay_reached_goal(row) -> bool:
    log = row.get("log") or []
    idx = [i for i, e in enumerate(log) if e["event"] == "route"]
    if not idx:
        return False
    route, after = log[idx[-1]], log[idx[-1] + 1:]
    hops = len(route["keys"]) - 1
    return (not any(e["event"] in ("edge_failed", "no_route") for e in after)
            and sum(e["event"] == "replay" for e in after) >= hops)


def load(spec: dict[str, str]) -> list[dict]:
    rows = []
    for cond, path in spec.items():
        for n, line in enumerate(Path(path).read_text().splitlines(), 1):
            r = json.loads(line)
            rows.append({**r, "condition": cond, "_file": path, "_line": n})
    return rows


def table(rows: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for r in rows:
        groups[(r["condition"], r["task"], r["task_sha"], r["mode"])].append(r)
    out = []
    for (cond, task, sha, mode), rs in groups.items():
        row = {"condition": cond, "task": task, "task_sha": sha, "mode": mode, "trials": len(rs),
               "success": sum(r["success"] for r in rs),
               "replay_reached_goal": sum(replay_reached_goal(r) for r in rs),
               "success_with_replay_to_goal": sum(r["success"] and replay_reached_goal(r) for r in rs),
               "accounting_consistent": all(r["accounting_consistent"] for r in rs),
               "memory_unchanged": all(r["memory"]["unchanged"] for r in rs),
               "snapshots": sorted({r["memory"]["snapshot"] for r in rs}),
               "source_episodes": sorted({e for r in rs for e in r.get("source_episodes") or []})}
        for m in METRICS:
            vals = [r.get(m) or 0 for r in rs]
            row[m] = {"mean": round(statistics.mean(vals), 4), "min": min(vals), "max": max(vals)}
        out.append(row)
    order = {m: i for i, m in enumerate(MODES)}
    return sorted(out, key=lambda r: (r["condition"], r["task"], order.get(r["mode"], 9)))


def markdown(tab: list[dict]) -> str:
    lines = []
    for cond in dict.fromkeys(r["condition"] for r in tab):
        lines += [f"\n**{cond}**\n",
                  "| mode | success | replay reached goal | model calls | input tok | output tok | est. $ | browser steps "
                  "| replayed | episode s | reset s | route hops | recoveries | failed checks | wrong-target |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in (x for x in tab if x["condition"] == cond):
            m = lambda k, f="{:.1f}": f.format(r[k]["mean"])  # noqa: E731
            lines.append(f"| {r['mode']} | {r['success']}/{r['trials']} | {r['replay_reached_goal']}/{r['trials']} | "
                         f"{m('model_calls')} | {m('input_tokens', '{:,.0f}')} | {m('output_tokens', '{:,.0f}')} | "
                         f"{m('est_cost_usd', '{:.4f}')} | {m('steps')} | {m('replayed_steps')} | {m('seconds')} | "
                         f"{m('reset_seconds')} | {m('route_hops')} | {m('recoveries')} | {m('failed_edge_checks')} | "
                         f"{m('wrong_target_actions')} |")
    return "\n".join(lines)


# litellm 1.80.0 model table, "gpt-6-luna", standard tier (what AgentLab's tracker multiplies by)
PRICE_IN, PRICE_OUT = 0.10 / 1e6, 0.50 / 1e6


def costs(rows: list[dict]) -> list[dict]:
    """Per (condition, mode): mean USD per task, split into chooser and base agent, with call counts.
    Parse retries = base model calls beyond one per LLM-chosen browser step."""
    groups = defaultdict(list)
    for r in rows:
        groups[(r["condition"], r["mode"])].append(r)
    out = []
    mean = statistics.mean
    for (cond, mode), rs in groups.items():
        usd = [r["input_tokens"] * PRICE_IN + r["output_tokens"] * PRICE_OUT for r in rs]
        chooser = [r["chooser_input_tokens"] * PRICE_IN + r["chooser_output_tokens"] * PRICE_OUT for r in rs]
        out.append({
            "condition": cond, "mode": mode, "trials": len(rs), "checker_passed": sum(r["success"] for r in rs),
            "usd_per_task": round(mean(usd), 5), "usd_min": round(min(usd), 5), "usd_max": round(max(usd), 5),
            "usd_chooser": round(mean(chooser), 5), "usd_base": round(mean(usd) - mean(chooser), 5),
            "tracker_usd_per_task": round(mean(r["est_cost_usd"] for r in rs), 5),
            "input_tokens": round(mean(r["input_tokens"] for r in rs)), "output_tokens": round(mean(r["output_tokens"] for r in rs)),
            "chooser_calls": mean(r["chooser_calls"] for r in rs), "base_calls": mean(r["base_calls"] for r in rs),
            "parse_retries": mean(r["base_calls"] - r["llm_steps"] for r in rs),
            "model_calls": mean(r["model_calls"] for r in rs),
        })
    order = {m: i for i, m in enumerate(MODES)}
    return sorted(out, key=lambda r: (r["condition"], order.get(r["mode"], 9)))


if __name__ == "__main__":
    spec = dict(a.split("=", 1) for a in sys.argv[1:])
    rows = load(spec)
    tab = table(rows)
    print(json.dumps({"table": tab, "costs": costs(rows)}, indent=1))
    print(markdown(tab), file=sys.stderr)
