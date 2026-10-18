"""Memory graph operations shared by the demo UI and the MCP server.

Every graph operation is a fixed, parameterised Cypher query; nothing accepts Cypher from outside.
"""

from pathmemory.graph import GraphMemory
from pathmemory.state import State, Step, route_template, templatize

ROUTE_CYPHER = """MATCH (a:State {key:$src}), (b:State {key:$dst})
MATCH p = (a)-[:ACT*1..6]->(b)
WHERE all(r IN relationships(p) WHERE r.successes > 0 AND NOT r.eid IN $banned)
RETURN [n IN nodes(p) | n.key], [r IN relationships(p) | r.name], length(p) AS hops,
       reduce(f = 0, r IN relationships(p) | f + r.failures) AS fails
ORDER BY hops, fails LIMIT 3"""


class InvalidArgument(ValueError):
    pass


class PathMemoryService:
    def __init__(self, graph_name: str = "pathmemory"):
        self.graph = GraphMemory(graph_name)

    # --- memory graph -----------------------------------------------------------
    def graph_view(self) -> dict:
        nodes = [{"key": d["key"], "title": d["title"], "goals": d["goals"]} for d in self.graph.destinations()]
        edges = [
            {
                "eid": e,
                "src": a,
                "dst": b,
                "role": role,
                "name": name,
                "scope": scope,
                "pre": pre or [],
                "successes": s,
                "failures": f,
                "sources": src or [],
            }
            for a, e, role, name, scope, pre, s, f, src, b in self.graph.q(
                "MATCH (a:State)-[r:ACT]->(b:State) "
                "RETURN a.key, r.eid, r.role, r.name, r.scope, r.pre, r.successes, r.failures, r.sources, b.key"
            )
        ]
        return {
            "graph": self.graph.name,
            "fingerprint": self.graph.fingerprint(),
            "nodes": nodes,
            "edges": edges,
            "stats": self.graph.stats(),
        }

    def pages(self) -> list[dict]:
        return self.graph.destinations()

    def resolve(self, url: str) -> dict:
        key, route, bindings = route_template(url)
        return {"key": key, "route": route, "bindings": bindings, "known": self.graph.has_state(key)}

    def page_memory(self, key: str) -> dict:
        self._known(key)
        site = next(d for d in self.graph.destinations() if d["key"] == key)
        out = self.graph.q(
            "MATCH (:State {key:$k})-[r:ACT]->(b:State) RETURN r.role, r.name, b.key, r.successes, r.failures", k=key
        )
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
        b = {**src[2], **dst[2]}
        eid = self.graph.record_transition(
            State(src[0], src[1], src[2]), Step("click", role, templatize(name, b)), State(dst[0], dst[1], dst[2])
        )
        return {"eid": eid, "from": src[0], "to": dst[0], "name": templatize(name, b)}

    def report_failure(self, eid: str) -> dict:
        if not self.graph.q("MATCH ()-[r:ACT {eid:$e}]->() RETURN r.eid", e=eid):
            raise InvalidArgument(f"unknown step id {eid!r}")
        self.graph.mark_failure(eid)
        return {"eid": eid, "failures": self.graph.q("MATCH ()-[r:ACT {eid:$e}]->() RETURN r.failures", e=eid)[0][0]}

    def _known(self, key):
        if not self.graph.has_state(key):
            raise InvalidArgument(f"unknown page {key!r}; call list_pages or resolve_url first")
