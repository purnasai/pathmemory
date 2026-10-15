# PathMemory

**FalkorDB procedural memory for browser agents: remember how a website works, reuse it on new tasks,
and route around steps that break.**

Browser agents rediscover the same navigation on every task: open the repo, find Settings, find Collaborators.
Every one of those clicks is an LLM call. PathMemory stores what the agent has *verified* about a site as a graph
in FalkorDB and lets later tasks reuse it:

- **Pages are templates.** `/byteblaze/dotfiles/settings/collaboration` and `/primer/design/settings/collaboration`
  are the same node, `/:owner/:repo/settings/collaboration`, so a route learned on one repo works on every repo.
- **Steps are verified clicks.** An edge exists only if clicking that element (by role + accessible name, e.g.
  link `Settings`, link `{repo}`) actually led to the next page. Edges count successes and failures.
- **Routes are graph queries.** A bounded variable-length Cypher match finds the shortest, least-failed path,
  so a route can combine steps learned in different tasks.
- **Replay without the LLM, check every page.** Navigation clicks are replayed directly; the page after each click
  must match the expected template. If a step fails, it is banned for the run, recorded as a failure, and
  FalkorDB is asked for another route.
- **The LLM still does the real work.** Memory only replays navigation (links, tabs, menu items). Anything that
  changes data — filling forms, pressing buttons — is always the LLM's decision.

![Recovery run in the demo UI](docs/ui_recovery.png)
*A held-out task with the UI broken: the remembered dashboard link is gone (red). FalkorDB reroutes through
Explore (green) using steps learned in three different tasks; 4 clicks are replayed with no LLM call, then the
LLM adds the collaborator.*

## Results (local Gitea, `gpt-6-luna`, same agent/prompt/budget in every mode)

| Experiment | No memory | Flat memory (top-3 past trajectories in prompt) | **PathMemory (graph)** |
|---|---|---|---|
| Normal UI, 14 held-out tasks — success | 14/14 | 14/14 | 13/14 |
| — avg input tokens | 13.9k | 16.6k | **10.3k (−26%)** |
| — avg LLM calls | 4.1 | 4.3 | **3.5** |
| UI break, after one repair episode (4 tasks) — success | – | 4/4 | 3/4 |
| — avg input tokens | – | 36.4k | **15.5k** |

- Flat memory makes prompts bigger and saves nothing; the graph turns memory into skipped LLM calls.
- Under a UI break the graph detected the dead step on every task and rerouted. On `members-4` (which no mode
  could solve before the repair) it took 7 steps / 8k tokens vs. flat memory's 14 steps / 73.5k.
- With this model, memory changes **cost**, not success. Samples are small and on one self-built site —
  see [RESULTS.md](RESULTS.md) for every number, failure analysis and limits.

## How it works

```
 BrowserGym observation ──► state.py: URL → page template, element → (role, name, landmark), entities → {owner}/{repo}
                                │
 learn.py (successful runs) ───►│ (:State)-[:ACT {name, pre, successes, failures}]->(:State)
                                │ (:Task)-[:WORKED_AT {steps}]->(:State)            FalkorDB
                                ▼
 agent.py (wraps AgentLab GenericAgent)
   1. one LLM call: which known page does this goal need, and which owner/repo?
   2. Cypher: shortest verified route from the current page            ──► find_route
   3. replay clicks (no LLM), check each page; on failure ban the edge,
      record it, ask FalkorDB for another route                       ──► report_failure
   4. hand over to the LLM with what past tasks did on that page
```

Baselines use the same hint channel and the same frozen memory input, so the comparison is about the memory
structure, not about who saw more data.

## Quick start

```bash
uv sync && uv run playwright install chromium
docker compose up -d                                   # FalkorDB :6391 (browser UI :3391), Gitea :3300
uv run python -m pathmemory.site.seed --reset          # ~9 s: recreate and seed Gitea
# .env: PATHMEMORY_ENV_FILE=<file with OPENAI_API_KEY and OPENAI_MODEL>

uv run python -m pathmemory.run learn --tag v1         # 8 training tasks -> memory
uv run python -m pathmemory.run eval --tag v1          # 14 held-out tasks x {none, flat, graph}
uv run python -m pathmemory.run recovery --tag v1      # same, with dashboard repo links hidden
uv run python -m pathmemory.report results/v1/eval.jsonl
```

Gitea login: `byteblaze` / `hackathon123`. 24 tasks in 6 groups live in `src/pathmemory/site/tasks.py`, each
checked deterministically (Gitea API state, final URL, or the agent's answer).

### Demo UI

```bash
uv run pathmemory-ui        # http://localhost:8795
```

- **Run replay**: any saved run step by step — screenshot, LLM vs. replayed steps, failed step and reroute
  highlighted on the graph.
- **Results**: all three experiments; click any cell to replay that run.
- **Route query**: pick two pages, tick steps to treat as broken, and watch FalkorDB find a different route
  (with the Cypher it runs).

### MCP server

Any MCP client can use the memory. `.mcp.json` registers it for Claude Code.

```bash
uv run pathmemory-mcp       # stdio
```

| Tool | Does |
|---|---|
| `list_pages` | known page templates and what past tasks did there |
| `resolve_url` | concrete URL → template + placeholder values |
| `page_memory` | past work on a page and the verified clicks leaving it |
| `find_route` | up to 3 verified routes, optionally avoiding broken steps |
| `record_step` | teach one verified navigation click (links/tabs/menu items only) |
| `report_failure` | mark a remembered step as failed |

Fixed, parameterised Cypher only; no tool accepts Cypher. `tests/test_mcp.py` runs the full
route → break → teach → recompose story over stdio.

## Layout

```
src/pathmemory/
  state.py        page templates, semantic steps, element lookup
  graph.py        FalkorDB schema + queries
  learn.py        successful runs -> graph + flat store
  agent.py        PathMemory agent (none / flat / graph)
  run.py          learn / eval / recovery experiments
  service.py      shared API for UI + MCP
  ui.py, static/  demo UI
  mcp_server.py   MCP tools
  site/           Gitea seed data and BrowserGym tasks
```

## Limits

One site, one model, small samples, a UI break I chose; not WebArena and not comparable to any leaderboard.
The model succeeds on nearly every task without memory, so the measured gain is efficiency. Details in
[RESULTS.md](RESULTS.md).
