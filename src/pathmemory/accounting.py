"""Model-usage accounting for runs saved before PathMemory counted it explicitly (v1 rows).

v1 rows report llm_steps = browser steps whose action came from the base LLM. That is not the number of
model calls: graph mode also calls the destination chooser once per run, and the base agent re-queries the
model when it cannot parse an answer. This derives the counts from the saved steps, without changing them:

  base calls     = assistant messages in each LLM step's saved chat (1 + parse retries)
  chooser calls  = 1 if the run's log has a "choose" event (logged right after the chooser returns)
  total tokens   = AgentLab's stats.cum_input_tokens / cum_output_tokens. These already include the chooser:
                   PathMemoryAgent.get_action is wrapped in AgentLab's cost tracker, which sees every completion.
  chooser tokens = the step-0 token stats, but only when step 0 was a replayed click (then the chooser was the
                   only model call in that step). If step 0 was an LLM step, AgentLab stored only the sum of the
                   chooser and base call, so the split is reported as null, not estimated.

    uv run python -m pathmemory.accounting docs/evidence/v1/eval.jsonl > docs/evidence/v1-derived/eval.accounting.jsonl
"""

import gzip
import json
import pickle
import sys
from pathlib import Path

from pathmemory.report import RESULTS, goal_of, load_rows, rel_run_dir


def _role(m):
    return m.get("role") if isinstance(m, dict) else getattr(m, "role", None)


def derive(exp_dir: Path) -> dict:
    files = sorted(exp_dir.glob("step_*.pkl.gz"), key=lambda f: int(f.name.split("_")[1].split(".")[0]))
    steps = [pickle.load(gzip.open(f)) for f in files]
    summary = json.loads((exp_dir / "summary_info.json").read_text())
    base_calls, log, sources = 0, [], []
    for s in steps:
        if not s.action:
            continue
        info = s.agent_info or {}
        pm = (info.get("extra_info") or {}).get("pathmemory") or {}
        log = pm.get("log", log)
        sources.append(pm.get("source", "llm"))
        if pm.get("source", "llm") == "llm":
            base_calls += sum(_role(m) == "assistant" for m in info.get("chat_messages") or [])
    chooser_calls = int(any(e.get("event") == "choose" for e in log))
    total_in = int(summary.get("stats.cum_input_tokens") or 0)
    total_out = int(summary.get("stats.cum_output_tokens") or 0)
    out = {"chooser_calls": chooser_calls, "base_calls": base_calls, "model_calls": chooser_calls + base_calls,
           "input_tokens": total_in, "output_tokens": total_out,
           "chooser_input_tokens": 0 if not chooser_calls else None,
           "chooser_output_tokens": 0 if not chooser_calls else None, "chooser_tokens_source": None}
    if chooser_calls and sources and sources[0] == "graph":
        st = (steps[0].agent_info or {}).get("stats") or {}
        out.update(chooser_input_tokens=int(st.get("input_tokens") or 0),
                   chooser_output_tokens=int(st.get("output_tokens") or 0),
                   chooser_tokens_source="step 0 stats (replayed step: chooser was the only call)")
    elif chooser_calls:
        out["chooser_tokens_source"] = "unavailable: chooser and base call in the same step, only their sum was saved"
    if out["chooser_input_tokens"] is not None:
        out["base_input_tokens"] = total_in - out["chooser_input_tokens"]
        out["base_output_tokens"] = total_out - out["chooser_output_tokens"]
    else:
        out["base_input_tokens"] = out["base_output_tokens"] = None
    return out


def derive_file(path) -> list[dict]:
    rows = []
    for r in load_rows(path):
        d = RESULTS / rel_run_dir(r["exp_dir"])
        row = {"line": r["_line"], "attempt": r["_attempt"], "attempts": r["_attempts"], "task": r["task"],
               "mode": r["mode"], "goal": goal_of(r), "success": r["success"], "steps": r["steps"],
               "llm_steps": r["llm_steps"], "replayed_steps": r["replayed_steps"], "seconds": r["seconds"],
               "reported_input_tokens": r["input_tokens"], "exp_dir": rel_run_dir(r["exp_dir"])}
        if (d / "summary_info.json").exists():
            row.update(derive(d))
            row["tokens_match_row"] = row["input_tokens"] == r["input_tokens"]
        else:
            row["unverified"] = "run directory not available locally"
        rows.append(row)
    return rows


if __name__ == "__main__":
    for row in derive_file(sys.argv[1]):
        print(json.dumps(row))
