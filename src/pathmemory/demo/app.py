"""Demo UI: `uv run python -m pathmemory.ui` then open http://localhost:8795.

Shows the FalkorDB memory graph, every saved run step by step (screenshots, LLM vs replayed steps,
failed edges and the recovery route highlighted on the graph), the result tables, and a live route query.
"""

import json
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pathmemory.config import settings
from pathmemory.demo.runs import RESULTS, RunService, safe_dir
from pathmemory.learn import restore_memory
from pathmemory.service import InvalidArgument, PathMemoryService
from pathmemory.site.tasks import TASKS, TASKS_BY_ID

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="PathMemory")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
runs = RunService()
# Memories the UI can show. v2 graphs are fingerprinted snapshots: the UI only reads them.
MEMORIES = {"v2": "pathmemory_v2", "v2-ablated": "pathmemory_v2_ablated", "v1": "pathmemory"}
MANIFEST = settings.root / "docs/evidence/v2/memory/manifest.json"
COMPOSITION = settings.root / "docs/evidence/v2/composition.json"


@lru_cache
def _svc(memory: str) -> PathMemoryService:
    if memory not in MEMORIES:
        raise HTTPException(400, f"memory must be one of {list(MEMORIES)}")
    return PathMemoryService(MEMORIES[memory])


def _call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except InvalidArgument as e:
        raise HTTPException(400, str(e)) from e


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/demo-video")
def demo_video():
    video = settings.root / "docs/media/pathmemory-demo.mp4"
    if not video.is_file():
        raise HTTPException(404, "Demo video is included in the source checkout under docs/media.")
    return FileResponse(video, media_type="video/mp4")


@app.get("/api/graph")
def graph(memory: str = "v2"):
    return _svc(memory).graph_view()


@app.get("/api/v2/demo")
def v2_demo():
    """Training episodes (from the manifest) and route queries computed now against FalkorDB."""
    from pathmemory.evaluation.composition import evidence

    manifest = json.loads(MANIFEST.read_text())
    live = evidence()
    recorded = json.loads(COMPOSITION.read_text())
    return {
        "computed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "episodes": [
            {k: e[k] for k in ("episode", "task", "success", "steps", "edges_taught", "task_sha")}
            | {"goal": TASKS_BY_ID[e["task"]].goal}
            for e in manifest["episodes"]
        ],
        "manifest_fingerprint": manifest["fingerprint"],
        "graph_fingerprint": live["graph_fingerprint"],
        "matches_manifest": live["graph_fingerprint"] == manifest["fingerprint"],
        "matches_recorded_evidence": live["composed_route"] == recorded["composed_route"],
        "cypher": live["cypher"],
        "request": live["request"],
        "normal": live["normal_ui"],
        "broken": live["broken_ui"],
        "ablation": live.get("ablation"),
        "composed": live["composed_route"],
        "containment": live["single_episode_containment"],
        "no_single_episode_contains_route": live["no_single_episode_contains_route"],
        "flat_replay": live["flat_replay_routes"],
        "recorded": _recorded_runs(),
    }


def _recorded_runs() -> list[dict]:
    """Trial 1 of each (condition, mode) from the committed v2 evaluation, for replay with screenshots."""
    from pathmemory.evaluation.report import rel_run_dir

    out = []
    for cond in ("normal", "broken", "ablation"):
        for line in (settings.root / f"docs/evidence/v2/runs/{cond}.jsonl").read_text().splitlines():
            r = json.loads(line)
            if r["trial"] == 1:
                out.append(
                    {
                        "condition": cond,
                        "mode": r["mode"],
                        "success": r["success"],
                        "started": r["started"],
                        "dir": rel_run_dir(r["exp_dir"]),
                        "available": (RESULTS / rel_run_dir(r["exp_dir"])).exists(),
                    }
                )
    return out


@app.get("/api/experiments")
def experiments():
    return runs.experiments()


@app.get("/api/run")
def run(dir: str):
    return _call(runs.run, dir)


@app.get("/api/screenshot")
def screenshot(dir: str, n: int):
    d = _call(safe_dir, dir)
    f = d / f"screenshot_step_{int(n)}.png"
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f)


@app.get("/api/route")
def route(src: str, dst: str, avoid: list[str] = Query(default=[]), memory: str = "v2"):
    return _call(_svc(memory).find_route, src, dst, avoid)


# --- live run: one task in a visible browser, started from the UI ------------------------------
LIVE: dict = {"proc": None, "file": None, "log": None}


class LiveRequest(BaseModel):
    task: str
    mode: str = "graph"
    break_ui: bool = False
    learn: bool = True  # write the run's verified steps to FalkorDB if it succeeds (v1 memory only)
    memory: str = "v1"  # v2 / v2-ablated: replay from a working copy of the snapshot, never learn


@app.get("/api/tasks")
def tasks():
    return [{"id": t.id, "kind": t.kind, "goal": t.goal} for t in TASKS]


@app.post("/api/live")
def live_start(req: LiveRequest):
    if req.task not in TASKS_BY_ID or req.mode not in ("none", "flat", "graph") or req.memory not in MEMORIES:
        raise HTTPException(400, "unknown task, mode or memory")
    if LIVE["proc"] and LIVE["proc"].poll() is None:
        raise HTTPException(409, "a live run is already going")
    tag = time.strftime("live-%Y%m%d-%H%M%S")
    out = RESULTS / tag
    out.mkdir(parents=True, exist_ok=True)
    LIVE["file"], LIVE["log"] = out / "live.json", out / "run.log"
    cmd = [
        sys.executable,
        "-m",
        "pathmemory.evaluation.run",
        "live",
        req.task,
        "--mode",
        req.mode,
        "--tag",
        tag,
        "--live-file",
        str(LIVE["file"]),
    ] + (["--break-ui"] if req.break_ui else [])
    if req.memory == "v1":
        cmd += ["--learn"] if req.learn else []
    else:
        cmd += ["--live-snapshot", MEMORIES[req.memory]]
    LIVE["proc"] = subprocess.Popen(cmd, cwd=settings.root, stdout=LIVE["log"].open("w"), stderr=subprocess.STDOUT)
    return {"started": tag}


@app.get("/api/live")
def live_status():
    if not LIVE["file"]:  # server restarted: show the most recent live run, if any
        saved = sorted(RESULTS.glob("live-*/live.json"))
        return json.loads(saved[-1].read_text()) if saved else {"status": "idle"}
    try:
        data = json.loads(LIVE["file"].read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        data = {"status": "starting", "steps": [], "events": []}
    proc = LIVE["proc"]
    if proc and proc.poll() is not None and data.get("status") not in ("done", "error"):
        tail = LIVE["log"].read_text().splitlines()[-5:] if LIVE["log"].exists() else []
        data.update(status="error", note=" | ".join(tail)[-400:])
    return data


@app.post("/api/memory/restore")
def memory_restore():
    """Undo live learning: put back the memory the v1 experiments used."""
    if LIVE["proc"] and LIVE["proc"].poll() is None:
        raise HTTPException(409, "a live run is going")
    try:
        return restore_memory(_svc("v1").graph)
    except ValueError as e:  # no live run has learned anything yet
        raise HTTPException(400, str(e)) from e


def main():
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8795, log_level="warning")


if __name__ == "__main__":
    main()
