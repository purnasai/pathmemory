"""Reproduction checks for the v2 evidence, runnable from a fresh clone (no saved runs, no LLM needed).

    uv run python -m pathmemory.repro fixture      # recreate + seed Gitea, compare with the declared fixture
    uv run python -m pathmemory.repro load         # load v2 (+ ablated) memory from the committed dumps
    uv run python -m pathmemory.repro provenance   # every edge <-> the training episodes that showed it
    uv run python -m pathmemory.repro ablate       # rebuild the ablated copy from v2, compare with the dump
    uv run python -m pathmemory.repro composition  # live Cypher on v2 == committed composition.json
    uv run python -m pathmemory.repro unchanged    # v2 / ablated / v1 memories still have their fingerprints

Each command prints JSON and exits non-zero if a check fails.
"""

import json
import sys

from pathmemory.config import settings
from pathmemory.graph import GraphMemory
from pathmemory.run import RECOVERY, TEST

EV = settings.root / "docs/evidence/v2"
MANIFEST = EV / "memory/manifest.json"
DUMPS = {"pathmemory_v2": EV / "memory/graph_v2.json", "pathmemory_v2_ablated": EV / "memory/graph_v2_ablated.json"}
FIXTURE = "32f2a9ca533fd2ce"     # Gitea state after seed.reset(), as recorded in every v2 row
V1_DEMO = "c51e00d7fe31aa16"     # v1 memory ("pathmemory", backup "pathmemory_v1"), never written by v2 work


def _json(p):
    return json.loads(p.read_text())


def fixture() -> dict:
    from pathmemory.run import reset_site
    fp = reset_site()
    return {"ok": fp == FIXTURE, "fixture": fp, "declared": FIXTURE}


def load() -> dict:
    out = {}
    for name, path in DUMPS.items():
        d = _json(path)
        g = GraphMemory(name)
        current = g.fingerprint() if name in g.db.list_graphs() else None
        if current != d["fingerprint"]:
            current = g.load_dump(d)
        out[name] = {"fingerprint": current, "expected": d["fingerprint"], "ok": current == d["fingerprint"]}
    out["ok"] = all(v["ok"] for v in out.values()) and out["pathmemory_v2"]["fingerprint"] == _json(MANIFEST)["fingerprint"]
    return out


def provenance() -> dict:
    """From committed files only: the manifest's episodes, each episode's own navigation steps (flat store),
    and the graph's edges. If the raw episode directories exist (author's machine), also rebuild and compare."""
    m, flat = _json(MANIFEST), _json(EV / "memory/flat_memory.json")
    edges = GraphMemory("pathmemory_v2").edges()
    used = {e["episode"] for e in m["episodes"] if e["success"]}
    nav = {t["episode"]: t["nav"] for t in flat}
    problems = []
    if not {e["task"] for e in m["episodes"]}.isdisjoint(set(TEST) | set(RECOVERY)):
        problems.append("a held-out task is in the training manifest")
    if set(nav) != used:
        problems.append("flat store episodes differ from the manifest's successful episodes")
    for e in edges:
        for src in e["sources"] or []:
            if src not in used:
                problems.append(f"{e['eid']}: source {src} not a training episode")
            elif not any(s["eid"] == e["eid"] and s["src"] == e["src"] and s["dst"] == e["dst"] and s["name"] == e["name"]
                         and s["scope"] == e["scope"] for s in nav[src]):
                problems.append(f"{e['eid']}: {src} does not contain this step")
        if not e["sources"]:
            problems.append(f"{e['eid']}: no source")
    by_eid = {e["eid"]: set(e["sources"] or []) for e in edges}
    for ep, steps in nav.items():
        for s in steps:
            if ep not in by_eid.get(s["eid"], set()):
                problems.append(f"{ep}: step {s['eid']} missing from the graph or its sources")
    out = {"episodes": len(used), "edges": len(edges), "problems": problems}
    raw = [settings.root / e["dir"] for e in m["episodes"]]
    if all(d.exists() for d in raw):
        from pathmemory.learn import build_memory, _sha_files
        g = GraphMemory("pm_repro_rebuild")
        rebuilt = build_memory(raw, g, settings.root / "results/pm_repro_flat.json", set(TEST) | set(RECOVERY))
        out["rebuild_from_raw_episodes"] = {"fingerprint": rebuilt["fingerprint"], "ok": rebuilt["fingerprint"] == m["fingerprint"],
                                            "file_hashes_ok": [e["files_sha"] for e in rebuilt["episodes"]] == [e["files_sha"] for e in m["episodes"]]}
        g.clear()
        if not (out["rebuild_from_raw_episodes"]["ok"] and out["rebuild_from_raw_episodes"]["file_hashes_ok"]):
            problems.append("rebuild from raw episodes does not reproduce the manifest")
    else:
        out["rebuild_from_raw_episodes"] = "skipped: raw episode directories are not in this checkout (git-ignored results/)"
    out["ok"] = not problems
    return out


def ablate() -> dict:
    from pathmemory.composition import bridge_step
    v2, copy = GraphMemory("pathmemory_v2"), GraphMemory("pm_repro_ablated")
    before = v2.fingerprint()
    copy.clear()
    v2.g.copy(copy.name)
    removed = copy.delete_edge(bridge_step(v2))
    fp = copy.fingerprint()
    copy.clear()
    expected = _json(DUMPS["pathmemory_v2_ablated"])["fingerprint"]
    return {"removed": removed, "fingerprint": fp, "expected": expected, "v2_untouched": v2.fingerprint() == before,
            "ok": removed == 1 and fp == expected and v2.fingerprint() == before}


def composition() -> dict:
    from pathmemory.composition import evidence
    live, saved = evidence(), _json(EV / "composition.json")
    keys = ("graph_fingerprint", "composed_route", "no_single_episode_contains_route", "single_episode_containment",
            "flat_replay_routes")
    diff = [k for k in keys if live[k] != saved[k]]
    if live["ablation"]["broken_ui_routes"] != saved["ablation"]["broken_ui_routes"]:
        diff.append("ablation")
    return {"composed_route": live["composed_route"]["keys"], "differs": diff, "ok": not diff}


def unchanged() -> dict:
    want = {"pathmemory_v2": _json(MANIFEST)["fingerprint"],
            "pathmemory_v2_ablated": _json(DUMPS["pathmemory_v2_ablated"])["fingerprint"]}
    names = GraphMemory("pathmemory_v2").db.list_graphs()
    for n in ("pathmemory", "pathmemory_v1"):
        if n in names:  # v1 demo memory exists only where v1 was run
            want[n] = V1_DEMO
    got = {n: GraphMemory(n).fingerprint() for n in want}
    return {"fingerprints": got, "expected": want, "ok": got == want}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    fn = {"fixture": fixture, "load": load, "provenance": provenance, "ablate": ablate,
          "composition": composition, "unchanged": unchanged}.get(cmd)
    if not fn:
        sys.exit(__doc__)
    res = fn()
    print(json.dumps(res, indent=1))
    sys.exit(0 if res["ok"] else 1)
