# Route composition from separate training episodes (v2)

**Question:** can graph memory reach a goal page via a route that no single past episode contained, by joining
steps learned in different episodes, and can the browser agent actually execute it?

**Answer on this case: yes.** Details below; browser outcomes are in the last section and in
[FAIR_COMPARISON.md](FAIR_COMPARISON.md).

## Held-out task and condition

- Task `issues-2` (test set; definition and checker unchanged since v1, `task_sha fd7a8fde540c`): *Create an issue "Update color tokens" in primer/design and assign it to carol.*
  The checker reads the Gitea API (issue exists with that title and assignee carol).
- Condition: `HIDE_DASHBOARD_REPO_LINKS` (the existing UI-break init script) hides every `owner/repo` link on the
  dashboard, so the usual route `/ → {owner}/{repo} → Issues → New Issue` cannot start.

## Training memory (v2)

Built fresh by `run build-memory` from 11 explicitly named episodes (10 successful, ingested; `repos-4` failed and
taught nothing). Manifest with run ids, task ids, task-definition hashes, goal hashes, file hashes and the graph
fingerprint: [memory/manifest.json](memory/manifest.json). Graph `pathmemory_v2`, fingerprint `ff0899ff00fbb4d5`.

- No held-out task (TEST or RECOVERY list) is in it; the builder refuses such episodes and episodes whose goal
  differs from the task's current definition (both tested).
- v1 memory contained a `members-2` repair episode, and `members-2` is a test task. v2 does not. The
  Explore → repository step that `members-2` supplied in v1 now comes from a new training task, `explore-3`
  ("Using the Explore page's list of repositories (not the dashboard), open the a11yproject.com repository."),
  run once with no memory on the normal UI (2026-10-18 17:56, 3 steps, success). A first attempt with different
  wording ("Go to the Explore page and open …") failed: the agent navigated correctly, then kept re-doing
  "go to Explore" for 15 steps. That run is kept in `results/v2-train/` and excluded: the builder refuses it
  because its goal is not the current definition.
- v2 is **not** identical to v1: see [memory/v1_vs_v2.json](memory/v1_vs_v2.json) (task sets differ, the dashboard
  step's landmark is no longer over-templated, counters differ).

## The graph's decision

Replay first asks FalkorDB for the shortest verified route from `/` to `/:owner/:repo/issues/new`
([composition.json](composition.json), regenerate with `python -m pathmemory.evaluation.composition`):

```cypher
MATCH (a:State {key:$src}), (b:State {key:$dst})
MATCH p = (a)-[:ACT*1..6]->(b)
WHERE all(r IN relationships(p) WHERE r.successes > 0 AND NOT r.eid IN $banned)
RETURN [n IN nodes(p) | n.key] AS keys,
       [r IN relationships(p) | [r.eid, r.role, r.name, r.scope, r.sources]] AS edges,
       length(p) AS hops, reduce(f = 0, r IN relationships(p) | f + r.failures) AS fails
ORDER BY hops, fails LIMIT 3
```

1. `banned = []` → route 1: `/ → /:owner/:repo → issues → issues/new` (3 hops, all from `issues-1`, which
   itself contains this whole route).
2. On the broken page the dashboard link `{owner}/{repo}` is not there; replay bans that step
   (`c114f1b71d3c`) for this run only and asks again. `banned = [c114f1b71d3c]` → the only route:

| hop | step (role, name, landmark) | taught by (training episode) |
|---|---|---|
| `/` → `/explore/repos` | link `Explore` [navigation:Navigation Bar] | explore-1, explore-3 |
| `/explore/repos` → `/:owner/:repo` | link `{repo}` [main:Explore] | **explore-3 only** |
| `/:owner/:repo` → `/:owner/:repo/issues` | link `Issues` [navigation] | **issues-1 only** |
| `/:owner/:repo/issues` → `/:owner/:repo/issues/new` | link `New Issue` [main:Issues] | **issues-1 only** |

Source ids are the run-directory names, stored on each FalkorDB edge as `r.sources` and in the manifest.
**Two episodes are essential** (removing either removes a hop); a third (explore-1) also taught hop 1.

## Absent from every individual episode

`composition.json → single_episode_containment` checks each of the 10 ingested episodes' own navigation steps:
none contains the route as a contiguous sequence, and none even contains all four steps anywhere
(explore-3 has hops 1–2, issues-1 hops 3–4, explore-1 hop 1). Automated:
`tests/test_composition.py::test_composed_route_is_absent_from_every_individual_training_episode` (runs from the
committed evidence, no infrastructure), plus `test_live_cypher_matches_committed_evidence` against FalkorDB.

Flat replay (one stored trajectory at a time, same chooser and matcher) finds the 3-hop `issues-1` route on the
normal UI and **no route** once the dashboard step is banned.

## Ablation

`run ablate --snapshot pathmemory_v2 --graph pathmemory_v2_ablated --edge fc698e14a7f1` copies the graph and
removes the bridge step (`/explore/repos → {repo}`); the original is checked unchanged
([memory/ablation.json](memory/ablation.json), ablated fingerprint `93e0b6bd12e2831c`). On the copy, the same
query with the dashboard step banned returns **no route**; without the ban it still returns the dashboard route.

## Fail-closed checks in the real browser (no LLM)

[probes.jsonl](probes.jsonl), `python -m pathmemory.evaluation.probe`: scripted destination choice, real Gitea + Chromium,
v2 memory, base agent replaced by an immediate stop.

- **wrong entity**: choice `owner=a11yproject, repo=design`. Dashboard has no such link → rerouted via Explore,
  where link `design` points to `/primer/design`. Replay refused it **before clicking** (`wrong_entity`, from the
  link's href) and stopped: 1 replayed click (Explore), 0 wrong-target actions.
- **ambiguous**: a fork `byteblaze/design` created through the API for this probe, dashboard links hidden. On
  Explore, `design` names two different repositories → `ambiguous`, nothing clicked, replay stopped. The fixture
  was reset afterwards.

## Browser outcome

`run eval issues-2 --modes none flat flatreplay graph --break-ui --trials 5` with the v2 snapshot
([runs/broken.jsonl](runs/broken.jsonl)). In **5/5 graph trials** the agent's log is the same:

```
choose     target /:owner/:repo/issues/new, bindings owner=primer repo=design
route      / → /:owner/:repo → issues → issues/new
edge_failed  link '{owner}/{repo}': missing          (hidden by the UI break; banned for this run only)
route      / → /explore/repos → /:owner/:repo → issues → issues/new
recovered
replay     Explore → design → Issues → New Issue      (4 clicks, no LLM; each landing page and owner/repo verified)
```

Then the LLM filled the title, picked carol, pressed Create Issue and reported. Checker passed in 5/5. Mean 6.0 model
calls (1 chooser + 5 base), 14,986 input tokens. Flat replay and the ablated graph never reached the goal page by
replay (0/5 each); their task successes were LLM fallbacks. Full table and the cases where other modes did as well
or better: [FAIR_COMPARISON.md](FAIR_COMPARISON.md). Step-by-step screenshots: [DEMO_WALKTHROUGH.md](DEMO_WALKTHROUGH.md).

Every replayed click in the v2 runs (57) was re-checked offline against the stored v2 memory
([replaycheck_v2_memory.json](replaycheck_v2_memory.json)): same element, stored name, role and landmark match the
page, and the destination and entities match. The one exception is the first wrong-entity probe, run before the
pre-click href check existed: it deliberately clicked into primer/design under an impossible binding, and the
arrival check stopped it.
