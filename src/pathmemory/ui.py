"""Demo UI: `uv run python -m pathmemory.ui` then open http://localhost:8795.

Shows the FalkorDB memory graph, every saved run step by step (screenshots, LLM vs replayed steps,
failed edges and the recovery route highlighted on the graph), the result tables, and a live route query.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from pathmemory.config import settings
from pathmemory.learn import restore_memory
from pathmemory.service import RESULTS, InvalidArgument, PathMemoryService, _safe_dir
from pathmemory.site.tasks import TASKS, TASKS_BY_ID

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="PathMemory")
svc = PathMemoryService()


def _call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except InvalidArgument as e:
        raise HTTPException(400, str(e)) from e


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/graph")
def graph():
    return svc.graph_view()


@app.get("/api/experiments")
def experiments():
    return svc.experiments()


@app.get("/api/run")
def run(dir: str):
    return _call(svc.run, dir)


@app.get("/api/screenshot")
def screenshot(dir: str, n: int):
    d = _call(_safe_dir, dir)
    f = d / f"screenshot_step_{int(n)}.png"
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f)


@app.get("/api/route")
def route(src: str, dst: str, avoid: list[str] = Query(default=[])):
    return _call(svc.find_route, src, dst, avoid)


# --- live run: one task in a visible browser, started from the UI ------------------------------
LIVE: dict = {"proc": None, "file": None, "log": None}


class LiveRequest(BaseModel):
    task: str
    mode: str = "graph"
    break_ui: bool = False
    learn: bool = True  # write the run's verified steps to FalkorDB if it succeeds


@app.get("/api/tasks")
def tasks():
    return [{"id": t.id, "kind": t.kind, "goal": t.goal} for t in TASKS]


@app.post("/api/live")
def live_start(req: LiveRequest):
    if req.task not in TASKS_BY_ID or req.mode not in ("none", "flat", "graph"):
        raise HTTPException(400, "unknown task or mode")
    if LIVE["proc"] and LIVE["proc"].poll() is None:
        raise HTTPException(409, "a live run is already going")
    tag = time.strftime("live-%Y%m%d-%H%M%S")
    out = RESULTS / tag
    out.mkdir(parents=True, exist_ok=True)
    LIVE["file"], LIVE["log"] = out / "live.json", out / "run.log"
    cmd = [sys.executable, "-m", "pathmemory.run", "live", req.task, "--mode", req.mode, "--tag", tag,
           "--live-file", str(LIVE["file"])] + (["--break-ui"] if req.break_ui else []) + (["--learn"] if req.learn else [])
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
        return restore_memory(svc.graph)
    except ValueError as e:  # no live run has learned anything yet
        raise HTTPException(400, str(e)) from e


def main():
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8795, log_level="warning")


if __name__ == "__main__":
    main()
