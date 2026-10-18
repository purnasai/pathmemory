"""Run PathMemory experiments on the local Gitea.

    uv run python -m pathmemory.run smoke profile-3 members-1        # base agent on given tasks
    uv run python -m pathmemory.run learn                            # TRAIN tasks -> build memory
    uv run python -m pathmemory.run eval --modes none flat graph     # TEST tasks, frozen memory snapshot
    uv run python -m pathmemory.run ingest results/x/learn/* --keep  # add saved runs to memory
    uv run python -m pathmemory.run live members-4 --break-ui --learn # visible run; successful run is learned
    uv run python -m pathmemory.run restore-memory                   # undo live learning (back to v1 memory)
"""

import argparse
import gzip
import hashlib
import json
import pickle
import shutil
import time
from dataclasses import replace
from pathlib import Path

from agentlab.agents.generic_agent.agent_configs import FLAGS_CUSTOM
from agentlab.agents.generic_agent.generic_agent import GenericAgentArgs
from agentlab.experiments.loop import EnvArgs, ExpArgs
from agentlab.llm.chat_api import OpenAIModelArgs
from bgym import HighLevelActionSetArgs

from pathmemory.agent import PathMemoryAgentArgs, write_json
from pathmemory.config import settings
from pathmemory.graph import GraphMemory
from pathmemory.learn import FLAT_STORE, backup_memory, ingest, memory_diff, restore_memory
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


def base_agent_args(demo: bool = False) -> GenericAgentArgs:
    model = OpenAIModelArgs(
        model_name=settings.openai_model,
        max_total_tokens=128_000,
        max_input_tokens=100_000,
        max_new_tokens=8_000,
        temperature=1.0,  # gpt-6-luna only accepts the default
    )
    # chat = send_msg_to_user, bid = element actions. No "nav": goto(url) would let any mode skip navigation.
    # demo=True animates each click inside the page (live runs in a visible browser)
    action = replace(FLAGS_CUSTOM.action, action_set=HighLevelActionSetArgs(
        subsets=["chat", "bid"], multiaction=False, demo_mode="default" if demo else None))
    flags = replace(FLAGS_CUSTOM, action=action, use_hints=False, be_cautious=False)
    return GenericAgentArgs(chat_model_args=model, flags=flags)


# Evaluation never touches the memory it is scored against: before every graph-mode trial the
# designated snapshot is copied into this working graph, and the agent only reads it.
EVAL_WORK_GRAPH = "pathmemory_eval_work"
ROW_SCHEMA = 2


def agent_args(mode: str, **kw):
    return PathMemoryAgentArgs(base_args=base_agent_args(), mode=mode, **kw)


def task_sha(task_id: str) -> str:
    """Fingerprint of a task definition (goal and checker), so two runs under one id but different
    definitions are never pooled silently."""
    s = TASKS_BY_ID[task_id]
    cells = [repr(c.cell_contents) for c in (getattr(s.check, "__closure__", None) or [])]
    blob = json.dumps([s.goal, s.kind, s.answer, s.url_pattern, getattr(s.check, "__qualname__", None), cells])
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def file_sha(path) -> str | None:
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.exists() else None


def usage(summary: dict) -> dict:
    """Model usage from AgentLab's summary. stats.cum_input_tokens is AgentLab's own episode total (its tracker
    sees every completion, chooser included); the pm_* keys are PathMemory's per-role counts of the same calls."""
    def cum(k):
        return int(summary.get(f"stats.cum_{k}") or 0)
    roles = {r: {k: cum(f"pm_{r}_{k}") for k in ("calls", "api_attempts", "input_tokens", "output_tokens")}
             for r in ("chooser", "base")}
    total_in, total_out = cum("input_tokens"), cum("output_tokens")
    consistent = (roles["chooser"]["input_tokens"] + roles["base"]["input_tokens"] == total_in
                  and roles["chooser"]["output_tokens"] + roles["base"]["output_tokens"] == total_out)
    return {
        "chooser_calls": roles["chooser"]["calls"], "base_calls": roles["base"]["calls"],
        "model_calls": roles["chooser"]["calls"] + roles["base"]["calls"],
        "api_attempts": roles["chooser"]["api_attempts"] + roles["base"]["api_attempts"],
        "input_tokens": total_in, "output_tokens": total_out,
        "chooser_input_tokens": roles["chooser"]["input_tokens"], "chooser_output_tokens": roles["chooser"]["output_tokens"],
        "base_input_tokens": roles["base"]["input_tokens"], "base_output_tokens": roles["base"]["output_tokens"],
        "accounting_consistent": consistent,
        "agent_seconds": round(float(summary.get("stats.cum_agent_elapsed") or 0), 1),
        "env_seconds": round(float(summary.get("stats.cum_step_elapsed") or 0), 1),
    }


def reset_site(expected: str | None = None) -> str:
    """Fresh Gitea fixture; raises if it does not match the fixture the batch started from."""
    seed.reset()
    fp = seed.fingerprint()
    if expected and fp != expected:
        raise RuntimeError(f"Gitea fixture after reset is {fp}, expected {expected}: refusing to run on drifted state")
    return fp


def run_task(task_id: str, agent, out_dir: Path, max_steps=15, ui_break=None, headless=True, slow_mo=None,
             reset: bool | None = None, fixture: str | None = None) -> dict:
    """reset=None keeps the demo behaviour (reset only before data-changing tasks); experiments pass True."""
    if reset or (reset is None and TASKS_BY_ID[task_id].kind == "mutate"):
        fixture = reset_site(fixture)
    env_args = EnvArgs(task_name=f"pathmemory.{task_id}", task_seed=0, max_steps=max_steps, headless=headless,
                       slow_mo=slow_mo, task_kwargs={"ui_break": ui_break} if ui_break else None)
    exp = ExpArgs(agent_args=agent, env_args=env_args)
    exp.prepare(out_dir)
    t0 = time.time()
    exp.run()
    seconds = round(time.time() - t0, 1)
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
        "schema": ROW_SCHEMA, "task": task_id, "task_sha": task_sha(task_id), "goal": TASKS_BY_ID[task_id].goal,
        "mode": getattr(agent, "mode", "none"),
        "success": summary.get("cum_reward", 0) > 0, "steps": summary.get("n_steps"),
        # browser steps by who chose the action; model calls are counted separately (chooser + base, incl. retries)
        "llm_steps": sources["llm"], "replayed_steps": sources["graph"],
        **usage(summary),
        "seconds": seconds, "err": summary.get("err_msg"),
        "recovered": any(e["event"] == "recovered" for e in log),
        "edge_failures": sum(e["event"] == "edge_failed" for e in log),
        "fixture": fixture, "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0)),
        "log": log, "exp_dir": str(d),
    }


def write(rows, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("phase", choices=["smoke", "learn", "ingest", "eval", "recovery", "live", "restore-memory"])
    p.add_argument("tasks", nargs="*")
    p.add_argument("--modes", nargs="+", default=["none", "flat", "graph"])
    p.add_argument("--max-steps", type=int, default=15)
    p.add_argument("--tag", default=time.strftime("%Y%m%d-%H%M%S"))
    p.add_argument("--keep", action="store_true", help="learn: add to existing memory instead of clearing it")
    p.add_argument("--mode", default="graph", help="live: memory mode")
    p.add_argument("--break-ui", action="store_true", help="live: hide the dashboard repo links")
    p.add_argument("--live-file", help="live: progress JSON for the demo UI")
    p.add_argument("--learn", action="store_true", help="live: write the run's verified steps to memory if it succeeds")
    p.add_argument("--snapshot", default="pathmemory",
                   help="eval/recovery: memory graph to evaluate from; it is copied, never written")
    a = p.parse_args()
    register_all()
    out = RESULTS / a.tag

    if a.phase == "smoke":
        for t in a.tasks:
            r = run_task(t, agent_args("none"), out, a.max_steps)
            print(json.dumps({k: v for k, v in r.items() if k != "log"}))
        return

    if a.phase == "restore-memory":
        print(json.dumps(restore_memory(GraphMemory())))
        return

    if a.phase == "live":  # one task in a visible, slowed-down browser; progress streamed to --live-file
        task, live_file = a.tasks[0], a.live_file or str(out / "live.json")
        out.mkdir(parents=True, exist_ok=True)
        write_json(live_file, {"status": "starting", "mode": a.mode, "steps": [], "events": [],
                               "note": "resetting the site" if TASKS_BY_ID[task].kind == "mutate" else "opening browser"})
        agent = PathMemoryAgentArgs(base_args=base_agent_args(demo=True), mode=a.mode, live_file=live_file,
                                    record_failures=a.learn)  # memory is written only with --learn
        graph = GraphMemory() if a.learn else None
        if graph:
            backup_memory(graph)
            before = graph.snapshot()  # taken before the run: graph mode also records failed steps while running
        try:
            r = run_task(task, agent, out / "live", a.max_steps, headless=False, slow_mo=700,
                         ui_break=HIDE_DASHBOARD_REPO_LINKS if a.break_ui else None)
        except Exception as e:  # noqa: BLE001 - shown in the UI
            write_json(live_file, {**json.loads(Path(live_file).read_text()), "status": "error", "note": str(e)[:300]})
            raise
        memory = None
        if graph:
            # Same rule as the experiments: only a successful run becomes memory (both graph and flat store).
            if r["success"]:
                ingest([Path(r["exp_dir"])], graph)
            memory = {**memory_diff(before, graph.snapshot()), "learned": r["success"], "stats": graph.stats()}
        final = json.loads(Path(live_file).read_text())
        write_json(live_file, {**final, "status": "done", "success": r["success"], "tokens": r["input_tokens"],
                               "seconds": r["seconds"], "dir": str(Path(r["exp_dir"]).relative_to(RESULTS)),
                               "memory": memory})
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
        fixture = reset_site()
        rows = [run_task(t, agent_args("none"), out / "learn", a.max_steps, reset=True, fixture=fixture)
                for t in (a.tasks or TRAIN)]
        write(rows, out / "learn.jsonl")
        print(json.dumps(ingest([Path(r["exp_dir"]) for r in rows], graph)))
        for r in rows:
            print(r["task"], "OK" if r["success"] else "FAIL", r["steps"])
        return

    recovery = a.phase == "recovery"
    # Frozen inputs for the whole batch: graph snapshot (copied per trial), flat store (copied once), site fixture.
    snapshot = GraphMemory(a.snapshot)
    snap_fp = snapshot.fingerprint()
    out.mkdir(parents=True, exist_ok=True)
    flat_copy = out / "flat_snapshot.json"
    if FLAT_STORE.exists():
        shutil.copyfile(FLAT_STORE, flat_copy)
    fixture = reset_site()
    work = GraphMemory(EVAL_WORK_GRAPH)
    for t in a.tasks or (RECOVERY if recovery else TEST):
        for mode in a.modes:
            work.restore(a.snapshot)
            before = work.fingerprint()
            assert before == snap_fp, "working copy differs from the snapshot"
            r = run_task(t, agent_args(mode, graph_name=EVAL_WORK_GRAPH, flat_store=str(flat_copy)), out / a.phase,
                         a.max_steps, ui_break=HIDE_DASHBOARD_REPO_LINKS if recovery else None, reset=True,
                         fixture=fixture)
            after = work.fingerprint()
            if snapshot.fingerprint() != snap_fp:
                raise RuntimeError(f"memory snapshot {a.snapshot!r} changed during evaluation")
            r["memory"] = {"snapshot": a.snapshot, "fingerprint": snap_fp, "unchanged": after == before,
                           "flat_store_sha": file_sha(flat_copy)}
            write([r], out / f"{a.phase}.jsonl")
            print(f"{t:10} {mode:5} {'OK  ' if r['success'] else 'FAIL'} steps={r['steps']:>2} "
                  f"llm_steps={r['llm_steps']:>2} replay={r['replayed_steps']:>2} calls={r['model_calls']:>2} "
                  f"tok={r['input_tokens']:>6}")


if __name__ == "__main__":
    main()
