# Demo video script (v2, about 2:45)

Tracks: 01 — Agents That Act on Connected Data (primary), 02 — Agent Memory and Coordination (secondary).

Everything shown is the real UI and a real browser. The one run done live on camera is labelled LIVE in the UI;
recorded runs are labelled RECORDED. Do not cut the live run's waiting time into a fake speed-up; trim with a
visible cut if needed.

## Before recording

```bash
docker compose up -d && uv run python -m pathmemory.repro fixture && uv run python -m pathmemory.repro load
uv run pathmemory-ui        # open http://localhost:8795, browser at ~1500x950
```
Have a terminal visible for the first 10 s. The live run opens a second, visible Chromium window; place it to the
right of the UI. A live run costs about $0.002 and takes about 75 s (slowed so each click is visible).

## Recording checklist

- [ ] `docker compose up -d`, then `uv run python -m pathmemory.repro fixture` → `"ok": true` (fixture `32f2a9ca533fd2ce`)
- [ ] `uv run python -m pathmemory.repro load` → v2 `ff0899ff00fbb4d5`, ablated `93e0b6bd12e2831c`
- [ ] `.env` points at the OpenAI key (needed for the live run only)
- [ ] `uv run pathmemory-ui`, browser at http://localhost:8795, window about 1500×950, zoom 100 %
- [ ] Header shows **memory: v2 — training-only (fingerprinted)** and chip `pathmemory_v2 · ff0899ff00fbb4d5`
      (if not, pick it in the selector). The default tab is **v2 composition**.
- [ ] The **Live run** tab may show the previous live run; its status line says `run live at <time>`. That is fine:
      the new run replaces it. Do not show an old live run as if it were happening now.
- [ ] Screen recorder covers the UI and the place where the Chromium window will open (it appears ~10 s after
      pressing Run, after the Gitea reset).
- [ ] Rehearse once off-camera (costs ~$0.002), then `repro fixture` again before the real take.

## Click sequence (about 2:45)

| time | click / show | say |
|---|---|---|
| 0:00 | **v2 composition** tab, top card visible | "A browser agent, a held-out task: create an issue in primer/design and assign carol. The dashboard's repository links are hidden. Can memory still get the agent to the New Issue form?" |
| 0:15 | scroll to **1 · Training episodes** | "Memory comes from ten successful runs of *training* tasks, recorded independently. None is this task." |
| 0:25 | on the graph, click edge **{repo}** (Explore → :owner/:repo) → info box `learned from: explore-3`; click edge **New Issue** → `issues-1` | "Every edge is a click verified to lead to a page, and FalkorDB stores which run taught it." |
| 0:40 | scroll to **2 · The graph's decision** (red **LIVE QUERY** badge); click **show on graph** under *Usual route* | "FalkorDB, queried now. Normally: dashboard → repo → Issues → New Issue, all from one run." |
| 0:50 | click **show on graph** under *Dashboard link unavailable* | "Ban the missing dashboard step and ask again: Explore → design → Issues → New Issue." |
| 0:58 | point at the hop table's gold badges | "Explore and the repository link come from explore-3, Issues and New Issue from issues-1. Two separate runs." |
| 1:05 | scroll to **No single past run contains this route ✓** | "No training run contains this route, and single-trajectory replay finds zero routes. Only the graph join does." |
| 1:12 | scroll to **3 · Run it now** (red **LIVE** badge); click **Run composed route (v2, links hidden)** | "Now for real: Chromium, the real model, Gitea reset first, memory is a read-only copy." |
| 1:15–1:30 | **Live run** tab opens; status shows the pulse while Gitea resets; the Chromium window opens | (wait; mention that the site was reset to a known state) |
| 1:30 | Chromium on the dashboard: repository list empty. Event **step failed: link '{owner}/{repo}': missing** | "The dashboard link memory expected is not there. Replay does not guess." |
| 1:35 | events **route: / → /explore/repos → …**, **rerouted via …** | "It bans that step and FalkorDB returns the composed route." |
| 1:40–2:00 | four **REPLAY** steps in the list and in Chromium: Explore, design, Issues, New Issue; after each a green **✓ verified … owner=primer repo=design** | "Each click is replayed without the model, and after each one the page and the owner and repo are checked." |
| 2:00–2:10 | **LLM** steps: title, carol, Create Issue | "Memory only navigates. The model does the data-changing part." |
| 2:10 | final status line: **LIVE run live at … · checker: passed · memory replay reached the goal page · … · memory pathmemory_v2 unchanged ✓** | "Checker passed, replay reached the page, memory unchanged." |
| 2:15 | **v2 composition** tab → *Ablation* card → **show ablated graph** (selector switches to *v2 ablated*) | "Now remove the one bridge edge, taught only by explore-3. The same query returns no route." |
| 2:22 | **4 · Recorded runs** table (grey **RECORDED** badge) → row **ablation / graph** → **open** | "This is a recorded run from the evaluation, not live. Replay stopped at the dashboard; the model found its own way and still passed." |
| 2:32 | stay on that recorded run: events **step failed … missing**, **no route**, all steps **LLM** | "That is the honest picture: without the graph join the base model still completes the task. What disappears is verified replay of steps from other runs. Across five trials: 5 of 5 with the graph, 0 of 5 with the bridge removed, 0 of 5 for single-trajectory replay." |
| 2:40 | **Results** tab, v2 rows | "Every mode passed the checker. One task, five trials: a demonstration, not a benchmark." |

Do not say: faster, more successful, statistically significant, multi-agent.

## If the live run fails on camera

Say so, then open **4 · Recorded runs → broken / graph → open** (RECORDED, 2026-10-18 18:28) and walk the same
events with its screenshots. Never present the recorded run as live.
