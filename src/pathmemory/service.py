"""One read/write API over the memory graph and the saved runs, shared by the demo UI and the MCP server.

Every graph operation is a fixed, parameterised Cypher query; nothing accepts Cypher from outside.
"""

import gzip
import json
import pickle
from functools import lru_cache
from pathlib import Path

from pathmemory.config import settings
from pathmemory.graph import GraphMemory
from pathmemory.report import duplicates, load_rows, rel_run_dir, select, summarize
from pathmemory.state import Step, route_template, semantic_step, state_of

RESULTS = settings.root / "results"

ROUTE_CYPHER = """MATCH (a:State {key:$src}), (b:State {key:$dst})
MATCH p = (a)-[:ACT*1..6]->(b)
WHERE all(r IN relationships(p) WHERE r.successes > 0 AND NOT r.eid IN $banned)
RETURN [n IN nodes(p) | n.key], [r IN relationships(p) | r.name], length(p) AS hops,
       reduce(f = 0, r IN relationships(p) | f + r.failures) AS fails
ORDER BY hops, fails LIMIT 3"""

EXPERIMENTS = [
    ("v1/eval.jsonl", "Normal UI — 14 held-out tasks"),
    ("v1/recovery.jsonl", "UI break — before any repair is learned"),
    ("v1-repaired/recovery.jsonl", "UI break — after learning from one repair episode"),
    ("v2-normal/eval.jsonl", "v2 — issues-2, normal UI, 4 modes x 5 trials (v2 memory, no test-task episodes)"),
    ("v2-broken/eval.jsonl", "v2 — issues-2, dashboard repo links hidden: composed route via Explore"),
    ("v2-ablation/eval.jsonl", "v2 — same, graph with the Explore→repo bridge step removed"),
]
# The published v1 tables used the latest attempt of a repeated (task, mode); the UI says so and lists the others.
EXPERIMENT_SELECTION = "latest"


class InvalidArgument(ValueError):
    pass


class PathMemoryService:
    def __init__(self, graph_name: str = "pathmemory"):
        self.graph = GraphMemory(graph_name)

    # --- memory graph -----------------------------------------------------------
    def graph_view(self) -> dict:
        nodes = [{"key": d["key"], "title": d["title"], "goals": d["goals"]} for d in self.graph.destinations()]
        edges = [
            {"eid": e, "src": a, "dst": b, "role": role, "name": name, "pre": pre or [],
             "successes": s, "failures": f}
            for a, e, role, name, pre, s, f, b in self.graph.q(
                "MATCH (a:State)-[r:ACT]->(b:State) "
                "RETURN a.key, r.eid, r.role, r.name, r.pre, r.successes, r.failures, b.key")
        ]
        return {"nodes": nodes, "edges": edges, "stats": self.graph.stats()}

    def pages(self) -> list[dict]:
        return self.graph.destinations()

    def resolve(self, url: str) -> dict:
        key, route, bindings = route_template(url)
        return {"key": key, "route": route, "bindings": bindings, "known": self.graph.has_state(key)}

    def page_memory(self, key: str) -> dict:
        self._known(key)
        site = next(d for d in self.graph.destinations() if d["key"] == key)
        out = self.graph.q("MATCH (:State {key:$k})-[r:ACT]->(b:State) RETURN r.role, r.name, b.key, r.successes, "
                           "r.failures", k=key)
        site["leaves_to"] = [{"role": r, "name": n, "to": b, "successes": s, "failures": f} for r, n, b, s, f in out]
        return site

    def find_route(self, src: str, dst: str, avoid: list[str] | None = None) -> dict:
        self._known(src)
        self._known(dst)
        routes = self.graph.routes(src, dst, banned=avoid or [])
        return {"cypher": ROUTE_CYPHER, "routes": routes}

    def record_step(self, from_url: str, role: str, name: str, to_url: str) -> dict:
        if role not in ("link", "tab", "menuitem"):
            raise InvalidArgument("only navigation clicks (link, tab, menuitem) are stored as reusable steps")
        src, dst = route_template(from_url), route_template(to_url)
        from pathmemory.state import State, templatize
        b = {**src[2], **dst[2]}
        eid = self.graph.record_transition(State(src[0], src[1], src[2]), Step("click", role, templatize(name, b)),
                                           State(dst[0], dst[1], dst[2]))
        return {"eid": eid, "from": src[0], "to": dst[0], "name": templatize(name, b)}

    def report_failure(self, eid: str) -> dict:
        if not self.graph.q("MATCH ()-[r:ACT {eid:$e}]->() RETURN r.eid", e=eid):
            raise InvalidArgument(f"unknown step id {eid!r}")
        self.graph.mark_failure(eid)
        return {"eid": eid, "failures": self.graph.q("MATCH ()-[r:ACT {eid:$e}]->() RETURN r.failures", e=eid)[0][0]}

    def _known(self, key):
        if not self.graph.has_state(key):
            raise InvalidArgument(f"unknown page {key!r}; call list_pages or resolve_url first")

    # --- saved runs -------------------------------------------------------------
    def experiments(self) -> list[dict]:
        out = []
        for rel, title in EXPERIMENTS:
            p = RESULTS / rel
            if p.exists():
                rows = load_rows(p)
                by = select(rows, EXPERIMENT_SELECTION)
                out.append({"file": rel, "title": title, "selection": EXPERIMENT_SELECTION, "summary": summarize(by),
                            "observations": len(rows), "repeated": duplicates(rows),
                            "tasks": {t: {m: _row(r) for m, r in modes.items()} for t, modes in by.items()}})
        return out

    def run(self, exp_dir: str) -> dict:
        d = _safe_dir(exp_dir)
        return _load_run(str(d))


def _row(r):
    return {k: r[k] for k in ("success", "steps", "llm_steps", "replayed_steps", "input_tokens", "seconds")} | {
        "exp_dir": rel_run_dir(r["exp_dir"])}




def _safe_dir(exp_dir: str) -> Path:
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
        steps.append({
            "n": i, "url": s.obs["url"], "page": st.key, "action": semantic_step(s.action, s.obs, st.bindings).text(),
            "source": pm.get("source", "llm"), "think": (s.agent_info or {}).get("think") or "",
            "error": (nxt or {}).get("last_action_error") or "", "screenshot": (d / f"screenshot_step_{i}.png").exists(),
        })
    summary = json.loads((d / "summary_info.json").read_text())
    obs0 = infos[0].obs
    goal = obs0.get("goal") or next((m.get("text", "") for m in (obs0.get("goal_object") or [])
                                     if m.get("type") == "text"), "")
    return {"dir": str(d.relative_to(RESULTS)), "goal": goal, "success": summary.get("cum_reward", 0) > 0,
            "tokens": summary.get("stats.cum_input_tokens", 0), "steps": steps, "events": log}
