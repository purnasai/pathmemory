"""Offline regression check of the fail-closed matcher on real pages: for every click PathMemory replayed in
the saved runs, look the remembered target up again with the current find_target() on the page the
click was made on, and report whether it still resolves to the element that was clicked (or to an element
with the same href). No browser or LLM needed.

    uv run python -m pathmemory.replaycheck results
"""

import collections
import gzip
import json
import pickle
import sys
from pathlib import Path

from pathmemory.state import _name, _role, find_target, hrefs, node_by_bid, norm_name, parse_action, scope_of


def check(results: Path) -> dict:
    counts, cases = collections.Counter(), []
    for d in sorted(results.glob("**/*graph_on*")):
        for f in sorted(d.glob("step_*.pkl.gz"), key=lambda f: int(f.name.split("_")[1].split(".")[0])):
            s = pickle.load(gzip.open(f))
            pm = ((s.agent_info or {}).get("extra_info") or {}).get("pathmemory") or {}
            if pm.get("source") != "graph":
                continue
            bid = parse_action(s.action)[1][0]
            node = node_by_bid(s.obs, bid)
            role, name, scope = _role(node), norm_name(_name(node)), scope_of(s.obs, node)
            m = find_target(s.obs, role, name, scope)
            h = hrefs(s.obs)
            same = m.ok and (m.bid == bid or (h.get(m.bid) and h.get(m.bid) == h.get(bid)))
            outcome = "same_target" if same else m.status
            counts[outcome] += 1
            if outcome != "same_target" or m.candidates > 1:
                cases.append({"run": str(d.relative_to(results)), "step": f.name, "role": role, "name": name,
                              "scope": scope, "outcome": outcome, "candidates": m.candidates})
    return {"replayed_clicks": sum(counts.values()), "outcomes": dict(counts), "notable": cases}


if __name__ == "__main__":
    print(json.dumps(check(Path(sys.argv[1] if len(sys.argv) > 1 else "results")), indent=1))
