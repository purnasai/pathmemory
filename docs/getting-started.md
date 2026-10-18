# Setup and usage

PathMemory currently supports a local source checkout with its Gitea demo and published
evidence files. The Python package alone does not contain the fixture's Compose file or
all experiment artifacts.

## Requirements

- Python 3.12 or newer, uv, and Docker with Compose v2.
- Ports 3300 (Gitea), 6391 (FalkorDB), 3391 (FalkorDB browser), and 8795 (demo UI).
- Chromium for BrowserGym. The reproduction script installs it through Playwright.
- An OpenAI API key for model-driven runs. Loading memory and checking composition need no key.

Run all commands below from the repository root. The fixed Compose project name
`t12-pathmemory` means checkouts on the same machine share containers. Fixture reset
recreates the demo Gitea container and removes its current data; use it when no other run
is using these services.

## Load the demo

```bash
scripts/reproduce_v2.sh
uv run pathmemory-ui
```

Open <http://localhost:8795>. The Walkthrough tab guides you through learning steps,
excluding the usual dashboard link, and composing another route with a fresh FalkorDB query.
Step 3 includes the three-minute video; it does not require an API key or local run traces.
Results include all trials of the published v2 experiment. Historical v1 tables retain
explicit latest-attempt selection. Committed summaries are available in a fresh checkout;
screenshots and step traces for individual runs require their local `results/` directories.

If Chromium cannot start because system libraries are missing, install Playwright's
browser dependencies for your operating system:

```bash
uv run playwright install --with-deps chromium
```

That command may need administrator access to install operating-system packages.

## Configure model runs

```bash
cp .env.example .env
```

Set `OPENAI_API_KEY` and `OPENAI_MODEL` in `.env`, then run:

```bash
scripts/reproduce_v2.sh --with-llm
```

This adds one broken-UI graph run and one bridge-ablation run. Model calls incur API charges;
recorded cost estimates are in the [evaluation notes](evaluation.md). The script checks
snapshot fingerprints after the runs.

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | unset | API key for model-driven tasks |
| `OPENAI_MODEL` | `gpt-6-luna` | Model used by AgentLab |
| `PATHMEMORY_ENV_FILE` | unset | Additional file with key/model settings |
| `FALKORDB_HOST` | `localhost` | Graph host |
| `FALKORDB_PORT` | `6391` | Graph port |
| `GITEA_URL` | `http://localhost:3300` | Demo site |
| `PATHMEMORY_GRAPH` | `pathmemory` | MCP graph name |
| `PATHMEMORY_ROOT` | source checkout | Checkout containing `.env`, `docs/`, and `results/` |

Shell environment values take precedence over `.env`, which takes precedence over the
additional env file. Set `PATHMEMORY_ROOT` in the shell before starting an installed package
if its checkout is elsewhere. Changing the model can require changes to AgentLab's model
configuration; the recorded experiments used the default model.

## Run one task

```bash
uv run pathmemory --help
uv run pathmemory eval issues-2 --modes graph --break-ui \
  --snapshot pathmemory_v2 --flat docs/evidence/v2/memory/flat_memory.json --tag local-check
```

The older `uv run python -m pathmemory.run ...` command remains available. The same applies
to `pathmemory.report`, `pathmemory.compare`, `pathmemory.repro`, and `pathmemory.ui`.
Specialized checks now live under `pathmemory.evaluation`, for example
`uv run python -m pathmemory.evaluation.composition`.

The UI can also start a task in a visible Chromium window. v2 runs use a working copy of
the selected snapshot. The historical v1 demo memory supports live learning and restoration
from its first backup; it is separate from the v2 snapshots.

## MCP tools

```bash
uv run pathmemory-mcp
```

The server uses stdio. `.mcp.json` registers it for clients launched from this checkout.
Set `PATHMEMORY_GRAPH=pathmemory_v2` to query the loaded v2 memory instead of the default
graph. Write tools can modify the selected graph, so use a separate graph for teaching or
failure reports if you want to preserve published snapshots.

| Tool | Purpose |
|---|---|
| `list_pages` | List remembered page templates and past work |
| `resolve_url` | Resolve a URL to its template and entity values |
| `page_memory` | Read work and outgoing steps for a page |
| `find_route` | Find up to three routes, optionally avoiding step IDs |
| `record_step` | Store a navigation outcome reported by the caller |
| `report_failure` | Increment a step's failure count |

`record_step` does not run a browser or verify the supplied outcome. The caller must
observe the transition before recording it. See [verification boundaries](architecture/README.md).

## Storage and troubleshooting

- Gitea uses tmpfs. Recreating its container removes fixture changes.
- FalkorDB has no configured data volume. Restarting its container preserves its current
  filesystem; removing it with `docker compose down` removes that memory. Reload published
  snapshots with `uv run python -m pathmemory.repro load`.
- The reproduction script keeps existing containers with `--no-recreate`. A plain
  `docker compose up -d` can recreate a container when its image configuration changes;
  export any memory you need before deliberately replacing that container.
- Local browser traces, screenshots, and new result summaries live in ignored `results/`.
  Published summaries and memory dumps live in `docs/evidence/`.
- If service startup fails, inspect `docker compose ps` and `docker compose logs`. The
  script stops after a bounded health check instead of waiting indefinitely.
