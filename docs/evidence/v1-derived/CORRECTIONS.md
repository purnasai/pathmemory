# v1 corrections (2026-10-18)

The v1 logs in `docs/evidence/v1*/` are unchanged. Everything here is **derived** from them and from the
saved run directories (`results/v1*/`, git-ignored, available locally). Regenerate:

```bash
uv run python -m pathmemory.accounting docs/evidence/v1/eval.jsonl          > docs/evidence/v1-derived/v1-eval.accounting.jsonl
uv run python -m pathmemory.accounting docs/evidence/v1/recovery.jsonl      > docs/evidence/v1-derived/v1-recovery.accounting.jsonl
uv run python -m pathmemory.accounting docs/evidence/v1-repaired/recovery.jsonl > docs/evidence/v1-derived/v1-repaired-recovery.accounting.jsonl
uv run python -m pathmemory.report docs/evidence/v1/eval.jsonl --select both > docs/evidence/v1-derived/v1-eval.report.txt
```

All 68 v1 rows were re-derived from their run directories; none is unverified, and every derived token total
equals the token total in the original row.

## 1. "LLM calls" was LLM-chosen browser steps, not model calls

The v1 column `llm_steps` (shown as "avg LLM calls" in the v1 results tables) counts browser
steps whose action came from the base agent. It misses:

- the **destination chooser** call that graph mode makes once per run (`_plan()`), and
- **parse retries**: the base agent re-queries the model when its answer cannot be parsed
  (`issues-6` none/flat/graph, `repos-3` flat/graph, first `repos-5` none, and others).

**Tokens were already correct.** `PathMemoryAgent.get_action` is wrapped in AgentLab's `cost_tracker_decorator`,
whose tracker sees every completion made inside it (chooser included). Evidence: in graph runs whose step 0 was a
replayed click, step 0 has non-zero `input_tokens` (≈1.4k) although no base call happened; that is the chooser.

Normal UI, 14 tasks (latest attempt, as published):

| Mode | Success | LLM-chosen steps (published as "LLM calls") | **Model calls** (chooser + base) | Input tokens | Output tokens |
|---|---|---|---|---|---|
| none | 14/14 | 4.14 | **4.21** (0 + 4.21) | 13,879 | 313 |
| flat | 14/14 | 4.29 | **4.43** (0 + 4.43) | 16,612 | 327 |
| graph | 13/14 | 3.50 | **4.64** (1 + 3.64) | 10,332 | 424 |

So the published "graph: −15% LLM calls" is **wrong**: graph mode made ~10% *more* model calls than no memory
(4.64 vs 4.21). The "−26% input tokens" stands (10,332 vs 13,879). Graph mode used more output tokens (424 vs 313),
mostly the chooser's JSON answer.

UI break, before repair (5 tasks): model calls none 11.2, flat 8.8, graph 11.0 (published "LLM calls": 11.0, 8.6, 9.2).
UI break, after one repair episode (4 tasks): flat 8.75, graph 7.0 (published: 8.0, 5.8). Tokens unchanged.

Chooser tokens per run could be isolated for 17 of the 24 graph runs (when step 0 was a replay, the chooser
was its only call): mean 1,403 input tokens (normal UI, 13 of 15 runs) and 1,471 (after repair, 4 of 4). For the
other 7 (step 0 was an LLM step: 2 normal-UI runs and all 5 pre-repair UI-break runs) AgentLab stored only the
sum of chooser and base tokens, so the split is `null`, not estimated.

## 2. Repeated `repos-5` attempts were a different task

`docs/evidence/v1/eval.jsonl` holds two attempts for each of `repos-5`/none, flat and graph (lines 37–39 and 43–45).
The old `report.py` kept the last one silently. The saved `goal_object.pkl.gz` of each run shows the two attempts
ran **different goals** under the same id:

| Attempt | Lines | Goal | Outcome (none / flat / graph) |
|---|---|---|---|
| 1 | 37–39 | "How many commits are on the main branch of a11yproject.com? Reply with the number." | FAIL / FAIL / FAIL (all answered "2"; checker expected "3") |
| 2 | 43–45 | "What is the description of the primer/design repository?" | OK / OK / OK |

Why it was rerun, as far as the artifacts establish it: commit `bfe48a3` ("… deterministic repos-5") replaced the
task definition and added the code comment "Gitea's header commit/branch counters are cached and can disagree with
the API, so no count questions here." The artifacts do not show what the page displayed, so whether "2" was the
cached counter's value is not established here.

| Selection | none | flat | graph |
|---|---|---|---|
| first attempt (old repos-5 definition) | 13/14 | 13/14 | 12/14 |
| latest attempt (new definition; the published numbers) | 14/14 | 14/14 | 13/14 |

`report.py` now requires `--select first|latest|both`, prints every repeated attempt and flags a changed
definition. New rows (schema 2) record `goal` and `task_sha`.

## 3. Evaluation wrote to the memory it was evaluated on

In v1 code `_fail()` always called `graph.mark_failure()`. Rows with an `edge_failed` event:
`v1/eval` none; `v1/recovery` all 5 graph trials; `v1-repaired/recovery` all 4 graph trials. All of them incremented
`failures` on the dashboard edge `b69223882ef8`, so later trials in those batches read a graph with a higher failure
count. Route ranking is `ORDER BY hops, fails`, and the logs show every one of those trials chose the same first
route (`/ → /:owner/:repo → …`), so the observed route choices were not changed by it. The leak was real; an effect
on these results is not visible in the logs.

## 4. The Gitea fixture was reset only before data-changing tasks

Read-only tasks ran on whatever the previous trial left. Confirmed case: `members-3` (none, flat, graph; lines 4–6)
ran after `members-2`/graph had added carol as a collaborator, and all three answered "alice and carol". The
checker only requires "alice", so the outcome did not change, but those trials did not see the fixture. Other
read-only tasks (`issues-5/6/7`, `profile-4`, `repos-5`) followed mutations of unrelated state.

## What changed in code

- explicit per-role usage (`pm_chooser_*`, `pm_base_*` step stats → `chooser_calls`, `base_calls`, `model_calls`,
  per-role tokens, and an `accounting_consistent` check against AgentLab's own total)
- explicit attempt selection with provenance in `report.py`
- fail-closed replay (hidden / out-of-scope / ambiguous / unbound targets are never clicked; prerequisites are
  skipped only when the next target is already clickable; entity bindings are checked after every replayed click)
- evaluation copies a designated memory snapshot per trial, never records failures, and resets + fingerprints the
  Gitea fixture before every trial; live learning records failures only with `--learn`
