"""Published experiment summaries and local browser-run artifacts for the demo UI."""

import gzip
import json
import pickle
from functools import lru_cache
from pathlib import Path

from pathmemory.config import settings
from pathmemory.evaluation.compare import replay_reached_goal
from pathmemory.evaluation.report import duplicates, load_rows, rel_run_dir, select, summarize
from pathmemory.service import InvalidArgument
from pathmemory.state import semantic_step, state_of

RESULTS = settings.root / "results"
EVIDENCE = settings.root / "docs/evidence"
# Local output and published evidence have separate locations. A fresh checkout has summaries,
# but screenshots and step pickles are only available after running experiments locally.
EXPERIMENTS = [
    ("v1/eval.jsonl", "v1/eval.jsonl", "v1: normal UI (historical)", "latest"),
    ("v1/recovery.jsonl", "v1/recovery.jsonl", "v1: UI break before repair (historical)", "latest"),
    ("v1-repaired/recovery.jsonl", "v1-repaired/recovery.jsonl", "v1: UI break after repair (historical)", "latest"),
    ("v2-normal/eval.jsonl", "v2/runs/normal.jsonl", "v2: normal UI", "all"),
    ("v2-broken/eval.jsonl", "v2/runs/broken.jsonl", "v2: dashboard repository links hidden", "all"),
    ("v2-ablation/eval.jsonl", "v2/runs/ablation.jsonl", "v2: bridge step removed", "all"),
    ("v2-broken-flatcov/eval.jsonl", "v2/runs/broken_flat_pinned.jsonl", "v2: flat prompt with pinned episodes", "all"),
]


class RunService:
    def experiments(self) -> list[dict]:
        out = []
        for local, published, title, selection in EXPERIMENTS:
            path = RESULTS / local
            if not path.exists():
                path = EVIDENCE / published
            if not path.exists():
                continue
            rows = load_rows(path)
            if selection == "all":
                # Each observation gets its own row; none of the independent trials is selected away.
                by = {}
                for row in rows:
                    label = f"{row['_unit']} · trial {row.get('trial', row['_attempt'])}"
                    if row["mode"] in by.get(label, {}):
                        label += f" · attempt {row['_attempt']}"
                    by.setdefault(label, {})[row["mode"]] = row
            else:
                by = select(rows, selection)
            summary = summarize(by)
            if selection == "all":
                for mode, totals in summary.items():
                    mode_rows = [row for row in rows if row["mode"] == mode]
                    totals["replay_reached_goal"] = sum(replay_reached_goal(row) for row in mode_rows)
                    totals["est_cost_usd"] = sum(row["est_cost_usd"] for row in mode_rows) / len(mode_rows)
            out.append(
                {
                    "file": str(path.relative_to(settings.root)),
                    "title": title,
                    "selection": selection,
                    "summary": summary,
                    "observations": len(rows),
                    "repeated": duplicates(rows),
                    "tasks": {task: {mode: _row(row) for mode, row in modes.items()} for task, modes in by.items()},
                }
            )
        return sorted(out, key=lambda experiment: experiment["selection"] != "all")

    def run(self, exp_dir: str) -> dict:
        return _load_run(str(safe_dir(exp_dir)))


def _row(r):
    return {k: r[k] for k in ("success", "steps", "llm_steps", "replayed_steps", "input_tokens", "seconds")} | {
        "exp_dir": rel_run_dir(r["exp_dir"]),
        "available": (RESULTS / rel_run_dir(r["exp_dir"]) / "summary_info.json").is_file(),
    }


def safe_dir(exp_dir: str) -> Path:
    d = (RESULTS / exp_dir).resolve()
    if RESULTS.resolve() not in d.parents or not (d / "summary_info.json").exists():
        raise InvalidArgument("not a run directory")
    return d


@lru_cache(maxsize=64)
def _load_run(d: str) -> dict:
    d = Path(d)
    steps, log = [], []
    files = sorted(d.glob("step_*.pkl.gz"), key=lambda f: int(f.name.split("_")[1].split(".")[0]))
    infos = [pickle.load(gzip.open(f)) for f in files]
    for i, s in enumerate(infos):
        if not s.action:
            continue
        nxt = infos[i + 1].obs if i + 1 < len(infos) else None
        extra = (s.agent_info or {}).get("extra_info") or {}
        pm = extra.get("pathmemory") or {}
        log = pm.get("log", log)
        st = state_of(s.obs)
        steps.append(
            {
                "n": i,
                "url": s.obs["url"],
                "page": st.key,
                "action": semantic_step(s.action, s.obs, st.bindings).text(),
                "source": pm.get("source", "llm"),
                "think": (s.agent_info or {}).get("think") or "",
                "error": (nxt or {}).get("last_action_error") or "",
                "screenshot": (d / f"screenshot_step_{i}.png").exists(),
            }
        )
    summary = json.loads((d / "summary_info.json").read_text())
    obs0 = infos[0].obs
    goal = obs0.get("goal") or next(
        (m.get("text", "") for m in (obs0.get("goal_object") or []) if m.get("type") == "text"), ""
    )
    return {
        "dir": str(d.relative_to(RESULTS)),
        "goal": goal,
        "success": summary.get("cum_reward", 0) > 0,
        "tokens": summary.get("stats.cum_input_tokens", 0),
        "steps": steps,
        "events": log,
    }
