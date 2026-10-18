# Architecture

PathMemory wraps AgentLab's GenericAgent. BrowserGym supplies observations and executes
browser actions; FalkorDB stores page templates, navigation steps, and past work.
The Gitea fixture and task checkers provide a repeatable local demo.

![Learning and replay](../architecture.gif)

The [interactive diagram](architecture.html) and its [source](architecture.archify.json)
are also available in this directory.

## Runtime flow

1. `state.py` maps the observed URL to a page template and extracts entity bindings.
   Accessibility nodes supply an element's role, name, and nearest landmark.
2. `learn.py` ingests successful saved runs. Navigation between page templates becomes
   graph edges; other actions describe work performed on a page. The Gitea task registry
   supplies training goals and task definitions.
3. `agent.py` asks the model to choose a known destination and its entity values. Invalid
   chooser responses return control to the base agent.
4. `graph.py` queries a bounded path from the current template to the destination, excluding
   steps banned during this run. It orders routes by hop count, then accumulated failures.
5. Replay resolves a remembered target on the current page and verifies the landing
   template and chosen entities. A failed step is banned and an alternative route is tried.
   When replay ends, the base agent completes the task.

The graph composes routes from stored edges. It does not choose the goal, infer arbitrary
website semantics, or execute forms independently of the base model.

## Graph model

```text
(:State {key, route, title})
(:State)-[:ACT {eid, kind, role, name, scope, pre,
               successes, failures, sources}]->(:State)
(:Task {id, goal, cluster})-[:WORKED_AT {steps}]->(:State)
```

A state key is a page template plus functional query parameters and, where observed, an
open-dialog marker. Entity names are stored separately and substituted into remembered
action names. Prerequisite clicks can open a menu before navigation.

The route query in `graph.py` is:

```cypher
MATCH (a:State {key:$src}), (b:State {key:$dst})
MATCH p = (a)-[:ACT*1..6]->(b)
WHERE all(r IN relationships(p) WHERE r.successes > 0 AND NOT r.eid IN $banned)
RETURN [n IN nodes(p) | n.key] AS keys,
       [r IN relationships(p) | [r.eid, r.kind, r.role, r.name, r.pre, r.scope, r.sources]] AS edges,
       length(p) AS hops,
       reduce(f = 0, r IN relationships(p) | f + r.failures) AS fails
ORDER BY hops, fails LIMIT $k
```

The default maximum is six hops. Success/failure counters affect route ordering; a failure
report alone does not permanently disable an edge. Callers can exclude it explicitly.

## Verification boundaries

- The matcher requires visibility data and matches role, normalized name, and stored landmark.
  Hidden, missing, out-of-scope, and ambiguous targets stop replay.
- Several visible matches are accepted if they have the same href. This handles repeated
  links to the same destination; it is not a strict one-element rule.
- A legacy stored landmark with unresolved placeholders is logged as `scope_unverifiable`
  and omitted from matching. Visibility and duplicate-target checks still apply.
- Available hrefs are checked for conflicting entity values before navigation. Afterward,
  the page template and entity values present in both the choice and URL are checked.
  The parser is Gitea-specific and does not establish identity across arbitrary domains.
- Reusable navigation is limited by element role to links, tabs, and menu items. This is a
  demo policy, not a general guarantee that a website's links cannot change data. Buttons
  can be replayed as menu-opening prerequisites learned from successful runs.
- MCP `record_step` accepts caller-reported navigation. It does not inspect a browser,
  store a landmark, or independently validate that the transition happened.
- Evaluation uses memory copies and does not record failed replay steps into them. Live
  learning and MCP write tools are separate paths that can modify their selected graph.

## Code boundaries

`service.py` exposes graph operations used by MCP and the UI. `demo/runs.py` reads published
summaries and local run artifacts. `demo/app.py` serves the UI and starts live-run subprocesses.
`evaluation/` contains experiment execution, accounting, comparison, and provenance checks.
The root command modules remain compatibility entry points.

Prompt text lives in `prompts.py`. Configuration defaults to a source checkout; an installed
package can locate that checkout through `PATHMEMORY_ROOT`. The demo reads evidence files
from it and writes new browser artifacts under `results/`.
