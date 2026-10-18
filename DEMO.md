# Demo video script (v2, about 2:45)

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

## Script

**0:00–0:20 · The problem** (UI, v2 composition tab, top card)
> "Browser agents redo the same navigation every task. Memory usually means saved trajectories. Here the dashboard
> no longer shows repository links, so the trajectory that starts there is dead. Can memory still get the agent to
> the New Issue form for primer/design?"

**0:20–0:45 · What memory knows** (scroll to "1 · Training episodes")
> "Memory was built from ten successful runs of *training* tasks only. None of them is this task. Each graph edge
> is a click that was verified to lead to a page, and it remembers which run taught it."
Click the `{repo}` edge on the graph: the info box shows `learned from: explore-3`. Click `New Issue`: `issues-1`.

**0:45–1:15 · The graph's decision** (scroll to "2 · The graph's decision", LIVE QUERY badge)
> "This is FalkorDB answering now. Normally the route is dashboard → repo → Issues → New Issue, all from one run.
> With the dashboard step banned, the same Cypher query returns Explore → design → Issues → New Issue: Explore and
> the repo link from explore-3, Issues and New Issue from issues-1."
Point at the gold badges, then at "No single past run contains this route ✓" and "Flat replay finds 0 route(s)".
Open "Cypher" briefly.

**1:15–2:15 · Real execution** (press **Run composed route (v2, links hidden)**)
> "Now a real run: Chromium, real model, Gitea reset first, memory is a read-only copy."
While it runs (Live tab + browser window): the dashboard has no repo list → event "step failed: link
'{owner}/{repo}': missing" → "rerouted via /explore/repos …" → four REPLAY steps, each followed by a green
"✓ verified … owner=primer repo=design" → LLM steps fill the title, pick carol, press Create Issue.
At the end, read the status line:
> "Checker passed, memory replay reached the goal page, six model calls, ended on primer/design/issues/4, and the
> memory snapshot is unchanged."

**2:15–2:40 · Ablation** (memory selector → "v2 ablated"; or v2 tab → "show ablated graph")
> "Remove the one bridge edge, taught only by explore-3, from a copy of the graph. The same query now returns no
> route."
Recorded runs tab → open `ablation / graph` (RECORDED label):
> "In the evaluation the agent still finished by itself, but memory replay reached the page 0 of 5 times, against 5
> of 5 with the bridge. Single-trajectory flat replay: also 0 of 5."

**2:40–2:50 · Honest summary** (Results tab, v2 tables)
> "Every mode passed the checker; the difference is that the graph composed a route no run contained and executed
> it, verified, at lower model cost. One task, five trials: a demonstration, not a benchmark."

## If the live run fails on camera

Say so, open the RECORDED composed run (Recorded runs → `broken / graph`, 2026-10-18 18:28) and walk the same events
with screenshots. Never present the recorded run as live.
