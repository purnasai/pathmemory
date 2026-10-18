# Teaching a browser agent to remember a website with FalkorDB

*Draft — Graph Hacks 2026 (WeMakeDevs × FalkorDB)*

Watch an LLM browser agent work for a while and you notice something wasteful. Ask it to add a collaborator to a
repository and it reasons its way to the repo, then to Settings, then to Collaborators. Ask it again for a
different repo and it reasons the whole way again. Every one of those clicks is a model call. It never learns the
site.

I wanted to see whether a graph database could fix that. The result is **PathMemory**: procedural memory for
browser agents, stored in FalkorDB.

## The idea: a website is a graph of pages you have proven you can reach

Each time the agent clicks a link and lands on a new page, that is a fact: *from this kind of page, clicking this
element takes you to that kind of page.* PathMemory stores those facts as edges between page templates:

- `/byteblaze/dotfiles/settings/collaboration` and `/primer/design/settings/collaboration` are the same node,
  `/:owner/:repo/settings/collaboration`.
- An edge is a click identified by what the element *is* (role + accessible name, like link "Settings"), with repo
  and owner names turned into placeholders (`{repo}`), and counters for how often it worked or failed.

On a new task, one LLM call picks the destination page. A Cypher query finds the shortest verified route to it.
The agent replays those clicks without calling the model, checks every page it lands on, and only then hands control
back to the LLM for the part that actually needs judgment: filling the form, pressing the button.

## Building it

- **Site:** a local Gitea (≈150 MB) seeded with users, orgs, repos and issues. It resets in 9 seconds, which made
  repeatable experiments cheap. (I skipped WebArena's 30 GB GitLab image on purpose.)
- **Agent:** AgentLab's GenericAgent on BrowserGym, unchanged. PathMemory wraps it.
- **Tasks:** 24 tasks in 6 groups (collaborators, issues, profile settings, repos, explore, social), each checked
  automatically through the Gitea API, the final URL or the agent's answer.
- **Baselines:** the same agent with no memory, and with "flat" memory: the top three most similar past
  trajectories pasted into the prompt. Same model, prompt, step budget and hint channel in every mode.

## What broke along the way

Most of the work was in the details nobody puts in the diagram:

- **Same name, different link.** Gitea has an "Issues" link in the top bar *and* a repo "Issues" tab. The first
  replay clicked the wrong one. Fix: remember which page region (landmark) the element was in.
- **Badges.** "Issues 4" on one repo is "Issues 2" on another. Strip the counts.
- **Dropdowns.** Some links only exist after opening a menu, and that click doesn't change the page. Edges now carry
  prerequisite clicks.
- **Memory confused the agent.** After forking a repo, the agent landed on `/byteblaze/design`, the same template
  as `/primer/design`. My hint said "you're on the page where the work happens", so it forked again, and again. The
  hint now names the exact URL where replay ended.
- **My own answer key was wrong.** Gitea's commit counter on the repo page is cached and disagreed with the API.
  The agents answered what the page showed; I was the one who was wrong.

## Results

The honest headline first: on this site the model completes the tasks without memory too. What memory changes is
how the agent gets there and what it costs.

The test that matters for a graph: I broke the site with a script that hides every repository link on the
dashboard, so the usual first step `/ → {owner}/{repo}` disappears. The held-out task was to create an issue in
primer/design and assign it to carol. The memory came from ten successful runs of *training* tasks; none of them
was this task.

FalkorDB first returns the usual 3-hop route. Replay finds the dashboard link missing, bans that step and asks
again, and gets `/ → Explore → {repo} → Issues → New Issue`. The Explore and repository hops were taught by one
training run (`explore-3`), Issues and New Issue by another (`issues-1`). No single run contains that route.

Five trials per mode, same model (`gpt-6-luna`):

- Graph-composed replay reached the New Issue page in **5/5** trials; replaying a single stored trajectory in
  **0/5**; the graph with that one bridge edge removed in **0/5**.
- Every mode passed the task checker 5/5: when replay can't help, the LLM finds its own way.
- The graph used 6.0 model calls and 15.0k input tokens per task, against 7.0 and 20.6k with no memory.
- No memory used fewer browser actions (7 vs 9): the activity feed still links the issue, and the LLM took a
  2-click shortcut through a button that memory, which stores only navigation links, can't learn.

## What didn't work, and the limits

- Success didn't move: every mode passed every trial. Memory changed the route and the cost, not the outcome.
- No latency advantage, and no significance test.
- One site, one model, one composition case, five trials per mode, and a UI break I chose myself. These are not
  benchmark numbers.
- My first version (v1) had flaws I found later: its memory included a run of a test task, and its
  "LLM calls" column didn't count every model call. v2 rebuilt the memory from training tasks only; the
  corrections are documented in the repo.

## Try it

The code, results and a demo UI are at **https://github.com/purnasai/pathmemory**. The memory is also exposed as an
MCP server with six tools (`find_route`, `report_failure`, `record_step`, …), so any agent can ask it how to get
somewhere.

The takeaway I didn't expect: the useful unit of agent memory wasn't the trajectory, it was the *edge*. Store
verified steps as a graph and routes compose themselves.

---
*This project was built with an AI coding assistant (Claude Code). The author reviewed, tested and can explain every part: graph model, route query, replay and evaluation.*
