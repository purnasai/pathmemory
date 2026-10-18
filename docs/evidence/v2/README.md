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
