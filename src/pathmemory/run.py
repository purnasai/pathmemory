"""Run PathMemory experiments on the local Gitea.

    uv run python -m pathmemory.run smoke profile-3 members-1        # base agent on given tasks
    uv run python -m pathmemory.run learn                            # TRAIN tasks -> build memory
    uv run python -m pathmemory.run eval --modes none flat graph     # TEST tasks, frozen memory
    uv run python -m pathmemory.run ingest results/x/learn/* --keep  # add saved runs to memory
"""

import argparse
import gzip
import json
import pickle
import time
from dataclasses import replace
from pathlib import Path

from agentlab.agents.generic_agent.agent_configs import FLAGS_CUSTOM
from agentlab.agents.generic_agent.generic_agent import GenericAgentArgs
from agentlab.experiments.loop import EnvArgs, ExpArgs
from agentlab.llm.chat_api import OpenAIModelArgs
from bgym import HighLevelActionSetArgs

from pathmemory.agent import PathMemoryAgentArgs
from pathmemory.config import settings
from pathmemory.graph import GraphMemory
from pathmemory.learn import FLAT_STORE, ingest
from pathmemory.site import seed
from pathmemory.site.tasks import HIDE_DASHBOARD_REPO_LINKS, TASKS_BY_ID, register_all

RESULTS = settings.root / "results"

# Memory is learned from TRAIN and frozen; TEST tasks have different templates/targets within the same clusters.
TRAIN = ["members-1", "issues-1", "issues-3", "profile-1", "profile-3", "repos-1", "repos-4", "social-1"]
TEST = ["members-2", "members-3", "members-4", "issues-2", "issues-4", "issues-5", "issues-6", "issues-7",
        "profile-2", "profile-4", "repos-2", "repos-3", "repos-5", "social-2"]
# Learned after TRAIN to give the graph a second way into repos; RECOVERY tasks then run with that way broken.
ALT_TRAIN = ["explore-1", "explore-2"]
RECOVERY = ["members-2", "members-4", "issues-2", "issues-5", "repos-3"]


def base_agent_args() -> GenericAgentArgs:
    model = OpenAIModelArgs(
        model_name=settings.openai_model,
        max_total_tokens=128_000,
        max_input_tokens=100_000,
        max_new_tokens=8_000,
        temperature=1.0,  # gpt-6-luna only accepts the default
    )
    # chat = send_msg_to_user, bid = element actions. No "nav": goto(url) would let any mode skip navigation.
    action = replace(FLAGS_CUSTOM.action, action_set=HighLevelActionSetArgs(subsets=["chat", "bid"], multiaction=False))
    flags = replace(FLAGS_CUSTOM, action=action, use_hints=False, be_cautious=False)
    return GenericAgentArgs(chat_model_args=model, flags=flags)


def agent_args(mode: str):
    return PathMemoryAgentArgs(base_args=base_agent_args(), mode=mode)


def run_task(task_id: str, agent, out_dir: Path, max_steps=15, ui_break=None) -> dict:
    if TASKS_BY_ID[task_id].kind == "mutate":
        seed.reset()
    env_args = EnvArgs(task_name=f"pathmemory.{task_id}", task_seed=0, max_steps=max_steps, headless=True,
                       task_kwargs={"ui_break": ui_break} if ui_break else None)
    exp = ExpArgs(agent_args=agent, env_args=env_args)
    exp.prepare(out_dir)
    t0 = time.time()
    exp.run()
    d = Path(exp.exp_dir)
    summary = json.loads((d / "summary_info.json").read_text())
    log, sources = [], {"llm": 0, "graph": 0}
    for f in sorted(d.glob("step_*.pkl.gz")):
        info = (pickle.load(gzip.open(f)).agent_info or {}).get("extra_info") or {}
        pm = info.get("pathmemory")
        if pm:
            sources[pm["source"]] += 1
            log = pm.get("log", log)
    return {
        "task": task_id, "mode": getattr(agent, "mode", "none"),
        "success": summary.get("cum_reward", 0) > 0, "steps": summary.get("n_steps"),
        "llm_steps": sources["llm"], "replayed_steps": sources["graph"],
        "input_tokens": summary.get("stats.cum_input_tokens", 0), "output_tokens": summary.get("stats.cum_output_tokens", 0),
        "seconds": round(time.time() - t0, 1), "err": summary.get("err_msg"),
        "recovered": any(e["event"] == "recovered" for e in log),
        "edge_failures": sum(e["event"] == "edge_failed" for e in log),
        "log": log, "exp_dir": str(d),
    }


def write(rows, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("phase", choices=["smoke", "learn", "ingest", "eval", "recovery"])
    p.add_argument("tasks", nargs="*")
    p.add_argument("--modes", nargs="+", default=["none", "flat", "graph"])
    p.add_argument("--max-steps", type=int, default=15)
    p.add_argument("--tag", default=time.strftime("%Y%m%d-%H%M%S"))
    p.add_argument("--keep", action="store_true", help="learn: add to existing memory instead of clearing it")
    a = p.parse_args()
    register_all()
    out = RESULTS / a.tag

    if a.phase == "smoke":
        for t in a.tasks:
            r = run_task(t, agent_args("none"), out, a.max_steps)
            print(json.dumps({k: v for k, v in r.items() if k != "log"}))
        return

    if a.phase == "ingest":  # add saved runs (e.g. a repair episode) to memory; tasks = run directories
        graph = GraphMemory()
        if not a.keep:
            graph.clear()
            FLAT_STORE.unlink(missing_ok=True)
        print(json.dumps(ingest([Path(t) for t in a.tasks], graph)))
        return

    if a.phase == "learn":
        graph = GraphMemory()
        if not a.keep:
            graph.clear()
            FLAT_STORE.unlink(missing_ok=True)
        rows = [run_task(t, agent_args("none"), out / "learn", a.max_steps) for t in (a.tasks or TRAIN)]
        write(rows, out / "learn.jsonl")
        print(json.dumps(ingest([Path(r["exp_dir"]) for r in rows], graph)))
        for r in rows:
            print(r["task"], "OK" if r["success"] else "FAIL", r["steps"])
        return

    recovery = a.phase == "recovery"
    for t in a.tasks or (RECOVERY if recovery else TEST):
        for mode in a.modes:
            r = run_task(t, agent_args(mode), out / a.phase, a.max_steps,
                         ui_break=HIDE_DASHBOARD_REPO_LINKS if recovery else None)
            write([r], out / f"{a.phase}.jsonl")
            print(f"{t:10} {mode:5} {'OK  ' if r['success'] else 'FAIL'} steps={r['steps']:>2} "
                  f"llm={r['llm_steps']:>2} replay={r['replayed_steps']:>2} tok={r['input_tokens']:>6}")


if __name__ == "__main__":
    main()
