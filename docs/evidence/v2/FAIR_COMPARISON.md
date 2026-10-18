# Four-mode comparison on the composition case (v2, 2026-10-18)

**This is a focused demonstration on one held-out task, not a benchmark.** 5 trials per mode and condition,
45 trials total, all run once and all reported. Estimated total cost $0.107.

## Setup (identical for every mode)

| | |
|---|---|
| Task | `issues-2` (held out; checker unchanged): create issue "Update color tokens" in primer/design, assign carol. `task_sha fd7a8fde540c` in every row |
| Model / agent | `gpt-6-luna` (temperature 1, the only value it accepts), AgentLab GenericAgent, actions `chat`+`bid` (no `goto`), 15-step budget |
| Training evidence | v2 memory from 10 successful training episodes ([memory/manifest.json](memory/manifest.json)); graph `pathmemory_v2` fingerprint `ff0899ff00fbb4d5`; flat store sha `6c743fd14bc18df2`. Both built from the same episodes in one build |
| Isolation | Before **every** trial: Gitea recreated and seeded, fixture fingerprint `32f2a9ca533fd2ce` checked; graph snapshot copied into a working graph; flat store copied once per batch. Every row reports `memory.unchanged: true`; snapshot and flat-store fingerprints are checked after each trial |
| Order | trial 1 of all 4 modes, then trial 2, … (interleaved) |
| Accounting | `accounting_consistent: true` in all 45 rows (chooser + base tokens = AgentLab's own total). Cost = AgentLab tracker × litellm price table ($0.10/M in, $0.50/M out). This is an estimate, not checked against the OpenAI bill |

Modes: **none** (no memory). **flat** (top-3 trajectories by goal-word Jaccard, each with its goal and every step
"on <url>: <action>", as prompt text). **flatreplay** (same destination chooser, matcher, entity checks, reroute
limit and LLM fallback as graph, but a route must be a contiguous stretch of one stored trajectory). **graph**
(FalkorDB route over all learned steps).

Conditions: **normal** UI. **broken**: the existing `HIDE_DASHBOARD_REPO_LINKS` script hides the dashboard's
`owner/repo` links. **ablation**: broken UI, graph mode on `pathmemory_v2_ablated` (bridge step removed).

## Results (means over 5 trials; raw rows in [runs/](runs/), tables by `python -m pathmemory.compare`)

"Replay reached goal" = the memory route was replayed to its last hop with no failed check after it. A success
without it is an **LLM-fallback success**, not a memory success.

| condition | mode | success | replay reached goal | model calls | input tok | output tok | est. $ | browser steps | replayed | episode s | reset s | route hops | recoveries | failed checks | wrong-target |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| normal | none | 5/5 | – | 8.0 | 22,779 | 565 | 0.0026 | 8.0 | 0 | 38.2 | 9.6 | – | – | – | 0 |
| normal | flat | 5/5 | – | 8.2 | 26,359 | 572 | 0.0029 | 8.0 | 0 | 36.8 | 8.8 | – | – | – | 0 |
| normal | flatreplay | 5/5 | 5/5 | 6.0 | 14,788 | 466 | 0.0017 | 8.0 | 3.0 | 32.1 | 8.7 | 3 | 0 | 0 | 0 |
| normal | graph | 5/5 | 5/5 | 6.0 | 14,926 | 464 | 0.0017 | 8.0 | 3.0 | 31.7 | 9.1 | 3 | 0 | 0 | 0 |
| broken | none | 5/5 | – | 7.0 | 20,628 | 546 | 0.0023 | 7.0 | 0 | 32.8 | 8.1 | – | – | – | 0 |
| broken | flat | 5/5 | – | 7.6 | 25,389 | 618 | 0.0028 | 7.6 | 0 | 34.7 | 8.8 | – | – | – | 0 |
| broken | flatreplay | 5/5 | **0/5** | 8.4 | 23,718 | 631 | 0.0027 | 7.4 | 0 | 34.7 | 7.3 | 3 (failed) | 0 | 1 | 0 |
| broken | graph | 5/5 | **5/5** | **6.0** | **14,986** | 472 | **0.0017** | 9.0 | 4.0 | 33.5 | 8.5 | **4** | 1 | 1 | 0 |
| ablation | graph | 5/5 | **0/5** | 8.4 | 24,859 | 656 | 0.0028 | 7.4 | 0 | 36.7 | 8.3 | 3 (failed) | 0 | 1 | 0 |

"episode s" is the AgentLab episode wall time (browser start, login, agent and environment). "reset s" is the
Gitea recreate+seed before it, measured separately. Model calls include the chooser and parse retries.

## What this shows

1. **Composition happened in the browser, every time.** In all 5 broken-UI graph trials the dashboard step was
   found missing, banned for the run, and FalkorDB returned `/ → Explore → {repo} → Issues → New Issue`. All 4 hops
   were replayed (Explore, design, Issues, New Issue), each landing page and the owner/repo binding were verified,
   then the LLM filled the form and the unchanged checker passed. Source episodes on the route: explore-1, explore-3,
   issues-1 ([COMPOSITION.md](COMPOSITION.md)).
2. **Flat replay could not do this.** With the same chooser, matcher and fallback, its only route (from issues-1)
   failed at the dashboard and no single stored trajectory offered another: 0/5 replays reached the goal, and its
   5/5 task successes are LLM fallbacks.
3. **Ablation removes it.** Without the explore-3 bridge step, graph behaves like flat replay: 0/5 replays, 5/5
   LLM-fallback successes, the same cost as flat replay.
4. **The gain is cost, not success.** All 45 trials succeeded. Under the break, graph used 6.0 model calls
   vs 7.0 (none), 7.6 (flat), 8.4 (flatreplay), and 27–41% fewer input tokens. On the normal UI graph and flat
   replay are equal (both replay the issues-1 route; no composition is needed there).

## Where flat memory or no memory matches or beats graph

- **Normal UI: flat replay = graph** (6.0 calls, ~14.8k vs ~14.9k tokens, same 3 replayed steps). Composition adds
  nothing when one past episode already contains the whole route.
- **Browser steps under the break: none mode wins** (7.0 vs graph's 9.0). The break hides only exact
  `owner/repo` links; the activity feed still has issue links such as `primer/design#1`. Every LLM-driven run
  (none, flat, and flatreplay/ablation after fallback) clicked one, then the issue page's "New Issue" button: a
  2-click route. Graph replayed its 4-hop route instead. Memory had no such shortcut: the button is not a
  navigation link, so it is never learned as a replayable step. Graph still made fewer model calls, because
  replayed clicks need no LLM.
- **No-memory beat flat prompt memory** in both conditions (fewer tokens, equal or fewer calls).
- **Episode time** is about the same across modes (31.7–38.2 s); graph is not faster under the break (33.5 s vs
  32.8 s for none).

## Limitations

- One task, one site, one model. 5 trials per cell; the runs are nearly deterministic (identical token counts
  recur across trials), so trials are not independent samples. No significance claims.
- The UI break is partial (see the shortcut above). With a break that also removed the feed links, the LLM-only
  modes might need more steps. That was not run.
- `explore-3` was added for v2 because no existing training episode taught the Explore → repository step; the
  case was chosen after inspecting the training data. It is the only composition case tested.
- Costs are estimates from a public price table, not billing data.

## Reproduce

```bash
uv run python -m pathmemory.run build-memory results/v1/learn/* results/v1-alt/learn/* \
  results/v2-train/2026-10-18_17-56-16_PathMemory-none_on_pathmemory.explore-3_0 \
  --graph pathmemory_v2 --flat docs/evidence/v2/memory/flat_memory.json --manifest docs/evidence/v2/memory/manifest.json
uv run python -m pathmemory.run ablate --snapshot pathmemory_v2 --graph pathmemory_v2_ablated --edge fc698e14a7f1
F=docs/evidence/v2/memory/flat_memory.json
uv run python -m pathmemory.run eval issues-2 --modes none flat flatreplay graph --snapshot pathmemory_v2 --flat $F --trials 5 --tag v2-normal
uv run python -m pathmemory.run eval issues-2 --modes none flat flatreplay graph --snapshot pathmemory_v2 --flat $F --trials 5 --break-ui --tag v2-broken
uv run python -m pathmemory.run eval issues-2 --modes graph --snapshot pathmemory_v2_ablated --flat $F --trials 5 --break-ui --tag v2-ablation
uv run python -m pathmemory.compare normal=results/v2-normal/eval.jsonl broken=results/v2-broken/eval.jsonl ablation=results/v2-ablation/eval.jsonl
```
The saved training episodes live in the git-ignored `results/`; their hashes are in the manifest.
