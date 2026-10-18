"""FalkorDB procedural memory.

    (:State {key, route, title})
    (:State)-[:ACT {eid, kind, role, name, scope, pre, successes, failures, sources}]->(:State)   verified navigation step
        (pre = clicks that must happen first on the same page, e.g. opening a dropdown;
         sources = ids of the training episodes that showed this step, v2 memory only)
    (:Task {id, goal, cluster})-[:WORKED_AT {steps}]->(:State)               where a past task did its real work

Routes are found with a bounded variable-length Cypher match, so a route can be
stitched together from edges that were learned in different tasks.
"""

import hashlib
import json

from falkordb import FalkorDB

from pathmemory.config import settings
from pathmemory.state import State, Step


def edge_id(src: str, step: Step, dst: str) -> str:
    """Identity of a semantic step. The landmark scope is part of it: "Settings" in the repo header and
    "Settings" in the user menu are different actions even when they land on the same page template."""
    return hashlib.sha1(f"{src}|{step.kind}|{step.role}|{step.name}|{step.scope}|{dst}".encode()).hexdigest()[:12]


class GraphMemory:
    def __init__(self, name: str = "pathmemory"):
        self.name = name
        self.db = FalkorDB(host=settings.falkordb_host, port=settings.falkordb_port)
        self.g = self.db.select_graph(name)

    def q(self, cypher: str, **params):
        return self.g.query(cypher, params).result_set

    def clear(self):
        """Delete an existing graph; connection and server errors propagate to the caller."""
        if self.name in self.db.list_graphs():
            self.g.delete()

    # --- writes -------------------------------------------------------------
    def add_state(self, s: State):
        self.q(
            "MERGE (s:State {key:$key}) ON CREATE SET s.route=$route, s.title=$title",
            key=s.key,
            route=s.route,
            title=s.title,
        )

    def record_transition(
        self, src: State, step: Step, dst: State, ok: bool = True, pre: list[Step] = (), source: str | None = None
    ) -> str:
        """source = id of the episode that showed this step; kept (once) in r.sources as provenance."""
        self.add_state(src)
        self.add_state(dst)
        eid = edge_id(src.key, step, dst.key)
        self.q(
            """MATCH (a:State {key:$src}), (b:State {key:$dst})
               MERGE (a)-[r:ACT {eid:$eid}]->(b)
               ON CREATE SET r.kind=$kind, r.role=$role, r.name=$name, r.scope=$scope, r.pre=$pre, r.successes=0, r.failures=0
               SET r.successes = r.successes + $s, r.failures = r.failures + $f""",
            src=src.key,
            dst=dst.key,
            eid=eid,
            kind=step.kind,
            role=step.role,
            name=step.name,
            scope=step.scope,
            s=int(ok),
            f=int(not ok),
            pre=[f"{p.role}|{p.name}|{p.scope}" for p in pre],
        )
        if source:
            self.q(
                """MATCH ()-[r:ACT {eid:$eid}]->()
                      SET r.sources = CASE WHEN r.sources IS NULL THEN [$src]
                                           WHEN $src IN r.sources THEN r.sources ELSE r.sources + $src END""",
                eid=eid,
                src=source,
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
            id=task_id,
            goal=goal,
            cluster=cluster,
            key=state.key,
            steps=steps,
        )

    # --- reads --------------------------------------------------------------
    def worksites(self) -> list[dict]:
        rows = self.q(
            """MATCH (t:Task)-[w:WORKED_AT]->(s:State)
               RETURN s.key, s.title, collect(t.goal), collect(w.steps)"""
        )
        return [{"key": k, "title": t, "goals": g, "steps": st} for k, t, g, st in rows]

    def destinations(self) -> list[dict]:
        """Every known page, with the past tasks (if any) that did their work there."""
        rows = self.q(
            """MATCH (s:State) OPTIONAL MATCH (t:Task)-[w:WORKED_AT]->(s)
               RETURN s.key, s.title, collect(t.goal), collect(w.steps) ORDER BY s.key"""
        )
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
                       [r IN relationships(p) | [r.eid, r.kind, r.role, r.name, r.pre, r.scope, r.sources]] AS edges,
                       length(p) AS hops,
                       reduce(f = 0, r IN relationships(p) | f + r.failures) AS fails
                ORDER BY hops, fails LIMIT $k""",
            src=src,
            dst=dst,
            banned=list(banned),
            k=k,
        )
        return [
            {
                "keys": keys,
                "edges": [dict(zip(("eid", "kind", "role", "name", "pre", "scope", "sources"), e)) for e in edges],
            }
            for keys, edges, _, _ in rows
        ]

    def edges(self) -> list[dict]:
        """Every step with its counters and provenance, sorted (evidence dumps, provenance checks)."""
        rows = self.q(
            "MATCH (a:State)-[r:ACT]->(b:State) RETURN a.key, r.eid, r.kind, r.role, r.name, r.scope, r.pre, "
            "r.successes, r.failures, r.sources, b.key"
        )
        keys = ("src", "eid", "kind", "role", "name", "scope", "pre", "successes", "failures", "sources", "dst")
        return sorted((dict(zip(keys, r)) for r in rows), key=lambda e: (e["src"], e["dst"], e["eid"]))

    def delete_edge(self, eid: str) -> int:
        """Remove one step (ablation on a copied graph)."""
        n = self.q("MATCH ()-[r:ACT {eid:$eid}]->() RETURN count(r)", eid=eid)[0][0]
        self.q("MATCH ()-[r:ACT {eid:$eid}]->() DELETE r", eid=eid)
        return n

    def snapshot(self) -> dict:
        """Pages, tasks and edge counters, so a write can be diffed (see learn.memory_diff)."""
        edges = {
            eid: {"src": a, "name": n, "dst": b, "successes": s, "failures": f}
            for eid, a, n, b, s, f in self.q(
                "MATCH (a:State)-[r:ACT]->(b:State) RETURN r.eid, a.key, r.name, b.key, r.successes, r.failures"
            )
        }
        return {
            "edges": edges,
            "states": {k for (k,) in self.q("MATCH (s:State) RETURN s.key")},
            "tasks": {t for (t,) in self.q("MATCH (t:Task) RETURN t.id")},
        }

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

    def fingerprint(self) -> str:
        """Content hash of the whole memory (pages, steps with counters, tasks, worksites).
        Equal fingerprints = the agent sees exactly the same memory."""
        rows = [
            *(["S", k, r, t] for k, r, t in self.q("MATCH (s:State) RETURN s.key, s.route, s.title")),
            # provenance is appended only when present, so fingerprints of v1 memory (no sources) are unchanged
            *(
                ["E", *row[:-1]] + ([row[-1]] if row[-1] is not None else [])
                for row in self.q(
                    "MATCH (a:State)-[r:ACT]->(b:State) RETURN a.key, r.eid, r.kind, r.role, r.name, r.scope, r.pre, "
                    "r.successes, r.failures, b.key, r.sources"
                )
            ),
            *(
                ["W", *row]
                for row in self.q(
                    "MATCH (t:Task)-[w:WORKED_AT]->(s:State) RETURN t.id, t.goal, t.cluster, w.steps, s.key"
                )
            ),
        ]
        blob = json.dumps(sorted(rows, key=json.dumps), sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def dump(self) -> dict:
        """Everything fingerprint() covers, as JSON: load_dump() of this gives the same fingerprint."""
        return {
            "graph": self.name,
            "fingerprint": self.fingerprint(),
            "states": [
                dict(zip(("key", "route", "title"), r))
                for r in self.q("MATCH (s:State) RETURN s.key, s.route, s.title ORDER BY s.key")
            ],
            "edges": self.edges(),
            "worksites": [
                dict(zip(("task", "goal", "cluster", "steps", "state"), r))
                for r in self.q(
                    "MATCH (t:Task)-[w:WORKED_AT]->(s:State) RETURN t.id, t.goal, t.cluster, w.steps, s.key ORDER BY t.id"
                )
            ],
        }

    def load_dump(self, d: dict) -> str:
        """Replace this graph with a dump; returns the new fingerprint (callers compare it with d["fingerprint"])."""
        self.clear()
        for s in d["states"]:
            self.q("CREATE (:State {key:$key, route:$route, title:$title})", **s)
        for e in d["edges"]:
            props = {k: e[k] for k in ("eid", "kind", "role", "name", "scope", "pre", "successes", "failures")}
            self.q(
                """MATCH (a:State {key:$src}), (b:State {key:$dst}) CREATE (a)-[r:ACT]->(b) SET r = $props""",
                src=e["src"],
                dst=e["dst"],
                props={k: v for k, v in props.items() if v is not None},
            )
            if e["sources"] is not None:
                self.q("MATCH ()-[r:ACT {eid:$eid}]->() SET r.sources=$s", eid=e["eid"], s=e["sources"])
        for w in d["worksites"]:
            self.q(
                """MERGE (t:Task {id:$task}) SET t.goal=$goal, t.cluster=$cluster
                      WITH t MATCH (s:State {key:$state}) CREATE (t)-[:WORKED_AT {steps:$steps}]->(s)""",
                **w,
            )
        return self.fingerprint()

    def migrate_edge_ids(self) -> int:
        """Recompute every edge id with the current edge_id() (v1 ids did not include the scope).
        v1 ids were coarser, so each edge maps to exactly one new id; nothing is merged or split."""
        rows = self.q("MATCH (a:State)-[r:ACT]->(b:State) RETURN r.eid, a.key, r.kind, r.role, r.name, r.scope, b.key")
        plan = {
            eid: edge_id(src, Step(kind, role, name, scope=scope or ""), dst)
            for eid, src, kind, role, name, scope, dst in rows
        }
        if len(set(plan.values())) != len(plan) or len(plan) != len(rows):
            raise ValueError("edge id collision: refusing to migrate (would merge distinct steps)")
        changed = 0
        for eid, src, kind, role, name, scope, dst in rows:
            new = plan[eid]
            if new != eid:
                self.q(
                    "MATCH (:State {key:$src})-[r:ACT {eid:$eid}]->(:State {key:$dst}) SET r.eid=$new",
                    src=src,
                    dst=dst,
                    eid=eid,
                    new=new,
                )
                changed += 1
        return changed

    def stats(self) -> dict:
        n = self.q("MATCH (s:State) RETURN count(s)")[0][0]
        e = self.q("MATCH ()-[r:ACT]->() RETURN count(r)")[0][0]
        t = self.q("MATCH (t:Task) RETURN count(t)")[0][0]
        return {"states": n, "edges": e, "tasks": t}
