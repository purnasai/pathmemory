# Evidence v2 (branch p0-correctness): code-correctness checks, no evaluation yet

No v2 evaluation has been run. This folder holds only what was needed to check the changed code on the real stack.

- `replaycheck.json`: `python -m pathmemory.replaycheck results`. Every click PathMemory replayed in the saved v1
  runs (63) is looked up again with the new fail-closed `find_target()` on the page it was made on: 63/63 resolve to
  the same element, or to one with the same href. One page (the dashboard in `repos-5`) lists `primer/design` twice,
  with the same href; the v1 matcher picked the first, and the new one accepts it because both are the same link.
  Limitation: the lookup uses the clicked element's own landmark, not the landmark stored in memory (see below).
- `smoke.jsonl` (+ `smoke.accounting.jsonl`): two single-trial runs of `eval issues-5 --modes graph
  --snapshot pathmemory_v1`, about 7k tokens each.
  - Run 1 (`p0-smoke`) exposed a regression: v1 memory stores the dashboard edge's landmark as
    `main:{owner} - Dashboard` (learned on a byteblaze repo; the landmark actually names the logged-in user).
    The strict matcher filled `{owner}` with the chosen repo owner (`a11yproject`), so it rejected the link
    as `out_of_scope` and rerouted via Explore (5 steps, still successful).
  - Fix: landmarks are now templated and filled only with the bindings of the page the click is on (learning and
    replay). Landmarks from older memory that still contain a placeholder are logged as `scope_unverifiable`
    and matched without a scope, still requiring one visible, unambiguous target.
  - Run 2 (`p0-smoke2`): replays the dashboard route directly (4 steps, 2 replayed), success.
  - Both runs: `accounting_consistent: true` (chooser 1,472 + base tokens = AgentLab's total), 3 model calls
    (1 chooser + 2 base), memory `unchanged: true`, snapshot fingerprint `c51e00d7fe31aa16` before and after,
    Gitea fixture fingerprint `32f2a9ca533fd2ce`.

Two runs on one task prove the plumbing works. They say nothing about success rates or savings.

## P1 (branch p1-composition): composition and four-mode comparison

- [COMPOSITION.md](COMPOSITION.md): training episodes, composed route, per-hop sources, Cypher, absence from every
  single episode, ablation, browser outcome. Raw: `composition.json`.
- [FAIR_COMPARISON.md](FAIR_COMPARISON.md): none / flat / flatreplay / graph on `issues-2`, normal UI, broken UI
  and ablation, 5 trials each. Raw: `runs/*.jsonl`, `runs/comparison.json`.
- [DEMO_WALKTHROUGH.md](DEMO_WALKTHROUGH.md): screenshots of one composed-route run.
- `memory/`: v2 manifest (episodes, hashes, fingerprint, edges with sources), flat store, ablation record, v1-vs-v2 diff.
- `replaycheck_v1_memory.json`, `replaycheck_v2_memory.json`: replayed clicks checked against the memory replayed.
- `migration_v1_copy.json`: scoped edge-id migration on a disposable copy of v1.
- `probes.jsonl`: no-LLM real-browser wrong-entity and ambiguous-target probes.

## P2 (branch p2-submission): submission readiness

- `memory/graph_v2.json`, `memory/graph_v2_ablated.json`: exact dumps of the two graphs (reload to the same
  fingerprints); [REPRODUCE.md](REPRODUCE.md) and `scripts/reproduce_v2.sh` rebuild and check everything from a clone.
- `runs/broken_flat_pinned.jsonl`: labelled retrieval-coverage check (flat prompt with the route's source runs pinned).
- `live/*.json`: the two live UI runs of 2026-10-18 (composed route; ablated graph), with the snapshot fingerprint
  before and after each.
- Path normalization: the `exp_dir` field of the v2 JSONL rows (`runs/`, `smoke.jsonl`, `probes.jsonl`) was rewritten
  from an absolute path on the author's machine to the project-relative `results/…` path. No other field changed.
  v1 evidence is unchanged and still contains absolute paths.
