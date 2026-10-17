"""Audit: which training episodes taught each hop of a replayed route.

ACT edges store outcome counts, not their source task, so this re-derives provenance from the
saved episodes with the same rule `learn.ingest` uses (successful run, navigational click that
moved to another page template). It then checks every route replayed in a recovery result file
and reports whether any single episode contains the whole route.

    uv run python -m pathmemory.provenance results/v1-repaired/recovery.jsonl \
        results/v1/learn/* results/v1-alt/learn/* \
        results/v1/recovery/*PathMemory-none_on_pathmemory.members-2_0
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from .learn import trajectory


def taught_hops(exp_dirs: list[Path]) -> dict[tuple[str, str], set[str]]:
    hops: dict[tuple[str, str], set[str]] = defaultdict(set)
    for d in exp_dirs:
        tr = trajectory(Path(d))
        if not tr:
            continue
        label = f"{tr['task_id']} ({Path(d).name.split('_')[2].split('-')[1]})"  # task (mode of that run)
        for r in tr["rows"]:
            step, moved = r["step"], r["src"].key != r["dst"].key
            if step.kind == "click" and r["ok"] and moved and step.navigational:
                hops[(r["src"].key, r["dst"].key)].add(label)
    return hops


def main(argv: list[str]) -> int:
    result_file, exp_dirs = Path(argv[0]), [Path(p) for p in argv[1:]]
    hops = taught_hops(exp_dirs)
    report = []
    for line in result_file.read_text().splitlines():
        run = json.loads(line)
        if run["mode"] != "graph":
            continue
        routes = [e["via"] for e in run["log"] if e["event"] == "recovered"] or [e["keys"] for e in run["log"] if e["event"] == "route"][-1:]
        for keys in routes:
            pairs = list(zip(keys, keys[1:]))
            sources = [sorted(hops.get(p, set())) for p in pairs]
            tasks_per_hop = [{s.split(" ")[0] for s in src} for src in sources]
            single = set.intersection(*tasks_per_hop) if tasks_per_hop else set()
            report.append({
                "task": run["task"], "success": run["success"],
                "hops": [{"from": a, "to": b, "taught_by": s} for (a, b), s in zip(pairs, sources)],
                "distinct_source_tasks": sorted(set().union(*tasks_per_hop)),
                "single_episode_with_whole_route": sorted(single),
                "unexplained_hops": sum(1 for s in sources if not s),
            })
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
