"""Build memory from saved AgentLab runs (successful trajectories only).

Reads step_*.pkl.gz from experiment dirs, so memory can be rebuilt without
re-running the LLM. Writes both stores from the same trajectories:
  - FalkorDB graph (states, verified navigation edges, worksites)
  - flat trace store (AWM-style raw trajectories, for the baseline)
"""

import gzip
import hashlib
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


def ingest(exp_dirs: list[Path], graph: GraphMemory, flat_path: Path = FLAT_STORE, provenance: bool = False) -> dict:
    """provenance=True tags every edge with the episode (run directory name) that showed it, and stores each
    episode's navigation steps in the flat store (used by the flat-replay baseline)."""
    flat_path = Path(flat_path)
    flat = json.loads(flat_path.read_text()) if flat_path.exists() else []
    seen = {t["task_id"] for t in flat}
    added = 0
    for d in exp_dirs:
        tr = trajectory(Path(d))
        if not tr:
            continue
        episode = Path(d).name if provenance else None
        nav = []
        spec = TASKS_BY_ID[tr["task_id"]]
        rows = tr["rows"]
        # Every verified navigation click becomes an edge, wherever it happens (detours and repairs included).
        # The work page is where the trajectory's final run of non-navigation actions took place.
        worksite, work_steps, pending = None, [], []
        for r in rows:
            step, moved = r["step"], r["src"].key != r["dst"].key
            if step.kind == "click" and r["ok"] and moved and step.navigational:
                eid = graph.record_transition(r["src"], step, r["dst"], ok=True, pre=pending, source=episode)
                nav.append({"eid": eid, "src": r["src"].key, "dst": r["dst"].key, "role": step.role, "name": step.name,
                            "scope": step.scope, "pre": [f"{p.role}|{p.name}|{p.scope}" for p in pending]})
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
            entry = {"task_id": spec.id, "goal": spec.goal,
                     "steps": [{"url": r["url"], "action": r["raw_text"]} for r in rows]}
            if provenance:
                entry.update(episode=episode, nav=nav, worksite=worksite.key if worksite else None,
                             work_steps=work_steps[:8])
            flat.append(entry)
            seen.add(spec.id)
        added += 1
    flat_path.parent.mkdir(parents=True, exist_ok=True)
    flat_path.write_text(json.dumps(flat, indent=1))
    return {"trajectories": added, **graph.stats()}


def _sha_files(files) -> str:
    h = hashlib.sha256()
    for f in sorted(files):
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def run_goal(exp_dir: Path) -> str:
    goal = pickle.load(gzip.open(exp_dir / "goal_object.pkl.gz"))
    text = next((m.get("text", "") for m in goal or [] if m.get("type") == "text"), "")
    return text.split(" When you are done, send me")[0]


def build_memory(exp_dirs: list[Path], graph: GraphMemory, flat_path: Path, forbidden_tasks: set[str]) -> dict:
    """A fresh memory (graph + flat store) from explicitly named episodes, with a manifest proving what went in.

    Refuses episodes of forbidden (test) tasks and episodes whose goal differs from the task's current definition.
    """
    from pathmemory.run import task_sha  # run imports this module

    episodes = []
    for d in (Path(x).resolve() for x in exp_dirs):
        exp_args = pickle.load(open(d / "exp_args.pkl", "rb"))
        task_id = exp_args.env_args.task_name.removeprefix("pathmemory.")
        if task_id in forbidden_tasks:
            raise ValueError(f"{d.name}: {task_id} is a held-out task; it must not enter training memory")
        goal = run_goal(d)
        if goal != TASKS_BY_ID[task_id].goal:
            raise ValueError(f"{d.name}: ran goal {goal!r}, current definition is {TASKS_BY_ID[task_id].goal!r}")
        summary = json.loads((d / "summary_info.json").read_text())
        episodes.append({"episode": d.name, "dir": str(d.relative_to(settings.root)), "task": task_id,
                         "task_sha": task_sha(task_id), "goal_sha": hashlib.sha256(goal.encode()).hexdigest()[:12],
                         "success": summary.get("cum_reward", 0) > 0, "steps": summary.get("n_steps"),
                         "files_sha": _sha_files([*d.glob("step_*.pkl.gz"), d / "summary_info.json",
                                                  d / "exp_args.pkl", d / "goal_object.pkl.gz"])})
    graph.clear()
    Path(flat_path).unlink(missing_ok=True)
    stats = ingest([settings.root / e["dir"] for e in episodes], graph, flat_path, provenance=True)
    used = {x for e in graph.edges() for x in e["sources"] or []}
    for e in episodes:
        e["used"] = e["success"]  # only successful episodes are ingested
        e["edges_taught"] = sum(e["episode"] in (x["sources"] or []) for x in graph.edges())
    assert used <= {e["episode"] for e in episodes}
    return {"graph": graph.name, "fingerprint": graph.fingerprint(), "stats": stats,
            "flat_store": str(Path(flat_path).resolve().relative_to(settings.root)), "flat_sha": _sha_files([Path(flat_path)]),
            "forbidden_tasks": sorted(forbidden_tasks), "episodes": episodes}
