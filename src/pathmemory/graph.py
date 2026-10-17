"""FalkorDB procedural memory.

    (:State {key, route, title})
    (:State)-[:ACT {eid, kind, role, name, pre, successes, failures}]->(:State)   verified navigation step
        (pre = clicks that must happen first on the same page, e.g. opening a dropdown)
    (:Task {id, goal, cluster})-[:WORKED_AT {steps}]->(:State)               where a past task did its real work

Routes are found with a bounded variable-length Cypher match, so a route can be
stitched together from edges that were learned in different tasks.
"""

import hashlib

from falkordb import FalkorDB

from pathmemory.config import settings
from pathmemory.state import State, Step


def edge_id(src: str, step: Step, dst: str) -> str:
    return hashlib.sha1(f"{src}|{step.kind}|{step.role}|{step.name}|{dst}".encode()).hexdigest()[:12]


class GraphMemory:
    def __init__(self, name: str = "pathmemory"):
        self.name = name
        self.db = FalkorDB(host=settings.falkordb_host, port=settings.falkordb_port)
        self.g = self.db.select_graph(name)

    def q(self, cypher: str, **params):
        return self.g.query(cypher, params).result_set

    def clear(self):
        try:
            self.g.delete()
        except Exception:
            pass

    # --- writes -------------------------------------------------------------
    def add_state(self, s: State):
        self.q("MERGE (s:State {key:$key}) ON CREATE SET s.route=$route, s.title=$title", key=s.key, route=s.route,
               title=s.title)

    def record_transition(self, src: State, step: Step, dst: State, ok: bool = True, pre: list[Step] = ()) -> str:
        self.add_state(src)
        self.add_state(dst)
        eid = edge_id(src.key, step, dst.key)
        self.q(
            """MATCH (a:State {key:$src}), (b:State {key:$dst})
               MERGE (a)-[r:ACT {eid:$eid}]->(b)
               ON CREATE SET r.kind=$kind, r.role=$role, r.name=$name, r.scope=$scope, r.pre=$pre, r.successes=0, r.failures=0
               SET r.successes = r.successes + $s, r.failures = r.failures + $f""",
            src=src.key, dst=dst.key, eid=eid, kind=step.kind, role=step.role, name=step.name, scope=step.scope,
            s=int(ok), f=int(not ok), pre=[f"{p.role}|{p.name}|{p.scope}" for p in pre],
        )
        return eid

    def mark_failure(self, eid: str):
        self.q("MATCH ()-[r:ACT {eid:$eid}]->() SET r.failures = r.failures + 1", eid=eid)

    def record_worksite(self, task_id: str, goal: str, cluster: str, state: State, steps: list[str]):
        self.add_state(state)
        self.q(
            """MERGE (t:Task {id:$id}) SET t.goal=$goal, t.cluster=$cluster
               WITH t MATCH (s:State {key:$key})
               MERGE (t)-[w:WORKED_AT]->(s) SET w.steps=$steps""",
            id=task_id, goal=goal, cluster=cluster, key=state.key, steps=steps,
        )

    # --- reads --------------------------------------------------------------
    def worksites(self) -> list[dict]:
        rows = self.q(
            """MATCH (t:Task)-[w:WORKED_AT]->(s:State)
               RETURN s.key, s.title, collect(t.goal), collect(w.steps)""")
        return [{"key": k, "title": t, "goals": g, "steps": st} for k, t, g, st in rows]

    def destinations(self) -> list[dict]:
        """Every known page, with the past tasks (if any) that did their work there."""
        rows = self.q(
            """MATCH (s:State) OPTIONAL MATCH (t:Task)-[w:WORKED_AT]->(s)
               RETURN s.key, s.title, collect(t.goal), collect(w.steps) ORDER BY s.key""")
        return [{"key": k, "title": t, "goals": [x for x in g if x], "steps": st} for k, t, g, st in rows]

    def has_state(self, key: str) -> bool:
        return bool(self.q("MATCH (s:State {key:$k}) RETURN s LIMIT 1", k=key))

    def routes(self, src: str, dst: str, banned: list[str] = (), k: int = 3, max_hops: int = 6) -> list[dict]:
        """Up to k verified routes src -> dst, shortest and least-failed first."""
        if src == dst:
            return [{"keys": [src], "edges": []}]
        rows = self.q(
            f"""MATCH (a:State {{key:$src}}), (b:State {{key:$dst}})
                MATCH p = (a)-[:ACT*1..{int(max_hops)}]->(b)
                WHERE all(r IN relationships(p) WHERE r.successes > 0 AND NOT r.eid IN $banned)
                RETURN [n IN nodes(p) | n.key] AS keys,
                       [r IN relationships(p) | [r.eid, r.kind, r.role, r.name, r.pre, r.scope]] AS edges,
                       length(p) AS hops,
                       reduce(f = 0, r IN relationships(p) | f + r.failures) AS fails
                ORDER BY hops, fails LIMIT $k""",
            src=src, dst=dst, banned=list(banned), k=k,
        )
        return [{"keys": keys, "edges": [dict(zip(("eid", "kind", "role", "name", "pre", "scope"), e)) for e in edges]}
                for keys, edges, _, _ in rows]

    def snapshot(self) -> dict:
        """Pages, tasks and edge counters, so a write can be diffed (see learn.memory_diff)."""
        edges = {eid: {"src": a, "name": n, "dst": b, "successes": s, "failures": f}
                 for eid, a, n, b, s, f in self.q(
                     "MATCH (a:State)-[r:ACT]->(b:State) RETURN r.eid, a.key, r.name, b.key, r.successes, r.failures")}
        return {"edges": edges, "states": {k for (k,) in self.q("MATCH (s:State) RETURN s.key")},
                "tasks": {t for (t,) in self.q("MATCH (t:Task) RETURN t.id")}}

    # --- backup (live runs write to memory; the experiments' graph is kept as a copy) -------------
    def backup(self, copy_name: str) -> bool:
        """Copy this graph to copy_name once; later calls keep the first copy."""
        if copy_name in self.db.list_graphs():
            return False
        self.g.copy(copy_name)
        return True

    def restore(self, copy_name: str):
        if copy_name not in self.db.list_graphs():
            raise ValueError(f"no backup graph {copy_name!r}")
        self.clear()
        self.db.select_graph(copy_name).copy(self.name)

    def stats(self) -> dict:
        n = self.q("MATCH (s:State) RETURN count(s)")[0][0]
        e = self.q("MATCH ()-[r:ACT]->() RETURN count(r)")[0][0]
        t = self.q("MATCH (t:Task) RETURN count(t)")[0][0]
        return {"states": n, "edges": e, "tasks": t}
