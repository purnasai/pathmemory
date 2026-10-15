"""Demo UI: `uv run python -m pathmemory.ui` then open http://localhost:8795.

Shows the FalkorDB memory graph, every saved run step by step (screenshots, LLM vs replayed steps,
failed edges and the recovery route highlighted on the graph), the result tables, and a live route query.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from pathmemory.service import RESULTS, InvalidArgument, PathMemoryService, _safe_dir

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


def main():
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8795, log_level="warning")


if __name__ == "__main__":
    main()
