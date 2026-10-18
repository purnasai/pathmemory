# Reproducing the v2 evidence

One script, from a fresh clone. Steps 1–6 and 9 need no API key and no saved runs; 7–8 call the model.

```bash
scripts/reproduce_v2.sh             # steps 1-6, 9  (about 1-2 minutes after images are pulled)
scripts/reproduce_v2.sh --with-llm  # also 7-8      (OpenAI key in .env; about 2 minutes, ~$0.005)
```

Requirements: Docker (Compose v2), [uv](https://docs.astral.sh/uv/), ports 6391/3391 (FalkorDB) and 3300 (Gitea)
free. The compose project is named `t12-pathmemory`, so a second checkout reuses the same containers.

| step | command | what it checks | expected |
|---|---|---|---|
| 1 | `docker compose up -d`, `uv sync`, `playwright install chromium` | services up | Gitea `/api/healthz` OK |
| 2 | `python -m pathmemory.repro fixture` | recreate Gitea (tmpfs), seed, hash the state the checkers read (API) | `fixture: 32f2a9ca533fd2ce` |
| 3 | `python -m pathmemory.repro load` | load `memory/graph_v2.json` and `graph_v2_ablated.json` into FalkorDB | `pathmemory_v2: ff0899ff00fbb4d5` (= manifest), `pathmemory_v2_ablated: 93e0b6bd12e2831c` |
| 4 | `python -m pathmemory.repro provenance` | every edge's `sources` are training runs in the manifest and each of those runs' own steps contains that edge; every step of every run is in the graph under that run; no held-out task in the manifest. With the raw runs present (author's machine), rebuild v2 from them | `problems: []`; rebuild `ff0899ff00fbb4d5`, file hashes match (or `skipped` in a clone) |
| 5 | `python -m pathmemory.repro composition` | run the route query now; compare with `composition.json` | route `/ → /explore/repos → /:owner/:repo → issues → issues/new`, `differs: []` |
| 6 | `python -m pathmemory.repro ablate` | copy v2, delete the bridge step, fingerprint the copy, check v2 unchanged | `removed: 1`, `93e0b6bd12e2831c`, `v2_untouched: true` |
| 7 | `run eval issues-2 --modes graph --break-ui --snapshot pathmemory_v2 …` | composed route in the browser | checker pass; log: dashboard step `missing` → reroute → 4 replays, each `verified` |
| 8 | same with `--snapshot pathmemory_v2_ablated` | ablation in the browser | `no_route`; 0 replayed; pass only by LLM fallback (not guaranteed) |
| 9 | `python -m pathmemory.repro unchanged` | v2, ablated (and v1 where present) still have their fingerprints | all equal |

Steps 7–8 produce new rows in `results/repro-*/eval.jsonl`; the model's own actions vary run to run, the replayed
part does not. `compare.py` prints the same table format as [FAIR_COMPARISON.md](FAIR_COMPARISON.md).

What is *not* in a clone: the raw training runs and evaluation runs (step pickles, screenshots) are in the
git-ignored `results/` (their exact file hashes are in `memory/manifest.json`). The clone reproduces the memory from
the committed dump and checks its provenance against the committed per-run step lists (`memory/flat_memory.json`);
the full rebuild from raw runs was checked on the author's machine (step 4 output above).

Validated 2026-10-18 from a fresh `git clone` of branch `p2-submission` into an empty directory (see the P2
report for the exact output).
