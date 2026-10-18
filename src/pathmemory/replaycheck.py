"""Offline check of replayed clicks against real pages and against the memory that was replayed.

For every click PathMemory replayed in saved runs (graph or flatreplay mode), on the page it was made on:

  matcher   the current fail-closed find_target(), given the step as stored in memory, still resolves to the
            element that was clicked (or to one with the same href)
  name      the stored name template, filled with the page's and the chosen bindings, equals the clicked
            element's name
  scope     the stored landmark, filled with the page's own bindings, equals the clicked element's landmark
            ("unverifiable" when the stored landmark still has a placeholder: pre-p0 memory)
  dest      the next page has the stored destination template and agrees with the chosen entities

    uv run python -m pathmemory.replaycheck --graph pathmemory_v1 results/v1 results/v1-repaired
"""

import argparse
import collections
import gzip
import json
import pickle
from pathlib import Path

from pathmemory.graph import GraphMemory
from pathmemory.state import (_name, _role, find_target, hrefs, instantiate, node_by_bid, norm_name, parse_action,
                              scope_of, state_of)

CHECKED = ("owner", "repo", "org", "n")


def _steps(d: Path):
    files = sorted(d.glob("step_*.pkl.gz"), key=lambda f: int(f.name.split("_")[1].split(".")[0]))
    return [pickle.load(gzip.open(f)) for f in files]


def stored_steps(edges: list[dict]) -> dict:
    """(src key, name template) -> stored steps (edges, and the prerequisite clicks they carry)."""
    out = collections.defaultdict(list)
    for e in edges:
        out[(e["src"], e["name"])].append({"role": e["role"], "scope": e["scope"] or "", "dst": e["dst"], "pre": False})
        for pre in e["pre"] or []:
            role, name, scope = (pre.split("|") + ["", ""])[:3]
            out[(e["src"], name)].append({"role": role, "scope": scope, "dst": e["src"], "pre": True})
    return out


def check_run(d: Path, memory: dict) -> list[dict]:
    steps, out = _steps(d), []
    for i, s in enumerate(steps):
        pm = ((s.agent_info or {}).get("extra_info") or {}).get("pathmemory") or {}
        if pm.get("source") != "graph" or not s.action:
            continue
        log = pm.get("log") or []
        target = log[-1].get("target") if log and log[-1].get("event") == "replay" else None
        chosen = next((e.get("bindings") or {} for e in log if e["event"] == "choose"), {})
        st = state_of(s.obs)
        bid = parse_action(s.action)[1][0]
        node = node_by_bid(s.obs, bid)
        cands = memory.get((st.key, target), [])
        row = {"run": d.name, "step": i, "page": st.key, "target": target, "stored": len(cands)}
        if node is None or len(cands) != 1:
            row["result"] = "no_stored_step" if not cands else ("several_stored_steps" if node else "no_node")
            out.append(row)
            continue
        c = cands[0]
        b = {**st.bindings, **chosen}
        name = instantiate(target, b)
        scope = instantiate(c["scope"], st.bindings)
        obs_scope = scope_of(s.obs, node)
        m = find_target(s.obs, c["role"], name, "" if "{" in scope else scope)
        h = hrefs(s.obs)
        row["matcher"] = "same_target" if m.ok and (m.bid == bid or h.get(m.bid) == h.get(bid) != None) else m.status
        row["name"] = "match" if norm_name(_name(node)).lower() == norm_name(name).lower() else f"mismatch: {_name(node)!r}"
        row["scope"] = ("unverifiable" if "{" in scope else
                        "match" if scope.lower() == obs_scope.lower() else f"mismatch: stored {scope!r}, page {obs_scope!r}")
        row["role"] = "match" if _role(node) == c["role"] else f"mismatch: {_role(node)}"
        if i + 1 < len(steps) and steps[i + 1].obs:
            nxt = state_of(steps[i + 1].obs)
            bad = [k for k in CHECKED if chosen.get(k) and nxt.bindings.get(k) and
                   chosen[k].lower() != nxt.bindings[k].lower()]
            row["dest"] = ("match" if nxt.key.split("#")[0] == c["dst"] and not bad else
                           f"mismatch: {nxt.key} {bad}" if not c["pre"] or nxt.key != st.key else "match")
        out.append(row)
    return out


def check(dirs: list[Path], graph: str) -> dict:
    memory = stored_steps(GraphMemory(graph).edges())
    rows = []
    for root in dirs:
        for d in sorted(root.glob("**/*_on_pathmemory.*")):
            if (d / "summary_info.json").exists():
                rows.extend(check_run(d, memory))
    tally = {k: dict(collections.Counter(r.get(k, "n/a") if not str(r.get(k, "")).startswith("mismatch")
                                         else "mismatch" for r in rows))
             for k in ("matcher", "name", "scope", "role", "dest", "result")}
    return {"graph": graph, "replayed_clicks": len(rows), "tally": tally,
            "exceptions": [r for r in rows if r.get("result") or any(
                str(r.get(k, "match")) not in ("match", "same_target") for k in ("matcher", "name", "scope", "role", "dest"))]}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("dirs", nargs="+")
    p.add_argument("--graph", required=True, help="the memory the runs replayed")
    a = p.parse_args()
    print(json.dumps(check([Path(x) for x in a.dirs], a.graph), indent=1))
