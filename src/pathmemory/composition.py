"""Evidence that a route replayed from graph memory is composed from several training episodes.

Inputs are the v2 memory (FalkorDB graph built by `run build-memory`) and its flat store, which keeps each
training episode's own navigation steps. For the composition case (dashboard repo links gone, goal page
/:owner/:repo/issues/new) it records:

  - the Cypher query and the route FalkorDB returns, with the dashboard step banned (what replay does after
    that step fails on the broken page), and the source episodes of every hop
  - for every training episode, whether its own steps contain that route (contiguously, or at all)
  - what flat replay (single-trajectory routes) finds for the same request
  - the same query on the ablated copy (bridge step removed)

    uv run python -m pathmemory.composition > docs/evidence/v2/composition.json
"""

import json
import sys

from pathmemory.agent import FlatRoutes
from pathmemory.config import settings
from pathmemory.graph import GraphMemory

GRAPH, ABLATED = "pathmemory_v2", "pathmemory_v2_ablated"
FLAT = settings.root / "docs/evidence/v2/memory/flat_memory.json"
START, GOAL = "/", "/:owner/:repo/issues/new"

ROUTE_CYPHER = """MATCH (a:State {key:$src}), (b:State {key:$dst})
MATCH p = (a)-[:ACT*1..6]->(b)
WHERE all(r IN relationships(p) WHERE r.successes > 0 AND NOT r.eid IN $banned)
RETURN [n IN nodes(p) | n.key] AS keys,
       [r IN relationships(p) | [r.eid, r.role, r.name, r.scope, r.sources]] AS edges,
       length(p) AS hops, reduce(f = 0, r IN relationships(p) | f + r.failures) AS fails
ORDER BY hops, fails LIMIT 3"""


def dashboard_step(g: GraphMemory) -> str:
    [e] = [e for e in g.edges() if e["src"] == "/" and e["dst"] == "/:owner/:repo" and e["name"] == "{owner}/{repo}"]
    return e["eid"]


def bridge_step(g: GraphMemory) -> str:
    [e] = [e for e in g.edges() if e["src"] == "/explore/repos" and e["dst"] == "/:owner/:repo"]
    return e["eid"]


def contains(nav: list[dict], eids: list[str]) -> dict:
    """Does one episode's own step sequence contain the route: as a contiguous run, or every step at all?"""
    seq = [e["eid"] for e in nav]
    contiguous = any(seq[i:i + len(eids)] == eids for i in range(len(seq) - len(eids) + 1))
    return {"contiguous": contiguous, "all_steps_somewhere": set(eids) <= set(seq),
            "steps_of_route_present": [x for x in eids if x in seq]}


def query(g: GraphMemory, banned: list[str]) -> list[dict]:
    rows = g.q(ROUTE_CYPHER, src=START, dst=GOAL, banned=banned)
    return [{"keys": k, "hops": h, "fails": f,
             "edges": [dict(zip(("eid", "role", "name", "scope", "sources"), e)) for e in edges]}
            for k, edges, h, f in rows]


def evidence() -> dict:
    g = GraphMemory(GRAPH)
    dash, bridge = dashboard_step(g), bridge_step(g)
    normal = query(g, [])
    broken = query(g, [dash])
    composed = broken[0]
    eids = [e["eid"] for e in composed["edges"]]
    flat = FlatRoutes(FLAT)
    episodes = {t["episode"]: {"task": t["task_id"], **contains(t["nav"], eids)} for t in flat.store}
    sources_per_hop = [sorted(e["sources"]) for e in composed["edges"]]
    essential = sorted({s[0] for s in sources_per_hop if len(s) == 1})  # hops only one episode taught
    out = {
        "graph": GRAPH, "graph_fingerprint": g.fingerprint(), "flat_store": str(FLAT.relative_to(settings.root)),
        "request": {"from": START, "to": GOAL},
        "cypher": ROUTE_CYPHER,
        "normal_ui": {"banned": [], "routes": normal},
        "broken_ui": {"banned": [dash], "why": "dashboard repo link hidden: replay finds no such link and bans the step",
                      "routes": broken},
        "composed_route": {"keys": composed["keys"], "eids": eids, "sources_per_hop": sources_per_hop,
                           "distinct_source_episodes": sorted({x for s in sources_per_hop for x in s}),
                           "essential_episodes": essential},
        "single_episode_containment": episodes,
        "no_single_episode_contains_route": not any(v["contiguous"] or v["all_steps_somewhere"]
                                                    for v in episodes.values()),
        "flat_replay_routes": {"normal_ui": flat.routes(START, GOAL), "broken_ui": flat.routes(START, GOAL, [dash])},
    }
    names = GraphMemory(GRAPH).db.list_graphs()
    if ABLATED in names:
        a = GraphMemory(ABLATED)
        out["ablation"] = {"graph": ABLATED, "fingerprint": a.fingerprint(), "removed": bridge,
                           "bridge_present": any(e["eid"] == bridge for e in a.edges()),
                           "broken_ui_routes": query(a, [dash]), "normal_ui_routes": query(a, [])}
    return out


if __name__ == "__main__":
    json.dump(evidence(), sys.stdout, indent=1)
