"""Build memory from saved AgentLab runs (successful trajectories only).

Reads step_*.pkl.gz from experiment dirs, so memory can be rebuilt without
re-running the LLM. Writes both stores from the same trajectories:
  - FalkorDB graph (states, verified navigation edges, worksites)
  - flat trace store (AWM-style raw trajectories, for the baseline)
"""

import gzip
import json
import pickle
from pathlib import Path

from pathmemory.config import settings
from pathmemory.graph import GraphMemory
from pathmemory.site.tasks import TASKS_BY_ID
from pathmemory.state import POPUP_ROLES, semantic_step, state_of

FLAT_STORE = settings.root / "results" / "flat_memory.json"
IGNORED_KINDS = {"send_msg_to_user", "noop", "scroll", "press", "clear", "focus"}
# Live runs learn into the main memory. The memory the v1 experiments used is copied here first.
BACKUP_GRAPH = "pathmemory_v1"
FLAT_BACKUP = settings.root / "results" / "flat_memory.v1.json"


def backup_memory(graph: GraphMemory) -> bool:
    """Keep a copy of both memories before the first live write. Returns True if a copy was made now."""
    made = graph.backup(BACKUP_GRAPH)
    if FLAT_STORE.exists() and not FLAT_BACKUP.exists():
        FLAT_BACKUP.write_text(FLAT_STORE.read_text())
    return made


def restore_memory(graph: GraphMemory) -> dict:
    graph.restore(BACKUP_GRAPH)
    if FLAT_BACKUP.exists():
        FLAT_STORE.write_text(FLAT_BACKUP.read_text())
    return graph.stats()


def memory_diff(before: dict, after: dict) -> dict:
    """What a run wrote to the graph: new pages and steps, steps confirmed again, failures recorded."""
    new_steps, reinforced, failed = [], [], []
    for eid, e in after["edges"].items():
        b = before["edges"].get(eid)
        row = {"eid": eid, "src": e["src"], "name": e["name"], "dst": e["dst"]}
        if b is None:
            new_steps.append(row)
            continue
        if e["successes"] > b["successes"]:
            reinforced.append({**row, "successes": e["successes"], "by": e["successes"] - b["successes"]})
        if e["failures"] > b["failures"]:
            failed.append({**row, "failures": e["failures"], "by": e["failures"] - b["failures"]})
    return {"new_pages": sorted(after["states"] - before["states"]), "new_steps": new_steps,
            "reinforced": reinforced, "failures": failed, "new_tasks": sorted(after["tasks"] - before["tasks"])}


def load_steps(exp_dir: Path):
    steps = []
    for i in range(1000):
        f = exp_dir / f"step_{i}.pkl.gz"
        if not f.exists():
            break
        steps.append(pickle.load(gzip.open(f)))
    return steps


def trajectory(exp_dir: Path) -> dict | None:
    summary = json.loads((exp_dir / "summary_info.json").read_text())
    if summary.get("cum_reward", 0) <= 0:
        return None
    steps = load_steps(exp_dir)
    exp_args = pickle.load(open(exp_dir / "exp_args.pkl", "rb"))
    task_id = exp_args.env_args.task_name.removeprefix("pathmemory.")
    rows = []
    for a, b in zip(steps, steps[1:]):
        if not a.action:
            continue
        src, dst = state_of(a.obs), state_of(b.obs)
        bindings = {**src.bindings, **dst.bindings}
        step = semantic_step(a.action, a.obs, bindings, scope_bindings=src.bindings)
        rows.append({"src": src, "dst": dst, "step": step, "ok": not b.obs.get("last_action_error"),
                     "url": a.obs["url"], "raw": a.action,
                     "raw_text": semantic_step(a.action, a.obs, {}).text()})
    return {"task_id": task_id, "rows": rows}


def ingest(exp_dirs: list[Path], graph: GraphMemory) -> dict:
    flat = json.loads(FLAT_STORE.read_text()) if FLAT_STORE.exists() else []
    seen = {t["task_id"] for t in flat}
    added = 0
    for d in exp_dirs:
        tr = trajectory(Path(d))
        if not tr:
            continue
        spec = TASKS_BY_ID[tr["task_id"]]
        rows = tr["rows"]
        # Every verified navigation click becomes an edge, wherever it happens (detours and repairs included).
        # The work page is where the trajectory's final run of non-navigation actions took place.
        worksite, work_steps, pending = None, [], []
        for r in rows:
            step, moved = r["step"], r["src"].key != r["dst"].key
            if step.kind == "click" and r["ok"] and moved and step.navigational:
                graph.record_transition(r["src"], step, r["dst"], ok=True, pre=pending)
                worksite, work_steps, pending = None, [], []
                continue
            if step.kind == "click" and r["ok"] and not moved and step.role in POPUP_ROLES:
                pending.append(step)  # e.g. opens a dropdown; needed before the next edge
                continue
            if step.kind in IGNORED_KINDS:
                continue
            if worksite is None or r["src"].key != worksite.key:
                worksite, work_steps = r["src"], [p.text() for p in pending]
                pending = []
            work_steps.append(step.text())
        if worksite is None and rows:  # nothing changed data: the work page is where the agent ended
            worksite = rows[-1]["src"] if rows[-1]["step"].kind == "send_msg_to_user" else rows[-1]["dst"]
            work_steps = [p.text() for p in pending]
        if worksite:
            graph.record_worksite(spec.id, spec.goal, spec.cluster, worksite, work_steps[:8])
        if spec.id not in seen:
            flat.append({"task_id": spec.id, "goal": spec.goal,
                         "steps": [{"url": r["url"], "action": r["raw_text"]} for r in rows]})
            seen.add(spec.id)
        added += 1
    FLAT_STORE.parent.mkdir(parents=True, exist_ok=True)
    FLAT_STORE.write_text(json.dumps(flat, indent=1))
    return {"trajectories": added, **graph.stats()}
