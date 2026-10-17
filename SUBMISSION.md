# PathMemory: Graph Hacks submission (Track 02: Agent Memory and Coordination)

Repo: https://github.com/purnasai/pathmemory. Built 16–18 Oct 2026 for the hackathon.

## One-line pitch
Procedural memory for browser agents in FalkorDB. Verified navigation steps from past tasks become a graph of
page templates. New tasks get routes from a Cypher query, replay them without the LLM, check every page on
arrival, and reroute when a step breaks. The memory persists across tasks, processes and restarts.

## Problem
Browser agents rediscover the same navigation on every task, and every click costs an LLM call. Memory that
pastes past trajectories into the prompt (Agent Workflow Memory style) makes prompts bigger and can't combine
pieces of different runs. When the UI changes, a remembered trajectory breaks entirely.

## How memory works
- `(:State)` = page template (`/:owner/:repo/settings/collaboration`).
- `(:State)-[:ACT {role, name, successes, failures}]->(:State)` = a click verified to lead to that page. Outcome
  counts accumulate across runs, and failures are recorded when a remembered step breaks.
- `(:Task)-[:WORKED_AT]->(:State)` = where past tasks did their real work.
- Retrieval is a bounded variable-length Cypher match that excludes banned edges and orders by hops, then
  failures. Writing back: successful runs (experiments, or a live run with "learn" on) MERGE their verified
  steps. Six MCP tools expose the same memory to any MCP client.

## Verified results
All tables were recomputed on 2026-10-18 from the committed logs in `docs/evidence/`. Same agent (AgentLab
GenericAgent), same model (`gpt-6-luna`), same prompts, actions and 15-step budget in every mode.

**Normal UI, 14 held-out tasks:**

| Mode | Success | Avg LLM calls | Avg input tokens |
|---|---|---|---|
| No memory | 14/14 | 4.1 | 13,879 |
| Flat (top-3 past trajectories) | 14/14 | 4.3 | 16,612 |
| **Graph** | **13/14** | **3.5** | **10,332** |

**UI break (dashboard repo links removed), after learning from one repair episode, 4 tasks:**

| Mode | Success | Avg LLM calls | Avg input tokens |
|---|---|---|---|
| Flat | 4/4 | 8.0 | 36,352 |
| **Graph** | 3/4 | 5.8 | 15,535 |

Before any repair was learned (5 tasks): none 3/5, flat 4/5, graph 4/5. The graph found the dead step but knew no
other route.

- **Success caveat:** with this model, memory changes cost, not success. On the normal UI, graph is 13/14 against
  14/14. The failure (`repos-3`) is a hint problem that was fixed later; repeats: 1 failed before the fix, 1
  passed after.
- **Composition**, audited per hop with `python -m pathmemory.provenance`:
  - `issues-2` and `issues-5` replayed routes stitched from three different tasks (`explore-1`, repair run
    `members-2`, `issues-1`) that no single episode contains.
  - `members-4` and `repos-3` replayed a route the repair episode contains in full. There the gain over flat memory
    (`members-4`: 7 steps / 8.0k tokens against 14 / 73.5k) comes from replaying without the LLM, not from
    composition.
- **Persistence:** two separate processes, with a FalkorDB container restart between them, saw the same memory
  (11 templates, 11 steps, 10 worksites) and computed the same reroute around the broken step
  (`docs/evidence/persistence/`).

## Why FalkorDB is central
Routes are not stored anywhere. Each one is computed by the variable-length Cypher query over edges written by
different runs, with failure counts shared across every route that uses an edge. Rerouting after a failure is the
same query with the failed edge banned. Without FalkorDB, graph mode has nothing to replay.

## Limits
- Small samples, one run each: 14, 5 and 4 tasks.
- One self-seeded Gitea site and one model.
- The UI break is synthetic, chosen by me.
- Replayed clicks still count as browser steps.
- The compose file has no volume, so `docker compose down` deletes the memory.
- The "learn a new step live, then reuse it" demo is not reliable. The reliable live demo is `members-4` in graph
  mode with the UI broken.

## Reproduce
```bash
git clone https://github.com/purnasai/pathmemory && cd pathmemory
cp .env.example .env            # OPENAI_API_KEY
uv sync && uv run playwright install chromium
docker compose up -d && uv run python -m pathmemory.site.seed --reset
uv run pytest -q                # 12 tests
# recompute the published tables from the committed logs (no LLM needed):
uv run python -m pathmemory.report docs/evidence/v1/eval.jsonl
uv run python -m pathmemory.report docs/evidence/v1/recovery.jsonl
uv run python -m pathmemory.report docs/evidence/v1-repaired/recovery.jsonl
# full re-run with the LLM (~1 h; numbers vary run to run): see README "Quick start"
uv run pathmemory-ui            # http://localhost:8795
```

## Demo video
3 minutes maximum; the script is in `DEMO.md`. Show composition with `issues-2`. Show the cost gap with `members-4`
(the same trajectory was available to flat memory).

## AI assistance disclosure
Built with an AI coding assistant (Claude Code), directed and reviewed by the author, who can explain the state
templating, graph model, route query, replay and rerouting, and the evaluation.
