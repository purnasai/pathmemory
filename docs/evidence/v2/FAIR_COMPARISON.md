# Four-mode comparison on the composition case (v2, 2026-10-18)

**A focused demonstration on one held-out task, not a benchmark.** 5 trials per mode and condition, every trial
reported (45 trials in the main comparison + 5 in the labelled retrieval-coverage check). No statistical test was
run and no significance is claimed.

## The supported claim

> With the dashboard's repository links hidden, **graph-composed replay reached the target page in 5/5 trials;
> single-trajectory flat replay reached it in 0/5** (same chooser, matcher, checks and fallback). With the
> bridge step removed from a copy of the graph, graph replay also reached it in 0/5.

**What is not claimed:** a task-success advantage (every mode passed the checker in every trial), a latency
advantage (episode times overlap), or statistical significance.

## Setup (identical for every mode)

| | |
|---|---|
| Task | `issues-2` (held out; checker unchanged): create issue "Update color tokens" in primer/design, assign carol. `task_sha fd7a8fde540c` in every row. Checker: Gitea API shows an issue with that title and assignee carol |
| Model / agent | `gpt-6-luna` (temperature 1, the only value it accepts), AgentLab GenericAgent, actions `chat`+`bid` (no `goto`), 15-step budget |
| Training evidence | v2 memory from 10 successful training episodes ([memory/manifest.json](memory/manifest.json)); graph `pathmemory_v2` fingerprint `ff0899ff00fbb4d5`; flat store sha `6c743fd14bc18df2`; both built from the same episodes in one build |
| Isolation | before every trial: Gitea recreated + seeded and checked against fixture `32f2a9ca533fd2ce`; graph snapshot copied to a working graph; flat store copied once per batch. All rows: `memory.unchanged: true` |
| Order | trial 1 of all modes, then trial 2, … (interleaved) |

Modes: **none** (no memory). **flat** (prompt memory: top-3 stored trajectories by goal-word Jaccard, each with its
goal and every step "on <url>: <action>"). **flatreplay** (same destination chooser, matcher, entity checks, reroute
limit and LLM fallback as graph; a route must be a contiguous stretch of one stored trajectory). **graph** (FalkorDB
route over all learned steps).

Conditions: **normal** UI. **broken**: the existing `HIDE_DASHBOARD_REPO_LINKS` script hides the dashboard's
`owner/repo` links. **ablation**: broken UI, graph mode on `pathmemory_v2_ablated` (bridge step removed).

## Results (means over 5 trials; raw rows in [runs/](runs/); `python -m pathmemory.compare`)

"Replay reached goal" = the memory route was replayed to its last hop with no failed check after it. A checker pass
without it is an **LLM-fallback success**.

| condition | mode | checker passed | replay reached goal | model calls | input tok | output tok | browser steps | replayed | episode s | route hops | failed checks | wrong-target |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| normal | none | 5/5 | – | 8.0 | 22,779 | 565 | 8.0 | 0 | 38.2 | – | – | 0 |
| normal | flat | 5/5 | – | 8.2 | 26,359 | 572 | 8.0 | 0 | 36.8 | – | – | 0 |
| normal | flatreplay | 5/5 | 5/5 | 6.0 | 14,788 | 466 | 8.0 | 3.0 | 32.1 | 3 | 0 | 0 |
| normal | graph | 5/5 | 5/5 | 6.0 | 14,926 | 464 | 8.0 | 3.0 | 31.7 | 3 | 0 | 0 |
| broken | none | 5/5 | – | 7.0 | 20,628 | 546 | 7.0 | 0 | 32.8 | – | – | 0 |
| broken | flat | 5/5 | – | 7.6 | 25,389 | 618 | 7.6 | 0 | 34.7 | – | – | 0 |
| broken | flatreplay | 5/5 | **0/5** | 8.4 | 23,718 | 631 | 7.4 | 0 | 34.7 | 3 (failed) | 1 | 0 |
| broken | graph | 5/5 | **5/5** | 6.0 | 14,986 | 472 | 9.0 | 4.0 | 33.5 | **4** | 1 | 0 |
| ablation | graph | 5/5 | **0/5** | 8.4 | 24,859 | 656 | 7.4 | 0 | 36.7 | 3 (failed) | 1 | 0 |

"episode s" = AgentLab episode wall time (browser start, login, agent, environment); the Gitea reset before each
trial (7–10 s) is measured separately (`reset_seconds`). Times overlap across modes: no latency claim.

## Estimated cost per task

| condition | mode | USD / task | of which chooser | of which base agent | model calls (chooser + base) | parse retries | input tok | output tok |
|---|---|---|---|---|---|---|---|---|
| normal | none | 0.00256 | 0 | 0.00256 | 8.0 (0 + 8.0) | 0 | 22,779 | 565 |
| normal | flat | 0.00292 | 0 | 0.00292 | 8.2 (0 + 8.2) | 0.2 | 26,359 | 572 |
| normal | flatreplay | 0.00171 | 0.00017 | 0.00154 | 6.0 (1 + 5.0) | 0 | 14,788 | 466 |
| normal | graph | 0.00172 | 0.00019 | 0.00154 | 6.0 (1 + 5.0) | 0 | 14,926 | 464 |
| broken | none | 0.00234 | 0 | 0.00234 | 7.0 (0 + 7.0) | 0 | 20,628 | 546 |
| broken | flat | 0.00285 | 0 | 0.00285 | 7.6 (0 + 7.6) | 0 | 25,389 | 618 |
| broken | flatreplay | 0.00269 | 0.00017 | 0.00252 | 8.4 (1 + 7.4) | 0 | 23,718 | 631 |
| broken | graph | 0.00173 | 0.00019 | 0.00155 | 6.0 (1 + 5.0) | 0 | 14,986 | 472 |
| ablation | graph | 0.00281 | 0.00019 | 0.00263 | 8.4 (1 + 7.4) | 0 | 24,859 | 656 |
| broken (pinned context, below) | flat | 0.00298 | 0 | 0.00298 | 7.8 (0 + 7.8) | 0.2 | 26,549 | 650 |

Pricing and assumptions:
- Price: litellm 1.80.0 model table entry `gpt-6-luna`, standard tier: **$0.10 per 1M input tokens, $0.50 per 1M
  output tokens**. This is the table AgentLab's tracker uses; the USD column is recomputed from the token counts and
  equals the tracker's `stats.cum_cost` in every cell.
- Tokens are the API's reported `prompt_tokens` / `completion_tokens` for every completion: chooser calls, base
  calls and parse retries (a parse retry is a base call beyond one per LLM-chosen browser step; 0–0.2 per task here).
- Cached-input discounts (litellm lists $0.01/M for cached reads) are **not** applied, so if OpenAI served part of
  these prompts from cache the real cost is lower. Failed API attempts are not counted (no usage is returned).
  Not checked against an OpenAI invoice.

## Flat-prompt context audit (was the comparison fair to flat memory?)

The prompts saved in each step file show what flat mode was given. In every flat trial (normal and broken) the
top-3 retrieved trajectories were **repos-1, issues-3, explore-2**; **neither explore-3 nor issues-1** (the two
episodes the composed route needs) was in the LLM's context. The ranking uses the goal text the agent sees,
including the "When you are done, send me a short message…" suffix
(`tests/test_composition.py::test_flat_prompt_context_audit`). So in the main comparison flat prompt memory did
**not** have equivalent access to the essential knowledge.

**Retrieval-coverage check** (labelled, run separately after the main comparison; nothing else changed): broken
UI, flat mode with its context pinned to exactly the route's source episodes (explore-1, explore-3, issues-1;
`--flat-only`, recorded in every row and in a `flat_context` log event), 5 trials
([runs/broken_flat_pinned.jsonl](runs/broken_flat_pinned.jsonl)):

| | checker passed | model calls | input tok | browser steps | took the Explore route |
|---|---|---|---|---|---|
| flat, top-3 retrieval | 5/5 | 7.6 | 25,389 | 7.6 | 0/5 |
| flat, essential episodes pinned | 5/5 | 7.8 | 26,549 | 7.6 | 0/5 |

With the essential trajectories in its context, the LLM still never followed the Explore route: 4 trials used an
activity-feed issue link and 1 searched the repository box first. Giving flat memory the same knowledge did not
change its cost or path here. What it lacks is not knowledge of the steps but a way to execute them without the
LLM, which flat replay supplies only for one stored trajectory at a time.

## Where other modes matched or beat graph

- **Normal UI: flat replay = graph** (6.0 calls, ~$0.0017 each). One past episode (issues-1) already contains the
  whole route, so composition adds nothing.
- **Browser steps under the break: no memory wins (7.0 vs 9.0).** The UI break hides only exact `owner/repo` links.
  The dashboard's activity feed still lists issue links such as `primer/design#1`. Every LLM-driven run (none, flat,
  pinned flat, and flatreplay/ablation after fallback) clicked one, then the issue page's "New Issue" button: a
  2-click way to the form. Graph replayed its 4-hop route instead (Explore → design → Issues → New Issue). Memory
  has no such shortcut: the "New Issue" control on an issue page is a button, and only navigation links are stored
  as replayable steps. Graph still made fewer model calls (6.0 vs 7.0), because replayed clicks need no LLM.
- **No memory beat flat prompt memory** in every condition (fewer tokens, equal or fewer calls).
- **Episode time** is similar across modes (31.7–38.2 s); graph is not faster under the break (33.5 vs 32.8 s).

## Limitations

- One task, one self-built site, one model. 5 trials per cell; the runs are nearly deterministic (identical token
  counts recur), so trials are not independent samples.
- The UI break is partial (feed shortcut above). A break that also hid feed links was not run.
- `explore-3` was added for v2 because no existing training episode taught Explore → repository; the case was
  chosen after inspecting the training data. It is the only composition case tested.
- Costs are estimates from a public price table.

## Reproduce

Checks without an LLM: `scripts/reproduce_v2.sh` ([REPRODUCE.md](REPRODUCE.md)). Full comparison:

```bash
F=docs/evidence/v2/memory/flat_memory.json
uv run python -m pathmemory.run eval issues-2 --modes none flat flatreplay graph --snapshot pathmemory_v2 --flat $F --trials 5 --tag v2-normal
uv run python -m pathmemory.run eval issues-2 --modes none flat flatreplay graph --snapshot pathmemory_v2 --flat $F --trials 5 --break-ui --tag v2-broken
uv run python -m pathmemory.run eval issues-2 --modes graph --snapshot pathmemory_v2_ablated --flat $F --trials 5 --break-ui --tag v2-ablation
uv run python -m pathmemory.run eval issues-2 --modes flat --flat-only explore-1 explore-3 issues-1 --snapshot pathmemory_v2 --flat $F --trials 5 --break-ui --tag v2-broken-flatcov
uv run python -m pathmemory.compare normal=results/v2-normal/eval.jsonl broken=results/v2-broken/eval.jsonl \
  ablation=results/v2-ablation/eval.jsonl broken_flat_pinned=results/v2-broken-flatcov/eval.jsonl
```
