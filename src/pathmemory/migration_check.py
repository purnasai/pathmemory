"""Migrate a COPY of a memory graph to scoped edge ids and verify nothing but the ids changed.

    uv run python -m pathmemory.migration_check pathmemory_v1 pm_migration_scratch
"""

import json
import sys

from pathmemory.graph import GraphMemory


def _content(g):
    """Every edge without its id: what migration must preserve."""
    return sorted(json.dumps({k: v for k, v in e.items() if k != "eid"}, sort_keys=True) for e in g.edges())


def verify(source: str, scratch: str) -> dict:
    src, tmp = GraphMemory(source), GraphMemory(scratch)
    assert scratch != source
    src_fp = src.fingerprint()
    tmp.clear()
    src.g.copy(scratch)
    before, stats_before = _content(tmp), tmp.stats()
    ids_before = [e["eid"] for e in tmp.edges()]
    changed = tmp.migrate_edge_ids()
    after = tmp.edges()
    out = {
        "source": source, "source_fingerprint": src_fp, "scratch": scratch,
        "edges": len(after), "ids_changed": changed,
        "count_preserved": tmp.stats() == stats_before,
        "content_preserved": _content(tmp) == before,             # endpoints, role, name, scope, pre, counters
        "ids_unique": len({e["eid"] for e in after}) == len(after),
        "idempotent": tmp.migrate_edge_ids() == 0,
        "source_untouched": src.fingerprint() == src_fp,
        "old_to_new": dict(zip(ids_before, [e["eid"] for e in after])),
    }
    # collision handling: a second edge describing the same step under another id would map onto the same new
    # id; migration must refuse instead of silently merging two edges (and their counters)
    e = after[0]
    tmp.q("""MATCH (a:State {key:$src}), (b:State {key:$dst})
             CREATE (a)-[:ACT {eid:'collision00', kind:$kind, role:$role, name:$name, scope:$scope, pre:$pre,
                              successes:1, failures:0}]->(b)""",
          src=e["src"], dst=e["dst"], kind=e["kind"], role=e["role"], name=e["name"], scope=e["scope"], pre=e["pre"] or [])
    n_before = tmp.stats()["edges"]
    try:
        tmp.migrate_edge_ids()
        out["collision_refused"] = False
    except ValueError:
        out["collision_refused"] = tmp.stats()["edges"] == n_before and any(x["eid"] == "collision00" for x in tmp.edges())
    tmp.clear()
    return out


if __name__ == "__main__":
    print(json.dumps(verify(sys.argv[1], sys.argv[2]), indent=1))
