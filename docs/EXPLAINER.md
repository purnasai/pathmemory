# PathMemory — one-page explainer

**One sentence:** PathMemory stores the navigation a browser agent has *verified* on a website as a FalkorDB graph
of page templates, so later tasks replay known routes without the LLM and reroute around steps that break.

**The problem:** an LLM browser agent rediscovers the same clicks on every task (open the repo → Settings →
Collaborators), and every click is a paid LLM call. Pasting past trajectories into the prompt ("flat memory")
makes prompts bigger without saving work.

## 1. Graph data model (`graph.py`)

```
(:State {key, route, title})          page TEMPLATE, e.g. "/:owner/:repo/settings/collaboration"
(:State)-[:ACT {eid, role, name, scope, pre, successes, failures}]->(:State)
                                      a verified navigation click, e.g. link "Settings", link "{repo}"
(:Task {id, goal})-[:WORKED_AT {steps}]->(:State)
                                      where a past task did its real work, and what it did there
```

- **Templates, not URLs** (`state.py`): `/byteblaze/dotfiles/...` and `/primer/design/...` are one node, so a route
  learned on one repo works on all. Values (`owner=primer, repo=design`) are kept as *bindings*.
- **Elements by meaning, not id:** BrowserGym's element ids change every page load, so a click is stored as role +
  accessible name (+ landmark `scope` to tell the top-bar "Issues" from the repo tab "Issues"). Entity names are
  templated: clicking "dotfiles" is stored as `{repo}`. Badge counts are stripped ("Issues 4" → "Issues").
- **`pre`** = clicks needed first on the same page (opening a dropdown before "Settings").

## 2. How one task runs (`agent.py`)

1. **Choose (1 LLM call):** given the goal and the list of known pages (+ what past tasks did there), pick the
   destination template and the bindings (`owner`, `repo`).
2. **Route (Cypher):** shortest verified path from the current page to that template.
3. **Replay (no LLM):** for each edge, find the element by role + name + scope on the live page, click it.
4. **Verify:** the next page must match the expected template. If not, or the element is missing → the edge is
   banned for this run, its `failures` incremented, and FalkorDB is asked for another route (max 2 reroutes).
5. **Hand over:** the LLM gets a note ("memory replayed navigation to <exact URL>; past tasks here did …") and does
   the real work (fill forms, press buttons). Replayed steps are written into the base agent's history so its
   prompt stays consistent.

## 3. The query that matters

```cypher
MATCH (a:State {key:$src}), (b:State {key:$dst})
MATCH p = (a)-[:ACT*1..6]->(b)                                  -- any path up to 6 clicks
WHERE all(r IN relationships(p)
          WHERE r.successes > 0 AND NOT r.eid IN $banned)        -- only verified, non-broken steps
RETURN [n IN nodes(p) | n.key], [r IN relationships(p) | ...],
       length(p) AS hops, reduce(f=0, r IN relationships(p) | f + r.failures) AS fails
ORDER BY hops, fails LIMIT 3                                    -- shortest, then most reliable
```

Because it searches over *edges*, not stored trajectories, a route can mix edges from different tasks. That is why
the graph is necessary: the recovered route `/ → Explore → {repo} → Issues → New Issue` used by `issues-2` combines
hops learned in three different runs and exists in no single one.

## 4. Design decisions and why

| Decision | Why |
|---|---|
| Replay only links/tabs/menu items | Navigation is safe to repeat; data changes (forms, buttons) stay the LLM's decision |
| No `goto(url)` action for any mode | Otherwise agents could type URLs and skip navigation, hiding the effect of memory |
| Flat baseline = top-3 trajectories in the prompt (AWM-style), same hint channel | Fair comparison: same information, different structure |
| Learn only from successful runs; memory frozen for evaluation | No leaking answers from test tasks |
| Local Gitea instead of WebArena GitLab | User constraint: no 30+ GB downloads; reset + seed takes 9 s |
| Hint names the exact URL where replay ended | Fixed a real bug: after a fork the agent landed on the same template and thought it was back at the start |

## 5. Results (honest)

| | No memory | Flat | Graph |
|---|---|---|---|
| Normal UI, 14 tasks: success | 14/14 | 14/14 | 13/14 |
| — input tokens per task | 13.9k | 16.6k | **10.3k** |
| UI broken, after one repair run (4 tasks): success | – | 4/4 | 3/4 |
| — input tokens per task | – | 36.4k | **15.5k** |

Limits: one site, one model, small samples, a UI break we chose. Memory saves cost; it rarely changes success.

## 6. Likely judge questions

- **Why a graph and not a list of trajectories?** Routes are composed from edges across tasks, and a failure on one
  shared edge changes every route through it. A list can do neither without reimplementing graph search.
- **What if a page looks the same but isn't?** Every replayed click is verified against the expected template; a
  mismatch stops replay and reroutes or hands back to the LLM.
- **Why didn't success go up?** This model already solves almost every task here. The gain is fewer LLM calls and
  tokens, and recovery after the UI changes.
- **Where does the LLM still decide?** Picking the destination page, and every action that changes data.
- **What failed?** `repos-3` (forking): the model doesn't recognise a finished fork. It also fails without memory.
- **How would it scale?** More sites → more templates per site (`State.key` would gain a site prefix); routes stay
  bounded (≤ 6 hops) so the query stays cheap.
