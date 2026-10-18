# PathMemory

**Browser agents that remember how to navigate—and find another route when a link disappears.**

PathMemory stores learned browser steps in FalkorDB. When a familiar link is missing,
it joins steps from separate past runs into another route and checks each landing page
during replay. The current demo runs on a local Gitea instance through AgentLab and BrowserGym.

For example, one training run learns **Explore → repository** and another learns
**repository → Issues → New Issue**. PathMemory can join those steps when the usual
dashboard link is unavailable. The model chooses the destination and completes the form;
remembered navigation runs without additional model calls.

[Watch the three-minute demo](https://youtu.be/H7FJTGAeLQ4) ·
[Download the MP4](docs/media/pathmemory-demo.mp4) ·
[Run the walkthrough without an API key](#quick-start) ·
[Inspect the recorded evidence](docs/evaluation.md)

![Guided walkthrough in the demo UI](docs/ui_v2_composition.png)

## Quick start

Run from a source checkout with Python 3.12+, Docker Compose v2, and [uv](https://docs.astral.sh/uv/).
The demo uses ports 3300, 3391, 6391, and 8795.

```bash
git clone https://github.com/purnasai/pathmemory
cd pathmemory
scripts/reproduce_v2.sh
uv run pathmemory-ui
```

Open <http://localhost:8795> and follow **Learn → Lose a link → Watch replay**. The walkthrough
queries FalkorDB without calling a model. Browser execution is shown from saved runs when
their local traces are available; the video above includes the recorded browser execution.

The script starts the local services, recreates the Gitea
fixture, loads the published memory snapshots, and checks the route composition and ablation.
It does not need an API key. It uses the fixed Compose project `t12-pathmemory`, shared by
other checkouts on this machine; run it when no other demo or experiment is using those services.

To run the agent with a model:

```bash
cp .env.example .env
# Set OPENAI_API_KEY and OPENAI_MODEL in .env.
scripts/reproduce_v2.sh --with-llm
```

See [setup and usage](docs/getting-started.md) for browser dependencies, configuration,
MCP tools, storage behavior, and running individual tasks. Live browser runs use your API key.

## How it works

1. Successful training runs supply page templates and navigation steps identified by role,
   accessible name, and page landmark.
2. The model chooses a destination page and entity values for the new task.
3. A bounded Cypher query finds a route through remembered steps, including steps from different runs.
4. Replay checks visible targets and verifies the page template and chosen entities after each navigation.
   Failed steps are excluded for the rest of that run; the model takes over when replay stops.

The replay rules include duplicate-link handling and a legacy landmark exception.
The MCP write tool accepts caller-reported observations. See the
[architecture and verification boundaries](docs/architecture/README.md) for the exact behavior.

![Learning and replay architecture](docs/architecture.gif)

## Graph model and route query

```text
(:State {key, route, title})
(:State)-[:ACT {eid, role, name, scope, pre, successes, failures, sources}]->(:State)
(:Task {id, goal, cluster})-[:WORKED_AT {steps}]->(:State)
```

`State` nodes represent page templates; `ACT` edges store learned navigation outcomes and
their source episodes. The route query finds paths of at most six hops, excludes steps
that failed in this run, and prefers shorter paths with fewer recorded failures:

```cypher
MATCH (a:State {key:$src}), (b:State {key:$dst})
MATCH p = (a)-[:ACT*1..6]->(b)
WHERE all(r IN relationships(p) WHERE r.successes > 0 AND NOT r.eid IN $banned)
RETURN [n IN nodes(p) | n.key] AS keys,
       [r IN relationships(p) | r.name] AS steps,
       length(p) AS hops,
       reduce(f = 0, r IN relationships(p) | f + r.failures) AS fails
ORDER BY hops, fails LIMIT $k
```

The [runtime query](src/pathmemory/graph.py) also returns action metadata needed for replay.
The [architecture notes](docs/architecture/README.md) describe the schema and verification
boundaries; learning queries are implemented alongside routing in `graph.py`.

## Recorded results

The v2 experiment used one held-out task, one local Gitea site, one model, and five trials
per mode with dashboard repository links hidden.

| Mode | Task checker passed | Replay reached target page | Mean model calls |
|---|---|---|---|
| No memory | 5/5 | — | 7.0 |
| Flat prompt | 5/5 | — | 7.6 |
| Single-trajectory replay | 5/5 | 0/5 | 8.4 |
| Graph replay | 5/5 | 5/5 | 6.0 |
| Graph with bridge removed | 5/5 | 0/5 | 8.4 |

Graph replay used fewer model calls in this case. Every mode completed the task, and the
agent without memory used fewer browser actions. There was no demonstrated latency or
task-success advantage. This is a focused demonstration, not a general browser benchmark.

[Evaluation notes](docs/evaluation.md) explain the baselines, limitations, raw results, and
historical v1 corrections. The figures above are recorded results, not a new run of this checkout.

## Development

```bash
uv sync --locked
uv run pytest -q -m 'not integration'
uv run ruff check .
uv run ruff format --check .
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for integration tests and verification after changes.

```text
src/pathmemory/
  agent.py, state.py, graph.py, learn.py   navigation, matching, storage, learning
  prompts.py, config.py                   model text and configuration
  service.py, mcp_server.py                graph API and MCP tools
  evaluation/                             experiment runner, reports, evidence checks
  demo/                                   FastAPI UI, run artifacts, browser assets
  site/                                   Gitea fixture and BrowserGym task definitions
  run.py, report.py, compare.py, repro.py  compatibility command entry points
  ui.py                                   compatibility UI entry point
  probe.py                                compatibility for saved probe arguments
docs/
  getting-started.md, evaluation.md        setup and experiment documentation
  architecture/                           design notes and interactive diagram
  evidence/                               published results and memory snapshots
  hackathon/                              submission, recording script, blog draft
tests/                                    unit and container integration tests
scripts/reproduce_v2.sh                    local reproduction workflow
```

Built for Graph Hacks 2026 with Claude Code assistance. Submission material lives in
[docs/hackathon/](docs/hackathon/).
