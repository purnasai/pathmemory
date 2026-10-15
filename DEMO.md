# Demo video script (about 3 minutes)

Before recording: `docker compose up -d`, `uv run pathmemory-ui`, open http://localhost:8795 at 1600×950,
and have FalkorDB's browser (http://localhost:3391, graph `pathmemory`) open in a second tab.

| Time | Screen | Say |
|---|---|---|
| 0:00–0:20 | Title / README top | "Browser agents relearn the same navigation on every task: find the repo, find Settings, find Collaborators. Every click is an LLM call. PathMemory gives the agent a memory of how the website works, in FalkorDB." |
| 0:20–0:45 | Demo UI, graph only | "Each node is a page *template*: one node for every repo's collaborator page. Each edge is a click the agent actually did and verified, with success and failure counts. These came from 8 ordinary training tasks." Point at `/:owner/:repo` → Settings → Collaborators. |
| 0:45–1:20 | Results tab → Normal UI → click `members-2 / graph` | "On a new task, one LLM call picks the destination page. FalkorDB returns the route, and these green REPLAY steps run without the LLM. Then the LLM does the actual work: type carol, click Add." Back to Results: "Across 14 held-out tasks: same success, 26% fewer input tokens. Flat memory, pasting past trajectories into the prompt, costs *more*." |
| 1:20–1:50 | Run replay → UI break before repair → `members-2 / graph` | "Now we break the site: the dashboard repo links disappear. Memory's first step fails — red. It knows no other way yet, so the LLM takes over and finds one through Explore. That run gets learned." |
| 1:50–2:30 | UI break after repair → `members-4 / graph` (default view); click steps 0–4 | "Next task, different repo, private, which no mode could solve before. The dashboard step fails, FalkorDB reroutes: Explore from one task, the repo link from the repair run, Settings and Collaborators from a third. No single past run contains this route. Four clicks replayed, 7 steps, 8k tokens. Flat memory needed 14 steps and 73k." |
| 2:30–2:50 | Route query tab: tick the dashboard step, show the route and the Cypher | "It's a plain graph query: shortest verified path that avoids failed steps. The same queries are exposed as MCP tools, so any agent can use the memory." |
| 2:50–3:00 | README results table | "Honest limits: one site, one model, small samples. The model already succeeds without memory, so the gain is cost and recovery, not raw success." |

Fallback if anything breaks during recording: every screen is a saved run, so nothing calls the LLM or Gitea live
except the Route query tab, which only needs FalkorDB.
