# PathMemory — results (v1, 2026-10-16)

> **v2 (2026-10-18):** new training-only memory and a four-mode comparison on the composition case are in
> [docs/evidence/v2/FAIR_COMPARISON.md](docs/evidence/v2/FAIR_COMPARISON.md). v1 memory contained a repair episode of the test task
> `members-2`; the v1 numbers below are kept as recorded.

> **Correction (2026-10-18, branch `p0-correctness`):** the "LLM calls" columns below count LLM-chosen browser steps, not model calls. Counting the destination chooser and parse retries, graph mode made **more** model calls than no memory on the normal UI (4.64 vs 4.21 per task); the input-token savings stand. `repos-5` was run twice with different goals. v1 evaluation also wrote failure counts to its own memory and did not reset the site before read-only tasks. Details and corrected numbers: [docs/evidence/v1-derived/CORRECTIONS.md](docs/evidence/v1-derived/CORRECTIONS.md).

Same agent (AgentLab GenericAgent), same model (`gpt-6-luna`), same prompts, action set (`chat` + `bid`, no `goto`)
and 15-step budget in every mode. Only the memory differs:

- **none**: no memory
- **flat**: top-3 most similar past trajectories pasted into the prompt (Agent Workflow Memory style)
- **graph**: FalkorDB picks a destination page, replays the verified navigation route without the LLM,
  checks every page on arrival, reroutes around failed steps, then hands over to the LLM

Memory is learned from 8 training tasks (7 succeeded) plus 2 Explore tasks, then frozen.
Test tasks are different tasks in the same groups (members, issues, profile, repos, social).

## 1. Held-out tasks, normal UI (14 tasks)

| Mode | Success | Avg steps | Avg LLM calls | Avg replayed | Avg input tokens | Avg seconds |
|---|---|---|---|---|---|---|
| none | 14/14 | 4.1 | 4.1 | 0.0 | 13,879 | 21.4 |
| flat | 14/14 | 4.3 | 4.3 | 0.0 | 16,612 | 21.0 |
| graph | 13/14 | 5.3 | 3.5 | 1.8 | 10,332 | 24.0 |

- Graph: −15% LLM calls and −26% input tokens vs. no memory; flat memory *costs* +20% tokens and saves nothing.
- Graph takes more browser steps: replayed clicks are cheap but still steps, and on a few tasks
  (`issues-6`, `issues-7`) it navigated away from a dashboard that already showed the answer.
- The graph failure (`repos-3`, fork) was caused by the memory hint: after forking, the agent landed on a page of
  the same type and thought it was back at the start. The hint now names the exact URL where replay ended;
  re-run passed (4 steps; `results/v1-repeat2`). A repeat before that fix also failed (`results/v1-repeat`).
  Table shows the original failing run.

## 2. UI break: dashboard repository links hidden

`HIDE_DASHBOARD_REPO_LINKS` (Playwright init script) removes every repo link from the dashboard, so the
remembered first step `/ → {owner}/{repo}` no longer exists.

### Before any repair is learned (5 tasks)

| Mode | Success | Avg steps | Avg LLM calls | Avg replayed | Avg input tokens |
|---|---|---|---|---|---|
| none | 3/5 | 11.0 | 11.0 | 0.0 | 40,656 |
| flat | 4/5 | 8.6 | 8.6 | 0.0 | 39,298 |
| graph | 4/5 | 9.2 | 9.2 | 0.0 | 43,058 |

The graph detects the broken step (`edge_failed: no link '{owner}/{repo}'`) but knows no other way in, so it
falls back to the LLM — no benefit, slight overhead.

### After learning from ONE repair episode (4 held-out tasks)

The no-memory agent's successful `members-2` run under the break (it found Explore → repo) is added to both
memories. Graph and flat get exactly the same trajectory.

| Mode | Success | Avg steps | Avg LLM calls | Avg replayed | Avg input tokens |
|---|---|---|---|---|---|
| flat | 4/4 | 8.0 | 8.0 | 0.0 | 36,352 |
| graph | 3/4 | 9.0 | 5.8 | 3.2 | 15,535 |

Per task (graph vs flat):

| Task | flat | graph | Graph route after the failed step |
|---|---|---|---|
| members-4 (private repo; all modes failed before repair) | OK, 14 steps, 73.5k tok | **OK, 7 steps, 8.0k tok** | `/ → Explore → {repo} → Settings → Collaborators` |
| issues-2 | OK, 7 steps, 23.2k | OK, 9 steps, 15.0k | `/ → Explore → {repo} → Issues → New Issue` |
| issues-5 | OK, 6 steps, 28.8k | OK, 5 steps, 6.7k | `/ → Explore → {repo} → Issues` |
| repos-3 | OK, 5 steps, 19.9k | FAIL (15 steps) | `/ → Explore → {repo}` — replay correct, LLM then misread the finished fork (the no-memory agent made the same mistake before repair) |

**Composition (audited 2026-10-18 with `uv run python -m pathmemory.provenance` (output: `results/v1-repaired/provenance.json`)):** ACT edges do not store their source task, so the audit
re-derives which saved episode taught each replayed hop.

- `issues-2` and `issues-5` are genuinely composed: `/ → Explore` (from `explore-1` or the repair episode),
  `Explore → {repo}` (repair episode `members-2` only), `{repo} → Issues → New Issue` (`issues-1` only).
  No single episode contains either route. Both succeeded.
- `members-4` and `repos-3` are **not** composed: every hop of their route also appears in the one repair episode
  (`members-2`). Flat memory was given that same trajectory, so on `members-4` the difference
  (7 steps / 8.0k tokens vs. 14 / 73.5k) comes from replaying the route without the LLM, not from composition.
- An earlier version of this file said every recovered route was composed and none was in a single trajectory.
  That was wrong for two of the four tasks.

Excluding `repos-3`, graph used **~4× fewer input tokens than flat** after the repair (9.9k vs 41.8k avg).

## Honest limits

- Small samples (14 / 5 / 4 tasks, one run each). Differences of one task are noise; the token/LLM-call
  differences are consistent across tasks, the success differences are not.
- One site (local Gitea I seeded) and one model. Not WebArena; not comparable to any leaderboard.
- Success is the same across modes on the normal UI: with this model, memory buys efficiency, not success.
- The UI break is synthetic (one init script). It is a realistic kind of change, but I chose it.
- `repos-3` is unreliable for this model in any mode (it doesn't recognise a completed fork).
- Section 1 used memory built by the first learner version; the detour-recording fix came later (section 2).

## Reproduce

```bash
docker compose up -d
uv run python -m pathmemory.run learn --tag v1                       # TRAIN -> memory
uv run python -m pathmemory.run eval --tag v1                        # 14 tasks x 3 modes
uv run python -m pathmemory.run learn explore-1 explore-2 --keep --tag v1-alt
uv run python -m pathmemory.run recovery --tag v1                    # UI break, before repair
# rebuild memory with the repair episode (see learn.ingest), then:
uv run python -m pathmemory.run recovery members-4 issues-2 issues-5 repos-3 --modes flat graph --tag v1-repaired
uv run python -m pathmemory.report results/v1/eval.jsonl --select both
```
