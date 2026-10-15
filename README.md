# PathMemory

Graph-backed procedural memory for browser agents (FalkorDB + BrowserGym/AgentLab), tested on a local Gitea.

## Setup

```bash
uv sync && uv run playwright install chromium
docker compose up -d
uv run python -m pathmemory.site.seed --reset   # ~9s, recreate + seed Gitea
uv run python -m pathmemory.run profile-3 issues-6 members-1
```

`.env` points `PATHMEMORY_ENV_FILE` at the file holding `OPENAI_API_KEY` / `OPENAI_MODEL`.

- Gitea: http://localhost:3300 (byteblaze / hackathon123)
- FalkorDB: localhost:6391, browser UI http://localhost:3391
