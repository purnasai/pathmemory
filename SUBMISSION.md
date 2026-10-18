# PathMemory: Graph Hacks submission (Track 02: Agent Memory and Coordination)

Repo: https://github.com/purnasai/pathmemory. Built 16–18 Oct 2026 for the hackathon (first commit 2026-10-16 01:57 IST).

## One-line pitch
Procedural memory for browser agents in FalkorDB: verified UI steps from separate past runs are joined by a Cypher
path query into a route no single run took, and the agent replays it in a real browser with every page and
entity checked.

## Problem
Browser agents rediscover the same navigation on every task, and memory is usually whole past trajectories. When
the page a trajectory starts from changes, that trajectory is dead, and the knowledge needed to get around it is
spread over runs that were about other tasks.

## How memory works
- `(:State)` = page template (`/:owner/:repo/issues`); `(:State)-[:ACT {role, name, scope, successes, failures,
  sources}]->(:State)` = a click verified to lead to that page, with the training runs that showed it;
  `(:Task)-[:WORKED_AT]->(:State)` = where past tasks did their work.
- Route = bounded variable-length Cypher match, excluding steps that failed in this run, shortest then least-failed.
- Replay is fail-closed (one visible, unambiguous element in the remembered landmark; href and landing page must
  match the chosen owner/repo). Evaluation never writes to memory.

## Verified result (v2, 2026-10-18)
Held-out task `issues-2`, dashboard repository links hidden, `gpt-6-luna`, 5 trials per mode, every trial reported:

- **Graph-composed replay reached the target page in 5/5 trials; single-trajectory flat replay (same chooser,
  matcher, checks, fallback) in 0/5; the graph with the one bridge step removed in 0/5.**
- The composed route `/ → Explore → design → Issues → New Issue` joins `explore-3` (Explore → repository) and
  `issues-1` (repository → Issues → New Issue); no training run contains it (automated test).
- Every mode passed the unchanged checker in every trial: **no task-success advantage**, no latency advantage, no
  significance claim. Graph used 6.0 model calls and $0.0017 per task against 7.0–8.4 calls and $0.0023–0.0029 for
  the others (litellm list price). No-memory used fewer browser actions (7 vs 9) via an activity-feed shortcut that
  memory cannot learn.
- Flat prompt memory's top-3 retrieval did not include the two essential runs; pinning them into its prompt did not
  change its path or cost.

Details: `docs/evidence/v2/FAIR_COMPARISON.md`, `COMPOSITION.md`, `DEMO_WALKTHROUGH.md`. v1 results (2026-10-16) are
kept as recorded with corrections in `docs/evidence/v1-derived/CORRECTIONS.md`; the v1 recovery memory contained a
test-task episode and is superseded by v2.

## Why FalkorDB is central
Routes are not stored anywhere: each one is a path query over edges written by different runs. Rerouting is the same
query with the failed edge banned. Remove the bridge edge and the route disappears; remove FalkorDB and graph mode
has nothing to replay.

## Limits
One self-seeded Gitea site (synthetic data), one model, one composition case, 5 trials per cell. The UI break is
partial. `explore-3` was added as a training task for v2 after inspecting the training data (v1's equivalent step
came from a test-task episode).

## Reproduce
```bash
git clone https://github.com/purnasai/pathmemory && cd pathmemory
scripts/reproduce_v2.sh             # no API key: fixture, v2 memory, provenance, composed route, ablation
scripts/reproduce_v2.sh --with-llm  # + browser runs (OpenAI key in .env)
uv run pathmemory-ui                # http://localhost:8795, "v2 composition" tab
```

## Demo video
Script in `DEMO.md` (about 2:45): training runs and edge provenance, the live Cypher decision, one live browser run
of the composed route, the ablation.

## AI assistance disclosure
Built with AI coding assistants (Claude Code wrote most code, tests and docs; ChatGPT/GPT-6 for design critique and
review), directed and reviewed by the author, who can explain the state templating, graph model, route query,
fail-closed replay and the evaluation. See README "AI assistance disclosure".
